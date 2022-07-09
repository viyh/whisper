import logging
import threading
import time

from whisper import class_loader, secret, check_config

logger = logging.getLogger(__name__)


class store_cleaner:
    def __init__(self, store):
        logger.debug("Cleaner - Init")
        self.store = store
        self.thread = threading.Thread(name="store_cleaner", target=self.run, args=())
        self.thread.daemon = True
        if not self.thread.is_alive():
            logger.debug("Cleaner - Thread start")
            self.thread.start()

    def run(self):
        while True:
            logger.info("Cleaner - Deleting expired secrets")
            self.store.delete_expired()
            logger.info(f"Cleaner - Sleeping for {self.store.clean_interval} seconds")
            time.sleep(self.store.clean_interval)


class store:
    def __init__(self, storage_class, storage_config={}, clean_interval=900):
        self.clean_interval = clean_interval
        self.storage_class = storage_class
        self.storage_config = storage_config

    def start(self):
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
        s = self.backend.get_secret(secret_id)
        if isinstance(s, secret) and s.check_id():
            return s
        else:
            return False

    def set_secret(self, secret):
        return self.backend.set_secret(secret)

    def delete_secret(self, secret_id):
        logger.info(f"Delete secret: {secret_id}")
        return self.backend.delete_secret(secret_id)

    def delete_expired(self):
        return self.backend.delete_expired()
