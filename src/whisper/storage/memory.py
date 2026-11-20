import copy
import logging
import threading

from whisper import short_id
from whisper.storage import store

logger = logging.getLogger(__name__)


class memory(store):
    def __init__(self, name="memory", parent=None):
        self.default_config = {}
        self._lock = threading.Lock()
        super().__init__(name, parent)

    def start(self):
        self.secrets = {}

    def get_secret(self, secret_id):
        with self._lock:
            s = self.secrets.get(secret_id)
        if not s:
            return False
        logger.debug(f"Reading memory secret: {short_id(secret_id)}")
        # return a copy so callers can't mutate stored state without going
        # through set_secret/update_secret (matches the other backends)
        return copy.copy(s)

    def set_secret(self, s):
        if not s.check_id():
            return False
        with self._lock:
            if s.id in self.secrets:  # create-only: never replace a secret
                return False
            self.secrets[s.id] = copy.copy(s)
        logger.debug(f"Saving memory secret: {short_id(s.id)}")
        return True

    def update_secret(self, s):
        if not s.check_id():
            return False
        with self._lock:
            if s.id not in self.secrets:
                return False
            self.secrets[s.id] = copy.copy(s)
        logger.debug(f"Updating memory secret: {short_id(s.id)}")
        return True

    def modify_secret(self, secret_id, change):
        """Change a stored secret atomically (under the lock)."""
        with self._lock:
            stored = self.secrets.get(secret_id)
            if not stored:
                return None, None
            changed = change(copy.copy(stored))
            if changed is not None:
                self.secrets[secret_id] = copy.copy(changed)
        return copy.copy(stored), changed

    def delete_secret(self, secret_id):
        logger.info(f"Deleting memory secret: {short_id(secret_id)}")
        with self._lock:
            self.secrets.pop(secret_id, None)
        return True

    def delete_expired(self):
        with self._lock:
            to_delete = [
                secret_id
                for secret_id, s in self.secrets.items()
                if not s or s.is_expired()
            ]
        for secret_id in to_delete:
            self.delete_secret(secret_id)
