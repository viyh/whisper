import json
import logging
import os

import boto3
from whisper import secret
from whisper.storage import store

logger = logging.getLogger(__name__)


class s3(store):
    def __init__(self, name="s3", parent=None):
        self.default_config = {"bucket_name": None, "bucket_path": ""}
        super().__init__(name, parent)

    def start(self):
        self.client = boto3.client("s3")

    def get_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return False
        secret_filename = f"{s.id}.json"
        logger.debug(f"Reading S3 secret from file: {secret_filename}")
        return self.secret_from_s3_obj(secret_filename)

    def set_secret(self, s):
        if not s.check_id():
            return False
        logger.debug(f"Saving S3 secret: {s.id}")
        self.put_s3_obj(s)
        return True

    def delete_secret(self, secret_id):
        logger.info(f"Deleting S3 secret: {secret_id}")
        self.delete_s3_obj(f"{secret_id}.json")
        return True

    def delete_expired(self):
        store_objs = self.client.list_objects_v2(
            Bucket=self.config.bucket_name, Prefix=self.config.bucket_path
        )
        for store_obj in store_objs.get("Contents", []):
            secret_id, ext = os.path.splitext(os.path.basename(store_obj["Key"]))
            if ext != ".json":
                continue
            s = secret(secret_id)
            s.create_date, s.expire_date = self.get_s3_obj_dates(store_obj["Key"])
            if s.check_id() and s.is_expired():
                self.delete_secret(secret_id)

    def get_s3_obj_dates(self, full_key):
        tagset = self.client.get_object_tagging(
            Bucket=self.config.bucket_name, Key=full_key
        ).get("TagSet")
        create_date, expire_date = 0, 0
        for tag in tagset:
            if tag["Key"] == "create_date":
                create_date = int(tag["Value"])
            elif tag["Key"] == "expire_date":
                expire_date = int(tag["Value"])
        return create_date, expire_date

    def delete_s3_obj(self, key):
        full_path = os.path.join(self.config.bucket_path, key)
        try:
            self.client.delete_object(Bucket=self.config.bucket_name, Key=full_path)
        except self.client.exceptions.NoSuchKey:
            pass
        return True

    def get_s3_obj(self, key):
        full_path = os.path.join(self.config.bucket_path, key)
        try:
            store_obj = self.client.get_object(
                Bucket=self.config.bucket_name, Key=full_path
            )
        except self.client.exceptions.NoSuchKey:
            return False
        return store_obj

    def put_s3_obj(self, s):
        full_path = os.path.join(self.config.bucket_path, f"{s.id}.json")
        self.client.put_object(
            Body=bytes(json.dumps(s.__dict__).encode("utf-8")),
            Bucket=self.config.bucket_name,
            Key=full_path,
            Tagging=f"create_date={s.create_date}&expire_date={s.expire_date}",
        )
        return True

    def secret_from_s3_obj(self, secret_filename):
        store_obj = self.get_s3_obj(secret_filename)
        if not store_obj:
            return False

        s = secret()
        try:
            s.load_from_dict(json.load(store_obj["Body"]))
        except Exception as e:
            logger.error(f"Could not parse S3 file: {e}")

        if s and s.check_id():
            return s
        else:
            return False
