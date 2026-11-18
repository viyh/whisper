import importlib
import logging
import os
import re
import secrets
import time

import argon2
import yaml
from werkzeug.middleware.proxy_fix import ProxyFix

logger = logging.getLogger("whisper")

# Argon2id default parameters
DEFAULT_ARGON2_TIME_COST = 5
DEFAULT_ARGON2_MEMORY_COST = 131072  # 128 MB
DEFAULT_ARGON2_PARALLELISM = 1
DEFAULT_ARGON2_HASH_LEN = 32
DEFAULT_ARGON2_SALT_LEN = 16


class UniqueKeyLoader(yaml.SafeLoader):
    """Load YAML and error on duplicate keys"""

    def construct_mapping(self, node, deep=False):
        mapping = set()
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ValueError(key)
            mapping.add(key)
        return super().construct_mapping(node, deep)


class AttrDict(dict):
    """Object with dict keys also accessible as attributes"""

    def __init__(self, mapping=None):
        super().__init__()
        if mapping is not None:
            for key, value in mapping.items():
                self.__setitem__(key, value)

    def __setitem__(self, key, value):
        if isinstance(value, dict):
            value = AttrDict(value)
        super().__setitem__(key, value)
        self.__dict__[key] = value

    def __getattr__(self, item):
        try:
            return self.__getitem__(item)
        except KeyError:
            raise AttributeError(item)

    __setattr__ = __setitem__


class ConfigError(Exception):
    """Configuration Error Base Exception"""

    def __init__(self, config_key="", message="Configuration error"):
        self.message = message
        self.config_key = config_key
        super().__init__(self.message)

    def __str__(self):
        return f"{self.message}: {self.config_key}"


class ConfigMissingError(ConfigError):
    """Configuration Missing Parameter Error Exception"""

    def __init__(self, config_key="", message="Missing configuration parameter"):
        super().__init__(config_key=config_key, message=message)


class ConfigUnknownError(ConfigError):
    """Configuration Unknown Parameter Error Exception"""

    def __init__(self, config_key="", message="Unknown configuration parameter"):
        super().__init__(config_key=config_key, message=message)


def check_config(config_dict, default_config_dict):
    """Confirm that all variables are set and no non-existant variables are set."""
    # check that all keys in the default config have a value set in the config
    for k in default_config_dict:
        if config_dict.get(k) is None:
            raise ConfigMissingError(k, "Missing configuration parameter")

    # check that no extra configuration keys are set
    for k in config_dict:
        if k not in default_config_dict:
            raise ConfigUnknownError(k, "Unknown configuration parameter")

    return AttrDict(config_dict)


def _parse_config_yaml(stream, source):
    """Parse one YAML config document into a dict."""
    try:
        loaded = yaml.load(stream, Loader=UniqueKeyLoader)  # nosec B506
    except ValueError as e:
        # error on duplicate keys
        raise ConfigError(config_key=e, message="Duplicate key in configuration file")
    except yaml.YAMLError as e:
        # error on unparseable YAML
        raise ConfigError(message=f"Config error: {e}")
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(config_key=source, message="Config must be a YAML mapping")
    return loaded


def load_config(config_filenames=None, config_text=None):
    """Load configuration and set default values.

    ``config_text`` (YAML), when given, is used instead of the config files.
    The container passes the WHISPER_CONFIG environment variable here, for
    platforms that can inject secrets as environment variables but not files.
    """
    if config_filenames is None:
        config_filenames = ["config.yaml"]
    default_config = {
        "secret_key": None,  # nosec B105
        "storage_class": None,
        "storage_config": {},
        "storage_clean_interval": 900,
        "max_data_size_kb": 100,
        "app_listen_ip": "0.0.0.0",
        "app_port": "5000",
        "app_url_base": "/",
        "argon2_time_cost": DEFAULT_ARGON2_TIME_COST,
        "argon2_memory_cost": DEFAULT_ARGON2_MEMORY_COST,
        "argon2_parallelism": DEFAULT_ARGON2_PARALLELISM,
        "trusted_proxy_count": 0,
    }

    # initialize config with default values (copy — we mutate this below and
    # don't want to pollute default_config, which check_config compares against)
    config = dict(default_config)
    if config_text is not None:
        config.update(_parse_config_yaml(config_text, "WHISPER_CONFIG"))
        return check_config(config, default_config)
    for config_filename in config_filenames:
        if not os.path.exists(config_filename):
            logger.error(f"Config file does not exist, skipping. {config_filename}")
            continue
        with open(config_filename, "r") as config_file:
            config.update(_parse_config_yaml(config_file, config_filename))
    # check that loaded config is set correctly and return the config object
    return check_config(config, default_config)


def apply_proxy_fix(wsgi_app, trusted_proxy_count=0):
    """Wrap a WSGI app so ``request.remote_addr`` is the real client IP.

    ``trusted_proxy_count`` is how many X-Forwarded-For entries are added by
    proxies in front of the container (load balancers, CDNs). With 0, clients
    connect directly and X-Forwarded-For is ignored. Too low and every client
    shares the proxy's IP (one global rate limit); too high and clients can
    spoof their IP via X-Forwarded-For.
    """
    if (
        isinstance(trusted_proxy_count, bool)
        or not isinstance(trusted_proxy_count, int)
        or trusted_proxy_count < 0
    ):
        raise ConfigError("trusted_proxy_count", "Must be a non-negative integer")
    if trusted_proxy_count == 0:
        return wsgi_app
    # proxies overwrite (rather than append to) X-Forwarded-Proto, so only
    # the nearest one is trusted for the scheme
    return ProxyFix(wsgi_app, x_for=trusted_proxy_count, x_proto=1, x_host=0)


