import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

from whisper import secret, short_id
from whisper.storage import store

logger = logging.getLogger(__name__)

# S3 error codes meaning "the object is gone, or changed under us"
_GONE_OR_CHANGED = frozenset(
    {"404", "NoSuchKey", "NotFound", "412", "PreconditionFailed", "ConditionalRequestConflict"}
)


def _gone_or_changed(e):
    return str(e.response.get("Error", {}).get("Code", "")) in _GONE_OR_CHANGED


class s3(store):
    """AWS S3 backend.

    Each secret is stored as ``<bucket_path>/<id>.json``, with its create and
    expire dates mirrored into object tags so the cleaner can decide on expiry
    without downloading every object.

    Concurrency relies on S3 conditional requests on the object's ETag: a
    one-time claim deletes with ``IfMatch`` so exactly one caller wins (plain
    S3 deletes are idempotent and would let every concurrent caller "win"),
    and updates write with ``IfMatch`` so a claimed secret is never recreated.

    botocore retries transient errors; other errors propagate. The cleaner
    thread logs and survives errors raised from ``delete_expired``.
    """

    def __init__(self, name="s3", parent=None):
        self.default_config = {"bucket_name": None, "bucket_path": ""}
        super().__init__(name, parent)

    def start(self):
        self.client = boto3.client("s3")

    def _path(self, secret_id):
        return os.path.join(self.config.bucket_path, f"{secret_id}.json")

    def _list_prefix(self):
        path = self.config.bucket_path.strip("/")
        return f"{path}/" if path else ""

    def _etag(self, path):
        """Return the object's current ETag, or None if it does not exist."""
        try:
            return self.client.head_object(Bucket=self.config.bucket_name, Key=path)[
                "ETag"
            ]
        except ClientError as e:
            if _gone_or_changed(e):
                return None
            raise

    def get_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return False
        path = self._path(s.id)
        logger.debug(f"Reading S3 secret: {short_id(s.id)}")
        try:
            raw = self.client.get_object(Bucket=self.config.bucket_name, Key=path)[
                "Body"
            ].read()
        except ClientError as e:
            if _gone_or_changed(e):
                return False
            raise
        s = secret()
        try:
            if not s.load_from_dict(json.loads(raw)):
                return False
        except ValueError as e:
            logger.error(f"Could not parse S3 secret {short_id(secret_id)}: {e}")
            return False
        return s if s.check_id() else False

    def _upload(self, s, **conditions):
        self.client.put_object(
            Bucket=self.config.bucket_name,
            Key=self._path(s.id),
            Body=json.dumps(s.__dict__).encode("utf-8"),
            ContentType="application/json",
            Tagging=f"create_date={s.create_date}&expire_date={s.expire_date}",
            **conditions,
        )

    def set_secret(self, s):
        if not s.check_id():
            return False
        logger.debug(f"Saving S3 secret: {short_id(s.id)}")
        self._upload(s)
        return True

    def update_secret(self, s):
        """Overwrite only if the object still exists, pinned to its current
        ETag so a concurrent claim/delete makes this a no-op."""
        if not s.check_id():
            return False
        etag = self._etag(self._path(s.id))
        if etag is None:
            return False
        try:
            self._upload(s, IfMatch=etag)
        except ClientError as e:
            if _gone_or_changed(e):
                return False
            raise
        logger.debug(f"Updated S3 secret: {short_id(s.id)}")
        return True

    def delete_secret(self, secret_id):
        logger.info(f"Deleting S3 secret: {short_id(secret_id)}")
        # S3 deletes of missing keys succeed, so no NotFound handling needed
        self.client.delete_object(
            Bucket=self.config.bucket_name, Key=self._path(secret_id)
        )
        return True

    def claim_secret(self, secret_id):
        """Atomically claim a one-time secret by deleting with ETag match."""
        path = self._path(secret_id)
        etag = self._etag(path)
        if etag is None:
            return False
        try:
            self.client.delete_object(
                Bucket=self.config.bucket_name, Key=path, IfMatch=etag
            )
        except ClientError as e:
            if _gone_or_changed(e):
                return False
            raise
        return True

    def delete_expired(self):
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.config.bucket_name, Prefix=self._list_prefix()
        )
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                secret_id, ext = os.path.splitext(os.path.basename(key))
                # only touch objects that are exactly <bucket_path>/<id>.json
                if ext != ".json" or key != self._path(secret_id):
                    continue
                s = secret(secret_id)
                if not s.check_id():
                    continue
                dates = self._dates_from_tags(key)
                if dates is None:
                    # no usable tags (missing, or object just deleted): fall
                    # back to reading the dates from the object itself
                    stored = self.get_secret(secret_id)
                    if not stored:
                        logger.warning(f"Skipping unreadable S3 secret: {short_id(secret_id)}")
                        continue
                    dates = (stored.create_date, stored.expire_date)
                s.create_date, s.expire_date = dates
                if s.is_expired():
                    self.delete_secret(secret_id)

    def _dates_from_tags(self, path):
        try:
            tagset = self.client.get_object_tagging(
                Bucket=self.config.bucket_name, Key=path
            ).get("TagSet", [])
        except ClientError as e:
            if _gone_or_changed(e):
                return None
            raise
        tags = {tag["Key"]: tag["Value"] for tag in tagset}
        try:
            return int(tags["create_date"]), int(tags["expire_date"])
        except (KeyError, ValueError):
            return None
