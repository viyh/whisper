import glob
import json
import logging
import os
import threading
import time

from whisper import secret, short_id
from whisper.storage import store

logger = logging.getLogger(__name__)

#: An unreadable secret file younger than this may be another process
#: halfway through writing it, so the cleaner leaves it alone until then.
UNREADABLE_GRACE_SECONDS = 60


class local(store):
    """Each secret is a ``<path>/<id>.json`` file, readable by its owner only.

    One lock covers every read and write, so within the process a reader never
    sees a half-written file and wrong-password counts are never lost.
    Gunicorn runs a single worker (see gunicorn.conf.py), so that is every
    request.
    """

    def __init__(self, name="local", parent=None, path="/tmp/whisper"):  # nosec B108
        self.default_config = {"path": "/tmp/whisper"}  # nosec B108
        self._lock = threading.RLock()
        super().__init__(name, parent)

    def start(self):
        if not os.path.exists(self.config.path):
            # owner-only: a directory listing shows every stored secret's ID
            os.makedirs(self.config.path, mode=0o700)
            logger.info(f"Created directory {self.config.path}")

    def _filename(self, secret_id):
        return os.path.join(self.config.path, f"{secret_id}.json")

    def get_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return False
        logger.debug(f"Reading secret: {short_id(s.id)}")
        with self._lock:
            return self.secret_from_file(self._filename(s.id))

    def set_secret(self, s):
        if not s.check_id():
            return False
        # create-only (O_EXCL): never replace an existing secret.
        # Owner-only permissions; secret files are never meant to be shared.
        with self._lock:
            try:
                fd = os.open(
                    self._filename(s.id), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
            except FileExistsError:
                return False
            with os.fdopen(fd, "w") as secret_file:
                json.dump(s.__dict__, secret_file)
        logger.debug(f"Saving secret: {short_id(s.id)}")
        return True

    def update_secret(self, s):
        """Rewrite an existing secret file. Opening without O_CREAT fails if the
        file was claimed/deleted, so a claimed secret is never recreated."""
        if not s.check_id():
            return False
        with self._lock:
            return self._rewrite(s)

    def _rewrite(self, s):
        try:
            fd = os.open(self._filename(s.id), os.O_WRONLY | os.O_TRUNC)
        except FileNotFoundError:
            return False
        with os.fdopen(fd, "w") as secret_file:
            json.dump(s.__dict__, secret_file)
        logger.debug(f"Updating secret: {short_id(s.id)}")
        return True

    def increment_failed_attempts(self, s):
        """Count a wrong password atomically: re-read the stored count under
        the lock, so concurrent wrong passwords each count."""
        if not s.check_id():
            return False
        with self._lock:
            stored = self.secret_from_file(self._filename(s.id))
            if not stored:
                return False
            stored.failed_attempts += 1
            if not self._rewrite(stored):
                return False
        s.failed_attempts = stored.failed_attempts
        return True

    def delete_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return True
        try:
            with self._lock:
                os.remove(self._filename(s.id))
        except FileNotFoundError:
            # already gone (claimed, or deleted by a concurrent cleanup)
            return True
        logger.info(f"Deleting secret: {short_id(secret_id)}")
        return True

    def claim_secret(self, secret_id):
        """Atomically claim a one-time secret using atomic rename."""
        s = secret(secret_id)
        if not s.check_id():
            return False
        secret_filename = self._filename(s.id)
        claimed_filename = secret_filename + ".claimed"
        with self._lock:
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
            reason = (e.strerror or type(e).__name__) if isinstance(e, OSError) else e
            secret_id = os.path.splitext(os.path.basename(secret_filename))[0]
            logger.error(f"Could not load secret {short_id(secret_id)}: {reason}")
        if not s.check_id():
            return False
        return s

    def delete_expired(self):
        secret_filenames = glob.glob(os.path.join(self.config.path, "*.json"))
        for secret_filename in secret_filenames:
            secret_id = os.path.splitext(os.path.basename(secret_filename))[0]
            with self._lock:
                s = self.secret_from_file(secret_filename)
                if not s and self._recently_modified(secret_filename):
                    continue
            if not s or s.is_expired():
                self.delete_secret(secret_id)

    @staticmethod
    def _recently_modified(filename):
        try:
            return time.time() - os.path.getmtime(filename) < UNREADABLE_GRACE_SECONDS
        except FileNotFoundError:
            return False
