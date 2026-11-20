import copy
import logging
import threading
import time

from whisper import check_config, class_loader, secret, short_id

logger = logging.getLogger(__name__)

#: How often S3 and GCS retry a conditional write that another write got to
#: first (a compare-and-swap), before giving up with StorageBusy
CAS_ATTEMPTS = 5


class StorageBusy(Exception):
    """A change to a secret lost to other writes CAS_ATTEMPTS times in a row.
    Nothing was written, so the request can be tried again."""


def _wipe(stored):
    """modify_secret change: drop the ciphertext and auth hash, and keep the
    rest of the record (ID, dates, failed_attempts). None if they're gone."""
    if not stored.data and not stored.hash:
        return None
    stored.data = ""
    stored.hash = ""
    return stored


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
        Never recreates a secret that was deleted in the meantime.
        Returns True if the update was written, False otherwise."""
        return self.backend.update_secret(secret)

    def record_failed_attempt(self, s):
        """Add a wrong password to the stored failed_attempts count,
        atomically, so simultaneous wrong passwords each count. Sets
        s.failed_attempts to the new count. Returns False if the secret is
        gone. Raises StorageBusy if the count couldn't be written."""

        def add_one(stored):
            stored.failed_attempts += 1
            return stored

        _, written = self.backend.modify_secret(s.id, add_one)
        if not written:
            return False
        s.failed_attempts = written.failed_attempts
        return True

    def wipe_secret(self, secret_id):
        """Blank a locked secret's ciphertext and auth hash. It can never be
        opened again, so only what the "locked" answer needs is kept: the
        record, which also keeps the ID taken, its dates and its
        failed_attempts. Returns True if the secret is wiped (now or before)."""
        try:
            stored, written = self.backend.modify_secret(secret_id, _wipe)
        except StorageBusy:
            return False  # the next attempt on the secret wipes it
        if written:
            logger.info(f"Wiped locked secret: {short_id(secret_id)}")
        return stored is not None

    def open_secret(self, s, max_failed_attempts=0):
        """The stored secret, ciphertext included, for a request whose
        password checked out against ``s`` (an earlier read), or False if it
        can't be opened any more: read, locked or deleted since that read.

        It goes by what is stored now, not by ``s``, so wrong passwords
        counted since the read still lock it: simultaneous guesses can't get
        past max_failed_attempts.

        A one-time secret is claimed: atomically replaced with its wiped
        record, so exactly one request gets the ciphertext. The record keeps
        the ID taken until it expires. Otherwise anyone with the link and the
        password could store the secret (or something else) under it again
        after reading it, and the recipient would never see "already viewed".

        Raises StorageBusy if a claim kept losing to other writes."""

        def openable(stored):
            return bool(
                stored
                and not stored.is_wiped()
                and stored.hash == s.hash  # the record the password was checked against
                and not stored.is_locked(max_failed_attempts)
                and not stored.is_expired()
            )

        if s.is_one_time():
            stored, written = self.backend.modify_secret(
                s.id, lambda stored: _wipe(stored) if openable(stored) else None
            )
            return stored if written else False
        stored = self.get_secret(s.id)
        return stored if openable(stored) else False

    def modify_secret(self, secret_id, change):
        """Change a stored secret. ``change`` gets a copy of it and returns
        the secret to write in its place, or None to leave it as it is.
        Returns (stored, written): the secret as read and as written (None if
        change left it), or (None, None) if there's no such secret.

        Backend default: a read and update_secret, so two changes at the same
        moment can undo one another. The built-in backends make it atomic:
        local and memory under a lock, S3 and GCS with a compare-and-swap,
        which raises StorageBusy after CAS_ATTEMPTS lost races."""
        stored = self.get_secret(secret_id)
        if not stored:
            return None, None
        changed = change(copy.copy(stored))
        if changed is None:
            return stored, None
        if not self.update_secret(changed):
            return None, None
        return stored, changed

    def delete_secret(self, secret_id):
        """Delete a secret from the storage backend"""
        logger.info(f"Delete secret: {short_id(secret_id)}")
        return self.backend.delete_secret(secret_id)

    def delete_expired(self):
        """Delete expired secrets from the storage backend"""
        return self.backend.delete_expired()
