import logging
import threading
import time

from whisper import check_config, class_loader, secret, short_id

logger = logging.getLogger(__name__)

#: How often S3 and GCS retry a conditional write or delete that another
#: write got to first (a compare-and-swap), before giving up
CAS_ATTEMPTS = 5


class store_cleaner:
    """Storage cleaner class, deletes expired secrets by running a periodic
    expiration check"""

    def __init__(self, store):
        logger.debug("Cleaner - Init")
        self.store = store
        self.thread = threading.Thread(name="store_cleaner", target=self.run, args=())
        self.thread.daemon = True
        if not self.thread.is_alive():
            logger.debug("Cleaner - Thread start")
            self.thread.start()

    def run(self):
        """Run the cleaner loop, sleep for clean_interval between runs"""
        while True:
            logger.info("Cleaner - Deleting expired secrets")
            try:
                self.store.delete_expired()
            except Exception:
                # Never let a transient backend error kill the cleaner thread;
                # log it and try again on the next interval.
                logger.exception("Cleaner - Error deleting expired secrets")
            logger.info(f"Cleaner - Sleeping for {self.store.clean_interval} seconds")
            time.sleep(self.store.clean_interval)


class store:
    """Storage base class, stores secrets in a backend"""

    def __init__(self, storage_class, storage_config=None, clean_interval=900):
        self.clean_interval = clean_interval
        self.storage_class = storage_class
        self.storage_config = storage_config if storage_config is not None else {}

    def start(self):
        """Import/create configured backend storage object, check the
        configuration for that specific backend, then start the backend and
        cleaner loop.
        """
        self.backend = class_loader(
            self.storage_class,
            "store",
            parent=self,
        )
        config = {**self.backend.default_config, **self.storage_config}
        self.backend.config = check_config(config, self.backend.default_config)
        self.backend.start()
        self.cleaner = store_cleaner(self)

    def get_secret(self, secret_id):
        """Retrieve a secret from the storage backend. Expired secrets are
        treated as missing, so they can't be read before the cleaner runs."""
        s = self.backend.get_secret(secret_id)
        if not isinstance(s, secret) or not s.check_id():
            return False
        if s.is_expired():
            logger.info(f"Secret expired: {short_id(s.id)}")
            return False
        return s

    def set_secret(self, secret):
        """Save a new secret. Never overwrites: returns False if a secret with
        this ID already exists. IDs come from the browser, so this is what
        stops anyone from replacing an existing secret."""
        return self.backend.set_secret(secret)

    def update_secret(self, secret):
        """Save changes to a secret that already exists in the backend.
        Never recreates a secret that was deleted or claimed in the meantime.
        Returns True if the update was written, False otherwise."""
        return self.backend.update_secret(secret)

    def record_failed_attempt(self, secret):
        """Add a wrong password to the secret's failed_attempts count. Never
        recreates a secret that was claimed in the meantime. Returns True if
        the count was written."""
        return self.backend.increment_failed_attempts(secret)

    def wipe_secret(self, secret_id):
        """Blank a locked secret's ciphertext and auth hash. It can never be
        opened again, so only what the "locked" answer needs is kept: the
        record, which also keeps the ID taken, its dates and its
        failed_attempts. Never recreates a secret claimed in the meantime.
        Returns True if the secret is wiped."""
        s = self.backend.get_secret(secret_id)
        if not isinstance(s, secret) or not s.check_id():
            return False
        if not s.data and not s.hash:
            return True
        s.data = ""
        s.hash = ""
        if not self.backend.update_secret(s):
            return False
        logger.info(f"Wiped locked secret: {short_id(secret_id)}")
        return True

    def increment_failed_attempts(self, secret):
        """Backend default: a read-modify-write through update_secret, so two
        wrong passwords at the same moment can count once. The built-in
        backends count atomically instead: local and memory under a lock, S3
        and GCS with a compare-and-swap."""
        secret.failed_attempts += 1
        return self.update_secret(secret)

    def delete_secret(self, secret_id):
        """Delete a secret from the storage backend"""
        logger.info(f"Delete secret: {short_id(secret_id)}")
        return self.backend.delete_secret(secret_id)

    def claim_secret(self, secret_id):
        """Atomically claim a one-time secret (delete and return True if it existed).
        Returns True if this caller won the race, False otherwise."""
        return self.backend.claim_secret(secret_id)

    def delete_expired(self):
        """Delete expired secrets from the storage backend"""
        return self.backend.delete_expired()
