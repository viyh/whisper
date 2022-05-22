import json
import logging
import os

from google.cloud import storage
from google.cloud.exceptions import NotFound
from whisper import secret
from whisper.storage import store

logger = logging.getLogger(__name__)


class gcs(store):
    def __init__(self, name="s3", parent=None, bucket_name=None, bucket_path=""):
        super().__init__(name, parent)
        self.bucket_name = bucket_name
        self.bucket_path = bucket_path
        if not self.bucket_name:
            raise (
                "No bucket name specified, please add storage_config -> bucket_name "
                "to the config.yaml file."
            )
        self.client = storage.Client()
        self.bucket = self.client.get_bucket(self.bucket_name)

    def get_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return False
        secret_filename = f"{s.id}.json"
        logger.debug(f"Reading GCS secret from file: {secret_filename}")
        return self.secret_from_gcs_obj(secret_filename)

    def set_secret(self, s):
        if not s.check_id():
            return False
        logger.debug(f"Saving GCS secret: {s.id}")
        self.put_gcs_obj(s)
        return True

    def delete_secret(self, secret_id):
        logger.info(f"Deleting GCS secret: {secret_id}")
        self.delete_gcs_obj(f"{secret_id}.json")
        return True

    def delete_expired(self):
        store_objs = self.client.list_blobs(self.bucket_name, prefix=self.bucket_path)
        for store_obj in store_objs:
            secret_id, ext = os.path.splitext(os.path.basename(store_obj.name))
            if ext != ".json":
                continue
            s = secret(secret_id)
            s.expire_date = self.get_gcs_obj_expire_date(store_obj.name)
            if s.check_id() and s.is_expired():
                self.delete_secret(secret_id)

    def get_gcs_obj_expire_date(self, full_key):
        store_obj = self.bucket.get_blob(full_key)
        expire_date = store_obj.metadata.get("expire_date")
        if not store_obj.metadata or not expire_date:
            return True
        return int(expire_date)

    def delete_gcs_obj(self, key):
        full_path = os.path.join(self.bucket_path, key)
        try:
            self.bucket.delete_blob(full_path)
        except NotFound:
            pass
        return True

    def get_gcs_obj(self, key):
        full_path = os.path.join(self.bucket_path, key)
        store_obj = self.bucket.get_blob(full_path)
        return store_obj

    def put_gcs_obj(self, s):
        full_path = os.path.join(self.bucket_path, f"{s.id}.json")
        store_obj = self.bucket.blob(full_path)
        store_obj.upload_from_string(
            data=bytes(json.dumps(s.__dict__).encode("utf-8")),
            content_type="application/json",
        )
        store_obj.metadata = {"expire_date": s.expire_date}
        store_obj.patch()
        return True

    def secret_from_gcs_obj(self, secret_filename):
        store_obj = self.get_gcs_obj(secret_filename)
        if not store_obj:
            return False

        s = secret()
        try:
            s.load_from_dict(json.loads(store_obj.download_as_bytes().decode()))
        except Exception as e:
            logger.error(f"Could not parse GCS file: {e}")

        if s and s.check_id():
            return s
        else:
            return False