_LOG_ID_CHARS = frozenset("0123456789abcdefABCDEF")


def short_id(secret_id):
    """Loggable form of a secret ID.

    A secret ID is the random part of the share link, so full IDs in logs
    would hand every live link to anyone who can read the logs. The first 8
    hex characters are enough to correlate log lines but not to rebuild the
    link. Non-hex characters are dropped, so attacker-supplied IDs from the
    URL can't inject into logs either.
    """
    if not isinstance(secret_id, str):
        return "..."
    return "".join(c for c in secret_id[:8] if c in _LOG_ID_CHARS) + "..."


# Any run of 40+ hex characters, in either case and whatever surrounds it, so
# IDs are caught after a URL base without a trailing slash ("/s<id>") or next
# to percent-encoding ("%2F<id>"). Longer hex strings (e.g. digests) are
# shortened too, which is harmless in logs.
_SECRET_ID_PATTERN = re.compile(r"[0-9A-Fa-f]{40,}")


def redact_secret_ids(text):
    """Shorten every secret ID (40 hex characters) in text, e.g. URLs."""
    return _SECRET_ID_PATTERN.sub(lambda m: m.group(0)[:8] + "...", text)


def class_loader(classname, *args, **kwargs):
    """Dynamicly import class"""
    mymodule = importlib.import_module(classname.rsplit(".", 1)[0])
    myclass = getattr(mymodule, classname.rsplit(".", 1)[1])
    return myclass(*args, **kwargs)


def create_argon2_hasher(time_cost=None, memory_cost=None, parallelism=None):
    """Create an Argon2id password hasher with given or default parameters."""
    return argon2.PasswordHasher(
        time_cost=time_cost or DEFAULT_ARGON2_TIME_COST,
        memory_cost=memory_cost or DEFAULT_ARGON2_MEMORY_COST,
        parallelism=parallelism or DEFAULT_ARGON2_PARALLELISM,
        hash_len=DEFAULT_ARGON2_HASH_LEN,
        salt_len=DEFAULT_ARGON2_SALT_LEN,
        type=argon2.Type.ID,
    )

# Default hasher, replaced by app.py after config is loaded
_argon2_hasher = create_argon2_hasher()


#: Current stored-secret format version. New secrets are always written with
#: this version. The field is retained in the on-disk format and in the API
#: envelope so a future v3 can ship without breaking already-stored v2 data;
#: today, any version other than this is rejected.
CURRENT_SECRET_VERSION = 2


class secret:
    """Secret Class"""

    REQUIRED_ATTRS = frozenset({"id", "create_date", "expire_date", "data", "hash"})
    OPTIONAL_ATTRS = frozenset({"version", "failed_attempts"})

    def __init__(self, secret_id=None, expiration=None, key_pass=None, data=None):
        self.id = secret_id
        self.create_date = None
        self.expire_date = None
        self.data = None
        self.hash = None
        self.version = CURRENT_SECRET_VERSION
        self.failed_attempts = 0
        if not self.id and expiration and key_pass and data:
            self.create(expiration, key_pass, data)

    def load_from_dict(self, secret_dict):
        """Load secret from a dict object"""
        # check if dict has all required attributes
        if not self.REQUIRED_ATTRS.issubset(set(secret_dict)):
            logger.debug("Secret dict is missing required attributes.")
            return False
        # check for unknown attributes
        if not set(secret_dict).issubset(self.REQUIRED_ATTRS | self.OPTIONAL_ATTRS):
            logger.debug("Secret dict has unknown attributes.")
            return False
        # set attributes
        for key, value in secret_dict.items():
            setattr(self, key, value)
        return True

    def check_id(self):
        """Check if ID is set and valid"""
        return self.id and self.id.isalnum() and len(self.id) == 40

    def new_id(self):
        """Generate a new ID unless one is already set"""
        if self.id:
            return False
        self.id = secrets.token_hex(20)
        return True

    def create(self, expiration, key_pass, data):
        """Create a new secret"""
        self.version = CURRENT_SECRET_VERSION
        self.new_id()
        self.create_date = int(time.time())
        self.set_expire_date(expiration)
        self.set_password(key_pass)
        self.data = data

    def set_expire_date(self, expiration):
        """Get epoch seconds of expiration date."""
        now = int(time.time())
        if expiration == "1 hour":
            self.expire_date = now + 3600
        elif expiration == "1 day":
            self.expire_date = now + 86400
        elif expiration == "1 week":
            self.expire_date = now + 86400 * 7
        else:
            self.expire_date = -1

    def is_expired(self):
        """Check if secret is expired"""
        now = int(time.time())
        return (
            self.expire_date
            and now >= self.expire_date
            and (
                not self.is_one_time()
                or (self.create_date and now - self.create_date >= 86400 * 30)
            )
        )

    def is_one_time(self):
        """Check if secret is one-time"""
        return self.expire_date == -1

    def get_key_pass(self, password, key):
        """Generate the site unique password"""
        return key.encode("utf-8") + password.encode("utf-8")

    def check_password(self, key_pass):
        """Check if a key_pass matches the stored Argon2id hash."""
        if not self.hash:
            return False
        try:
            return _argon2_hasher.verify(self.hash, key_pass)
        except argon2.exceptions.VerifyMismatchError:
            return False
        except argon2.exceptions.VerificationError:
            return False

    def set_password(self, key_pass):
        """Generate Argon2id hash and store it."""
        self.hash = _argon2_hasher.hash(key_pass)
