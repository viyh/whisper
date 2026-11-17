import json
import logging
import os

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

from whisper import secret
from whisper.storage import store

logger = logging.getLogger(__name__)


class gcs(store):
    """Google Cloud Storage backend.

    Each secret is stored as ``<bucket_path>/<id>.json``, with its create and
    expire dates mirrored into custom object metadata so the cleaner can decide
    on expiry from a bucket listing without downloading every object.

    Concurrency relies on GCS object generations: a one-time claim deletes with
    ``if_generation_match`` so exactly one caller wins, and updates write with
    ``if_generation_match`` so a claimed secret is never recreated.

    The client library retries reads, deletes and generation-conditioned writes
    on transient errors; other errors propagate. The cleaner thread logs and
    survives errors raised from ``delete_expired``.
    """

    def __init__(self, name="gcp", parent=None):
        self.default_config = {
            "bucket_name": None,
            "bucket_path": "",
            "gcp_project": None,
        }
        super().__init__(name, parent)

    def start(self):
        self.client = storage.Client(project=self.config.gcp_project)
        # get_bucket makes an API call, so a missing bucket or bad
        # credentials fail at startup rather than on the first request
        self.bucket = self.client.get_bucket(self.config.bucket_name)

    def _path(self, secret_id):
        return os.path.join(self.config.bucket_path, f"{secret_id}.json")

    def _list_prefix(self):
        path = self.config.bucket_path.strip("/")
        return f"{path}/" if path else None

    def get_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return False
        path = self._path(s.id)
        logger.debug(f"Reading GCS secret: {path}")
        try:
            raw = self.bucket.blob(path).download_as_bytes()
        except NotFound:
            return False
        s = secret()
        try:
            if not s.load_from_dict(json.loads(raw)):
                return False
        except ValueError as e:
            logger.error(f"Could not parse GCS object {path}: {e}")
            return False
        return s if s.check_id() else False

    def _upload(self, s, **conditions):
        blob = self.bucket.blob(self._path(s.id))
        # metadata set before upload is sent with the object in one request
        blob.metadata = {
            "create_date": str(s.create_date),
            "expire_date": str(s.expire_date),
        }
        blob.upload_from_string(
            json.dumps(s.__dict__),
            content_type="application/json",
            **conditions,
        )

    def set_secret(self, s):
        if not s.check_id():
            return False
        logger.debug(f"Saving GCS secret: {s.id}")
        self._upload(s)
        return True

    def update_secret(self, s):
        """Overwrite only if the object still exists, pinned to its current
        generation so a concurrent claim/delete makes this a no-op."""
        if not s.check_id():
            return False
        blob = self.bucket.get_blob(self._path(s.id))
        if blob is None:
            return False
        try:
            self._upload(s, if_generation_match=blob.generation)
        except (NotFound, PreconditionFailed):
            return False
        logger.debug(f"Updated GCS secret: {s.id}")
        return True

    def delete_secret(self, secret_id):
        logger.info(f"Deleting GCS secret: {secret_id}")
        try:
            self.bucket.delete_blob(self._path(secret_id))
        except NotFound:
            pass
        return True

    def claim_secret(self, secret_id):
        """Atomically claim a one-time secret by deleting with generation match."""
        blob = self.bucket.get_blob(self._path(secret_id))
        if blob is None:
            return False
        try:
            blob.delete(if_generation_match=blob.generation)
        except (NotFound, PreconditionFailed):
            return False
        return True

    def delete_expired(self):
        for blob in self.client.list_blobs(self.bucket, prefix=self._list_prefix()):
            secret_id, ext = os.path.splitext(os.path.basename(blob.name))
            # only touch objects that are exactly <bucket_path>/<id>.json
            if ext != ".json" or blob.name != self._path(secret_id):
                continue
            s = secret(secret_id)
            if not s.check_id():
                continue
            dates = self._dates_from_metadata(blob)
            if dates is None:
                # no usable metadata (e.g. written by an older version):
                # fall back to reading the dates from the object itself
                stored = self.get_secret(secret_id)
                if not stored:
                    logger.warning(f"Skipping unreadable GCS object: {blob.name}")
                    continue
                dates = (stored.create_date, stored.expire_date)
            s.create_date, s.expire_date = dates
            if s.is_expired():
                self.delete_secret(secret_id)

    @staticmethod
    def _dates_from_metadata(blob):
        metadata = blob.metadata or {}
        try:
            return int(metadata["create_date"]), int(metadata["expire_date"])
        except (KeyError, TypeError, ValueError):
            return None
