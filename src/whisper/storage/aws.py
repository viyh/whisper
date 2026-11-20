import copy
import json
import logging
import posixpath

import boto3
from botocore.exceptions import ClientError

from whisper import secret, short_id
from whisper.storage import CAS_ATTEMPTS, StorageBusy, store

logger = logging.getLogger(__name__)

# S3 error codes meaning "the object is gone, or changed under us"
_GONE_OR_CHANGED = frozenset(
    {"404", "NoSuchKey", "NotFound", "412", "PreconditionFailed", "ConditionalRequestConflict"}
)


# S3 error codes meaning "a conditional write was refused": the object
# already exists, or a concurrent conditional write won
_WRITE_REFUSED = frozenset(
    {"412", "PreconditionFailed", "409", "ConditionalRequestConflict"}
)


#: _dates_from_tags result for an object that was deleted after the listing
_GONE = object()


def _error_code(e):
    return str(e.response.get("Error", {}).get("Code", ""))


def _gone_or_changed(e):
    return _error_code(e) in _GONE_OR_CHANGED


class s3(store):
    """AWS S3 backend.

    Each secret is stored as ``<bucket_path>/<id>.json``, with its create and
    expire dates mirrored into object tags so the cleaner can decide on expiry
    without downloading every object.

    Concurrency relies on S3 conditional requests: new secrets are written
    with ``IfNoneMatch="*"`` so an existing secret is never replaced, and
    updates write with ``IfMatch`` so a deleted secret is never recreated.
    Changes (wrong-password counts, one-time claims, wipes) are a
    compare-and-swap against the ETag of the copy that was read, retried if
    another write got in first. A claim replaces the secret with its wiped
    record, so exactly one caller wins: the losers find the wiped record.

    botocore retries transient errors; other errors propagate. The cleaner
    thread logs and survives errors raised from ``delete_expired``.
    """

    def __init__(self, name="s3", parent=None):
        self.default_config = {"bucket_name": None, "bucket_path": ""}
        super().__init__(name, parent)

    def start(self):
        self.client = boto3.client("s3")

    def _path(self, secret_id):
        # strip slashes like _list_prefix does, so "/secrets" stores secrets
        # where the cleaner looks for them. Object keys always use "/".
        return posixpath.join(self.config.bucket_path.strip("/"), f"{secret_id}.json")

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
        logger.debug(f"Reading S3 secret: {short_id(s.id)}")
        return self._read(s.id)[0]

    def _read(self, secret_id):
        """The stored secret and the ETag it was read with, or (False, None)
        if it is missing or unreadable."""
        try:
            response = self.client.get_object(
                Bucket=self.config.bucket_name, Key=self._path(secret_id)
            )
            raw = response["Body"].read()
        except ClientError as e:
            if _gone_or_changed(e):
                return False, None
            raise
        s = secret()
        try:
            if not s.load_from_dict(json.loads(raw)):
                return False, None
        except ValueError as e:
            logger.error(f"Could not parse S3 secret {short_id(secret_id)}: {e}")
            return False, None
        return (s, response.get("ETag")) if s.check_id() else (False, None)

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
        try:
            # create-only: never replace an existing secret
            self._upload(s, IfNoneMatch="*")
        except ClientError as e:
            if _error_code(e) in _WRITE_REFUSED:
                return False
            raise
        return True

    def update_secret(self, s):
        """Overwrite only if the object still exists, pinned to its current
        ETag so a concurrent delete makes this a no-op."""
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

    def modify_secret(self, secret_id, change):
        """Change a stored secret with a compare-and-swap: write change()'s
        result pinned to the ETag the secret was read with. If another write
        got in first, read again and retry, so simultaneous changes (wrong
        passwords counted at the same moment, a claim, a wipe) never undo one
        another. Raises StorageBusy after CAS_ATTEMPTS lost races."""
        if not secret(secret_id).check_id():
            return None, None
        for _ in range(CAS_ATTEMPTS):
            stored, etag = self._read(secret_id)
            if not stored or etag is None:
                return None, None
            changed = change(copy.copy(stored))
            if changed is None:
                return stored, None
            try:
                self._upload(changed, IfMatch=etag)
            except ClientError as e:
                if _error_code(e) in _WRITE_REFUSED:
                    continue  # changed since the read
                if _gone_or_changed(e):
                    return None, None  # deleted since the read
                raise
            return stored, changed
        logger.warning(f"Too many concurrent writes, change not made: {short_id(secret_id)}")
        raise StorageBusy()

    def delete_expired(self):
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.config.bucket_name, Prefix=self._list_prefix()
        )
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                secret_id, ext = posixpath.splitext(posixpath.basename(key))
                # only touch objects that are exactly <bucket_path>/<id>.json
                if ext != ".json" or key != self._path(secret_id):
                    continue
                s = secret(secret_id)
                if not s.check_id():
                    continue
                dates = self._dates_from_tags(key)
                if dates is _GONE:
                    # deleted since the listing: nothing to do
                    continue
                if dates is None:
                    # no usable tags: fall back to reading the dates from the
                    # object itself
                    stored = self.get_secret(secret_id)
                    if not stored:
                        logger.warning(f"Skipping unreadable S3 secret: {short_id(secret_id)}")
                        continue
                    dates = (stored.create_date, stored.expire_date)
                s.create_date, s.expire_date = dates
                if s.is_expired():
                    self.delete_secret(secret_id)

    def _dates_from_tags(self, path):
        """(create_date, expire_date) from the object's tags, None if they
        are missing or invalid, or _GONE if the object no longer exists."""
        try:
            tagset = self.client.get_object_tagging(
                Bucket=self.config.bucket_name, Key=path
            ).get("TagSet", [])
        except ClientError as e:
            if _gone_or_changed(e):
                return _GONE
            raise
        tags = {tag["Key"]: tag["Value"] for tag in tagset}
        try:
            return int(tags["create_date"]), int(tags["expire_date"])
        except (KeyError, ValueError):
            return None
