import glob
import json
import logging
import os

from whisper import secret
from whisper.storage import store

logger = logging.getLogger(__name__)


class local(store):
    def __init__(self, name="local", parent=None, path="/tmp/whisper"):
        super().__init__(name, parent)
        self.path = path
        if not os.path.exists(self.path):
            os.makedirs(self.path)
            logger.info(f"Created directory {self.path}")

    def get_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return False
        secret_filename = os.path.join(self.path, f"{s.id}.json")
        logger.debug(f"Reading secret from file: {secret_filename}")
        return self.secret_from_file(secret_filename)

    def set_secret(self, s):
        if not s.check_id():
            return False
        secret_filename = os.path.join(self.path, f"{s.id}.json")
        with open(secret_filename, "w") as secret_file:
            json.dump(s.__dict__, secret_file)
        logger.debug(f"Saving secret: {secret_filename}")
        return True

    def delete_secret(self, secret_id):
        s = secret(secret_id)
        secret_filename = os.path.join(self.path, f"{s.id}.json")
        if not s or not s.check_id() or not os.path.exists(secret_filename):
            return True
        logger.info(f"Deleting secret: {secret_id}")
        os.remove(secret_filename)
        return True

    def secret_from_file(self, secret_filename):
        if not os.path.exists(secret_filename):
            return False
        s = secret()
        try:
            with open(secret_filename) as secret_file:
                s.load_from_dict(json.load(secret_file))
        except Exception as e:
            logger.error(f"Could not load secret file [{secret_filename}]: {e}")
            pass
        if not s.check_id():
            return False
        return s

    def delete_expired(self):
        secret_filenames = glob.glob(os.path.join(self.path, "*.json"))
        for secret_filename in secret_filenames:
            secret_id = os.path.splitext(os.path.basename(secret_filename))[0]
            s = self.secret_from_file(secret_filename)
            if not s or s.is_expired():
                self.delete_secret(secret_id)
