import logging

from whisper.storage import store

logger = logging.getLogger(__name__)


class memory(store):
    def __init__(self, name="memory", parent=None):
        self.default_config = {}
        super().__init__(name, parent)

    def start(self):
        self.secrets = {}

    def get_secret(self, secret_id):
        if not self.secrets.get(secret_id):
            return False
        logger.debug(f"Reading memory secret: {self.secrets[secret_id].__dict__}")
        return self.secrets[secret_id]

    def set_secret(self, s):
        if not s.check_id():
            return False
        self.secrets[s.id] = s
        logger.debug(f"Saving memory secret: {self.secrets[s.id].__dict__}")
        return True

    def delete_secret(self, secret_id):
        logger.info(f"Deleting memory secret: {secret_id}")
        self.secrets.pop(secret_id, None)
        return True

    def delete_expired(self):
        to_delete = []
        for secret_id, s in self.secrets.items():
            if not s or s.is_expired():
                to_delete.append(secret_id)
        for secret_id in to_delete:
            self.delete_secret(secret_id)
