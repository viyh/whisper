import importlib
import logging
import os
import secrets
import time

import bcrypt
import yaml

logger = logging.getLogger("whisper")


class secret:
    def __init__(self, secret_id=None, expiration=None, key_pass=None, data=None):
        self.id = secret_id
        self.create_date = None
        self.expire_date = None
        self.data = None
        self.hash = None
        if not self.id and expiration and key_pass and data:
            self.create(expiration, key_pass, data)

    def load_from_dict(self, secret_dict):
        attr = ["id", "create_date", "expire_date", "data", "hash"]
        # check if dict has appropriate attributes
        if set(attr) != set(secret_dict):
            logger.debug("Secret dict is missing some attributes.")
            return False
        # set attributes
        for key, value in secret_dict.items():
            setattr(self, key, value)
        return True

    def check_id(self):
        return self.id and self.id.isalnum() and len(self.id) == 40

    def new_id(self):
        if self.id:
            return False
        self.id = secrets.token_hex(20)
        return True

    def create(self, expiration, key_pass, data):
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
        now = int(time.time())
        return self.expire_date and now >= self.expire_date and self.expire_date != -1

    def is_one_time(self):
        return self.expire_date == -1

    def is_data_url(self):
        if self.data.startswith("s3://"):
            return True
        else:
            return False

    def get_key_pass(self, password, key):
        return key.encode("utf-8") + password.encode("utf-8")

    def check_password(self, key_pass):
        """Check if a key_pass matches the stored salted SHA"""
        if not self.hash:
            return False
        return bcrypt.checkpw(key_pass, self.hash.encode("utf-8"))

    def set_password(self, key_pass, salt_rounds=12):
        """Generate salted hash and store it"""
        salt = bcrypt.gensalt(rounds=salt_rounds)
        self.hash = bcrypt.hashpw(key_pass, salt).decode("utf-8")


def load_config(config_filenames=["config.default.yaml", "config.yaml"]):
    config = {}
    for config_filename in config_filenames:
        if not os.path.exists(config_filename):
            logger.error(f"Config file does not exist, skipping. {config_filename}")
            continue
        with open(config_filename, "r") as config_file:
            try:
                config.update(yaml.safe_load(config_file))
            except yaml.YAMLError as e:
                logger.error(f"Config error: {e}")
    return config


def class_loader(classname, *args, **kwargs):
    mymodule = importlib.import_module(classname.rsplit(".", 1)[0])
    myclass = getattr(mymodule, classname.rsplit(".", 1)[1])
    return myclass(*args, **kwargs)
