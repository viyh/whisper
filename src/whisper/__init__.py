import hashlib
import hmac
import importlib
import logging
import os
import re
import time

import yaml
from werkzeug.middleware.proxy_fix import ProxyFix

logger = logging.getLogger("whisper")

# Argon2id defaults for the key derivation in the browser (see whisper.js).
# The server passes these to the page; it does no Argon2 hashing itself.
DEFAULT_ARGON2_TIME_COST = 5
DEFAULT_ARGON2_MEMORY_COST = 131072  # 128 MB
DEFAULT_ARGON2_PARALLELISM = 1


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
        "max_failed_attempts": 10,
    }

    # initialize config with default values (copy - we mutate this below and
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


def check_max_failed_attempts(value):
    """Validate max_failed_attempts: wrong passwords allowed per secret before
    it locks until it expires. 0 turns the lock off."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError("max_failed_attempts", "Must be a non-negative integer")
    return value


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

    An ID can't open a secret (it is a one-way hash of the link's token), but
    anyone holding one could send wrong passwords until the secret locks, so
    logs only get the first 8 characters: enough to correlate log lines.
    Non-hex characters are dropped, so attacker-supplied IDs can't inject
    into logs either.
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
    """Shorten every secret ID (40 or 64 hex characters) in text, e.g. URLs."""
    return _SECRET_ID_PATTERN.sub(lambda m: m.group(0)[:8] + "...", text)


def class_loader(classname, *args, **kwargs):
    """Dynamicly import class"""
    mymodule = importlib.import_module(classname.rsplit(".", 1)[0])
    myclass = getattr(mymodule, classname.rsplit(".", 1)[1])
    return myclass(*args, **kwargs)


#: Stored-secret format version. Only this version can be created or read.
#:
#: v3 (0.4.0+): the share link is ``<base>#<token>``, a random 22-character
#: base58 token the browser never sends to the server. From the token and the
#: password, the browser derives (see whisper.js):
#:   - the secret ID: SHA-256 of the token, which the server stores it under
#:   - Argon2id(password, salt=token), split with HKDF into an AES-256-GCM key
#:     and an auth token, which the server checks before releasing the data
#: The server stores only the ciphertext, the ID, and an HMAC of the auth
#: token keyed with ``secret_key``.
CURRENT_SECRET_VERSION = 3

# v3 secret IDs and auth tokens: 64 lowercase hex characters (256 bits).
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
# v2 secret IDs (before 0.4.0). Still recognized as storage keys, so the
# cleaner removes leftover v2 secrets when they expire, but never created or
# read.
_LEGACY_ID_RE = re.compile(r"[0-9a-f]{40}")


def is_secret_id(value):
    """True for a v3 secret ID."""
    return isinstance(value, str) and _HEX64_RE.fullmatch(value) is not None


def is_legacy_secret_id(value):
    """True for a v2 secret ID (before 0.4.0)."""
    return isinstance(value, str) and _LEGACY_ID_RE.fullmatch(value) is not None


def is_auth_token(value):
    """True for a well-formed auth token from the browser."""
    return isinstance(value, str) and _HEX64_RE.fullmatch(value) is not None


def auth_digest(auth, key):
    """What the server stores instead of the auth token: HMAC-SHA256 keyed
    with secret_key. A slow hash isn't needed: the token can't be guessed
    without the link's token, which the server never sees."""
    return hmac.new(key.encode("utf-8"), auth.encode("ascii"), hashlib.sha256).hexdigest()


class secret:
    """Secret Class"""

    REQUIRED_ATTRS = frozenset({"id", "create_date", "expire_date", "data", "hash"})
    OPTIONAL_ATTRS = frozenset({"version", "failed_attempts"})

    def __init__(self, secret_id=None):
        self.id = secret_id
        self.create_date = None
        self.expire_date = None
        self.data = None
        self.hash = None
        self.version = CURRENT_SECRET_VERSION
        self.failed_attempts = 0

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
        """Check the ID is a valid storage key (v3, or a leftover v2 one)."""
        return is_secret_id(self.id) or is_legacy_secret_id(self.id)

    def create(self, secret_id, expiration, auth, key, data):
        """Create a new secret. The ID and auth token come from the browser."""
        self.id = secret_id
        self.version = CURRENT_SECRET_VERSION
        self.create_date = int(time.time())
        self.set_expire_date(expiration)
        self.hash = auth_digest(auth, key)
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

    def check_auth(self, auth, key):
        """Check the browser's auth token against the stored HMAC, in
        constant time."""
        if not isinstance(self.hash, str) or not is_auth_token(auth):
            return False
        return hmac.compare_digest(self.hash, auth_digest(auth, key))
