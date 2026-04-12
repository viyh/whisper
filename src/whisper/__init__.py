import importlib
import logging
import os
import secrets
import time

import argon2
import yaml

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
        super(AttrDict, self).__init__()
        if mapping is not None:
            for key, value in mapping.items():
                self.__setitem__(key, value)

    def __setitem__(self, key, value):
        if isinstance(value, dict):
            value = AttrDict(value)
        super(AttrDict, self).__setitem__(key, value)
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
    for k, v in default_config_dict.items():
        if config_dict.get(k) is None:
            raise ConfigMissingError(k, "Missing configuration parameter")

    # check that no extra configuration keys are set
    for k, v in config_dict.items():
        if k not in default_config_dict.keys():
            raise ConfigUnknownError(k, "Unknown configuration parameter")

    return AttrDict(config_dict)


def load_config(config_filenames=["config.yaml"]):
    """Load configuration file and set default values"""
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
    }

    # initialize config with default values (copy — we mutate this below and
    # don't want to pollute default_config, which check_config compares against)
    config = dict(default_config)
    for config_filename in config_filenames:
        if not os.path.exists(config_filename):
            logger.error(f"Config file does not exist, skipping. {config_filename}")
            continue
        with open(config_filename, "r") as config_file:
            try:
                # load YAML config file
                config.update(yaml.load(config_file, Loader=UniqueKeyLoader))  # nosec B506
            except ValueError as e:
                # error on duplicate keys
                raise ConfigError(
                    config_key=e, message="Duplicate key in configuration file"
                )
            except yaml.YAMLError as e:
                # error on unparseable YAML
                raise ConfigError(message=f"Config error: {e}")
    # check that loaded config is set correctly and return the config object
    return check_config(config, default_config)


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

    REQUIRED_ATTRS = {"id", "create_date", "expire_date", "data", "hash"}
    OPTIONAL_ATTRS = {"version", "failed_attempts"}

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
