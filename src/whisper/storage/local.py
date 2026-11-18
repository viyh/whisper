import glob
import json
import logging
import os

from whisper import secret, short_id
from whisper.storage import store

logger = logging.getLogger(__name__)


class local(store):
    def __init__(self, name="local", parent=None, path="/tmp/whisper"):  # nosec B108
        self.default_config = {"path": "/tmp/whisper"}  # nosec B108
        super().__init__(name, parent)

    def start(self):
        if not os.path.exists(self.config.path):
            os.makedirs(self.config.path)
            logger.info(f"Created directory {self.config.path}")

    def get_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return False
        secret_filename = os.path.join(self.config.path, f"{s.id}.json")
        logger.debug(f"Reading secret: {short_id(s.id)}")
        return self.secret_from_file(secret_filename)

    def set_secret(self, s):
        if not s.check_id():
            return False
        secret_filename = os.path.join(self.config.path, f"{s.id}.json")
        # owner-only permissions; secret files are never meant to be shared
        fd = os.open(secret_filename, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as secret_file:
            json.dump(s.__dict__, secret_file)
        logger.debug(f"Saving secret: {short_id(s.id)}")
        return True

    def update_secret(self, s):
        """Rewrite an existing secret file. Opening without O_CREAT fails if the
        file was claimed/deleted, so a claimed secret is never recreated."""
        if not s.check_id():
            return False
        secret_filename = os.path.join(self.config.path, f"{s.id}.json")
        try:
            fd = os.open(secret_filename, os.O_WRONLY | os.O_TRUNC)
        except FileNotFoundError:
            return False
        with os.fdopen(fd, "w") as secret_file:
            json.dump(s.__dict__, secret_file)
        logger.debug(f"Updating secret: {short_id(s.id)}")
        return True

    def delete_secret(self, secret_id):
        s = secret(secret_id)
        secret_filename = os.path.join(self.config.path, f"{s.id}.json")
        if not s or not s.check_id() or not os.path.exists(secret_filename):
            return True
        logger.info(f"Deleting secret: {short_id(secret_id)}")
        os.remove(secret_filename)
        return True

    def claim_secret(self, secret_id):
        """Atomically claim a one-time secret using atomic rename."""
        s = secret(secret_id)
        if not s.check_id():
            return False
        secret_filename = os.path.join(self.config.path, f"{s.id}.json")
        claimed_filename = secret_filename + ".claimed"
        try:
            os.rename(secret_filename, claimed_filename)
            os.remove(claimed_filename)
            return True
        except FileNotFoundError:
            return False

    def secret_from_file(self, secret_filename):
        if not os.path.exists(secret_filename):
            return False
        s = secret()
        try:
            with open(secret_filename) as secret_file:
                s.load_from_dict(json.load(secret_file))
        except (OSError, ValueError) as e:
            reason = e.strerror if isinstance(e, OSError) else e
            secret_id = os.path.splitext(os.path.basename(secret_filename))[0]
            logger.error(f"Could not load secret {short_id(secret_id)}: {reason}")
        if not s.check_id():
            return False
        return s

    def delete_expired(self):
        secret_filenames = glob.glob(os.path.join(self.config.path, "*.json"))
        for secret_filename in secret_filenames:
            secret_id = os.path.splitext(os.path.basename(secret_filename))[0]
            s = self.secret_from_file(secret_filename)
            if not s or s.is_expired():
                self.delete_secret(secret_id)
