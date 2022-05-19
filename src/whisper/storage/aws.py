import json
import logging
import os

import boto3
from whisper import secret
from whisper.storage import store

logger = logging.getLogger(__name__)


class s3(store):
    def __init__(self, name="s3", parent=None, bucket_name=None, bucket_path=""):
        super().__init__(name, parent)
        self.bucket_name = bucket_name
        self.bucket_path = bucket_path
        if not self.bucket_name:
            raise (
                "No bucket name specified, please add storage_config -> bucket_name "
                "to the config.yaml file."
            )
        self.s3_client = boto3.client("s3")

    def get_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return False
        secret_filename = f"{s.id}.json"
        logger.debug(f"Reading S3 secret from file: {secret_filename}")
        return self.secret_from_file(secret_filename)

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

    def secret_from_file(self, secret_filename):
        s3_obj = self.get_s3_obj(secret_filename)
        return self.secret_from_s3_obj(s3_obj)

    def delete_expired(self):
        s3_objs = self.s3_client.list_objects_v2(
            Bucket=self.bucket_name, Prefix=self.bucket_path
        )
        for s3_obj in s3_objs.get("Contents", []):
            secret_id = os.path.splitext(os.path.basename(s3_obj["Key"]))[0]
            s = secret()
            s.expire_date = self.get_s3_obj_expire_date(s3_obj["Key"])
            if s.is_expired():
                self.delete_secret(secret_id)

    def get_s3_obj_expire_date(self, full_key):
        tagset = self.s3_client.get_object_tagging(
            Bucket=self.bucket_name, Key=full_key
        ).get("TagSet")
        for tag in tagset:
            if tag["Key"] == "expire_date":
                return int(tag["Value"])
        return False

    def delete_s3_obj(self, key):
        full_path = os.path.join(self.bucket_path, key)
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=full_path)
        except self.s3_client.exceptions.NoSuchKey:
            pass
        return True

    def get_s3_obj(self, key):
        full_path = os.path.join(self.bucket_path, key)
        try:
            s3_obj = self.s3_client.get_object(Bucket=self.bucket_name, Key=full_path)
        except self.s3_client.exceptions.NoSuchKey:
            return False
        return s3_obj

    def put_s3_obj(self, s):
        full_path = os.path.join(self.bucket_path, f"{s.id}.json")
        self.s3_client.put_object(
            Body=bytes(json.dumps(s.__dict__).encode("utf-8")),
            Bucket=self.bucket_name,
            Key=full_path,
            Tagging=f"expire_date={s.expire_date}",
        )
        return True

    def secret_from_s3_obj(self, s3_obj):
        s = secret()
        try:
            s.load_from_dict(json.load(s3_obj["Body"]))
        except Exception as e:
            logger.error(f"Could not parse S3 file: {e}")
        if not s.check_id():
            return False
        return s
