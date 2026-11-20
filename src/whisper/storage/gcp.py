import copy
import json
import logging
import posixpath

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

from whisper import secret, short_id
from whisper.storage import CAS_ATTEMPTS, StorageBusy, store

logger = logging.getLogger(__name__)


class gcs(store):
    """Google Cloud Storage backend.

    Each secret is stored as ``<bucket_path>/<id>.json``, with its create and
    expire dates mirrored into custom object metadata so the cleaner can decide
    on expiry from a bucket listing without downloading every object.

    Concurrency relies on GCS object generations: new secrets are written with
    ``if_generation_match=0`` so an existing secret is never replaced, and
    updates write with ``if_generation_match`` so a deleted secret is never
    recreated. Changes (wrong-password counts, one-time claims, wipes) are a
    compare-and-swap against the generation of the copy that was read,
    retried if another write got in first. A claim replaces the secret with
    its wiped record, so exactly one caller wins: the losers find the wiped
    record.

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
        # strip slashes like _list_prefix does, so "/secrets" stores secrets
        # where the cleaner looks for them. Object keys always use "/".
        return posixpath.join(self.config.bucket_path.strip("/"), f"{secret_id}.json")

    def _list_prefix(self):
        path = self.config.bucket_path.strip("/")
        return f"{path}/" if path else None

    def get_secret(self, secret_id):
        s = secret(secret_id)
        if not s.check_id():
            return False
        path = self._path(s.id)
        logger.debug(f"Reading GCS secret: {short_id(s.id)}")
        try:
            raw = self.bucket.blob(path).download_as_bytes()
        except NotFound:
            return False
        return self._parse(raw, s.id)

    @staticmethod
    def _parse(raw, secret_id):
        s = secret()
        try:
            if not s.load_from_dict(json.loads(raw)):
                return False
        except ValueError as e:
            logger.error(f"Could not parse GCS secret {short_id(secret_id)}: {e}")
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
        logger.debug(f"Saving GCS secret: {short_id(s.id)}")
        try:
            # generation 0 = "no live object": never replace an existing secret
            self._upload(s, if_generation_match=0)
        except PreconditionFailed:
            return False
        return True

    def update_secret(self, s):
        """Overwrite only if the object still exists, pinned to its current
        generation so a concurrent delete makes this a no-op."""
        if not s.check_id():
            return False
        blob = self.bucket.get_blob(self._path(s.id))
        if blob is None:
            return False
        try:
            self._upload(s, if_generation_match=blob.generation)
        except (NotFound, PreconditionFailed):
            return False
        logger.debug(f"Updated GCS secret: {short_id(s.id)}")
        return True

    def delete_secret(self, secret_id):
        logger.info(f"Deleting GCS secret: {short_id(secret_id)}")
        try:
            self.bucket.delete_blob(self._path(secret_id))
        except NotFound:
            pass
        return True

    def modify_secret(self, secret_id, change):
        """Change a stored secret with a compare-and-swap: write change()'s
        result pinned to the generation the secret was read at. If another
        write got in first, read again and retry, so simultaneous changes
        (wrong passwords counted at the same moment, a claim, a wipe) never
        undo one another. Raises StorageBusy after CAS_ATTEMPTS lost races."""
        if not secret(secret_id).check_id():
            return None, None
        path = self._path(secret_id)
        for _ in range(CAS_ATTEMPTS):
            blob = self.bucket.get_blob(path)
            if blob is None:
                return None, None
            generation = blob.generation
            try:
                # The content of exactly the generation looked up. A fresh,
                # unpinned blob: one from get_blob() requests that generation
                # by number, which a non-versioned bucket answers with 404
                # once it was overwritten, instead of a precondition failure.
                raw = self.bucket.blob(path).download_as_bytes(if_generation_match=generation)
            except NotFound:
                return None, None
            except PreconditionFailed:
                continue  # replaced between the two calls
            stored = self._parse(raw, secret_id)
            if not stored:
                return None, None
            changed = change(copy.copy(stored))
            if changed is None:
                return stored, None
            try:
                self._upload(changed, if_generation_match=generation)
            except NotFound:
                return None, None
            except PreconditionFailed:
                continue  # changed (or deleted) since the read: look again
            return stored, changed
        logger.warning(f"Too many concurrent writes, change not made: {short_id(secret_id)}")
        raise StorageBusy()

    def delete_expired(self):
        for blob in self.client.list_blobs(self.bucket, prefix=self._list_prefix()):
            secret_id, ext = posixpath.splitext(posixpath.basename(blob.name))
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
                    logger.warning(f"Skipping unreadable GCS secret: {short_id(secret_id)}")
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
