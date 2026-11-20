"""Unit tests for the GCS backend against a fake bucket (no network)."""

import json
import secrets
from unittest import mock

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from whisper import AttrDict, secret
from whisper.storage.gcp import gcs


@pytest.fixture
def backend():
    b = gcs()
    b.config = AttrDict({"bucket_name": "b", "bucket_path": "secrets", "gcp_project": "p"})
    b.client = mock.MagicMock()
    b.bucket = mock.MagicMock()
    return b


def _make_secret(expiration="1 hour"):
    s = secret()
    s.create(
        secret_id=secrets.token_hex(32), expiration=expiration, auth="a" * 64, key="k",
        data="ciphertext",
    )
    return s


def _listed_blob(name, metadata):
    blob = mock.MagicMock()
    blob.name = name
    blob.metadata = metadata
    return blob


def test_get_secret_roundtrip(backend):
    s = _make_secret()
    backend.bucket.blob.return_value.download_as_bytes.return_value = json.dumps(
        s.__dict__
    ).encode()
    assert backend.get_secret(s.id).__dict__ == s.__dict__
    backend.bucket.blob.assert_called_with(f"secrets/{s.id}.json")


def test_get_secret_missing(backend):
    backend.bucket.blob.return_value.download_as_bytes.side_effect = NotFound("gone")
    assert backend.get_secret("a" * 40) is False


def test_set_secret_sends_metadata_with_upload(backend):
    s = _make_secret()
    blob = backend.bucket.blob.return_value
    assert backend.set_secret(s) is True
    assert blob.metadata == {"create_date": str(s.create_date), "expire_date": str(s.expire_date)}
    blob.upload_from_string.assert_called_once()
    assert blob.upload_from_string.call_args.kwargs["if_generation_match"] == 0
    blob.patch.assert_not_called()


def test_set_secret_never_replaces_an_existing_secret(backend):
    backend.bucket.blob.return_value.upload_from_string.side_effect = PreconditionFailed("exists")
    assert backend.set_secret(_make_secret()) is False


def _meta(generation):
    """What get_blob() returns: the object's metadata at one generation."""
    blob = mock.MagicMock()
    blob.generation = generation
    return blob


def _content(s, **changes):
    return json.dumps(dict(s.__dict__, **changes)).encode()


def _add_one(stored):
    stored.failed_attempts += 1
    return stored


def test_modify_secret_is_a_compare_and_swap(backend):
    s = _make_secret()
    meta = backend.bucket.get_blob.return_value = _meta(4)
    fresh = backend.bucket.blob.return_value  # unpinned, by name
    fresh.download_as_bytes.return_value = _content(s, failed_attempts=2)
    stored, written = backend.modify_secret(s.id, _add_one)
    assert (stored.failed_attempts, written.failed_attempts) == (2, 3)
    fresh.download_as_bytes.assert_called_once_with(if_generation_match=4)
    meta.download_as_bytes.assert_not_called()  # would request generation 4 by number
    assert json.loads(fresh.upload_from_string.call_args.args[0])["failed_attempts"] == 3
    assert fresh.upload_from_string.call_args.kwargs["if_generation_match"] == 4


def test_modify_secret_retries_and_keeps_other_writes(backend):
    """Another write got in between (more wrong passwords and a wipe):
    change it on top of that instead of writing the stale copy back."""
    s = _make_secret()
    backend.bucket.get_blob.side_effect = [_meta(4), _meta(5), _meta(6)]
    fresh = backend.bucket.blob.return_value
    fresh.download_as_bytes.side_effect = [
        _content(s, failed_attempts=2),
        PreconditionFailed("replaced"),  # replaced again between lookup and download
        _content(s, failed_attempts=10, data="", hash=""),
    ]
    fresh.upload_from_string.side_effect = [PreconditionFailed("raced"), None]
    assert backend.modify_secret(s.id, _add_one)[1].failed_attempts == 11
    written = json.loads(fresh.upload_from_string.call_args.args[0])
    assert (written["failed_attempts"], written["data"], written["hash"]) == (11, "", "")
    assert fresh.upload_from_string.call_args.kwargs["if_generation_match"] == 6


def test_modify_secret_can_leave_it(backend):
    s = _make_secret()
    backend.bucket.get_blob.return_value = _meta(4)
    backend.bucket.blob.return_value.download_as_bytes.return_value = _content(s)
    stored, written = backend.modify_secret(s.id, lambda stored: None)
    assert (stored.data, written) == ("ciphertext", None)
    backend.bucket.blob.return_value.upload_from_string.assert_not_called()


def test_modify_secret_for_a_deleted_secret(backend):
    backend.bucket.get_blob.return_value = None
    assert backend.modify_secret(_make_secret().id, _add_one) == (None, None)
    backend.bucket.blob.return_value.upload_from_string.assert_not_called()


def test_modify_secret_gives_up_after_repeated_conflicts(backend, caplog):
    from whisper.storage import CAS_ATTEMPTS, StorageBusy

    s = _make_secret()
    backend.bucket.get_blob.return_value = _meta(4)
    backend.bucket.blob.return_value.download_as_bytes.return_value = _content(s)
    upload = backend.bucket.blob.return_value.upload_from_string
    upload.side_effect = PreconditionFailed("raced")
    with caplog.at_level("WARNING"), pytest.raises(StorageBusy):
        backend.modify_secret(s.id, _add_one)
    assert upload.call_count == CAS_ATTEMPTS
    assert "Too many concurrent writes" in caplog.text


def test_modify_secret_rejects_an_invalid_id(backend):
    assert backend.modify_secret("../other", _add_one) == (None, None)
    backend.bucket.get_blob.assert_not_called()


def test_a_one_time_claim_overwrites_instead_of_deleting(backend):
    from whisper.storage import store

    st = store("whisper.storage.gcp.gcs")
    st.backend = backend
    s = _make_secret("One time use")
    backend.bucket.get_blob.return_value = _meta(4)
    fresh = backend.bucket.blob.return_value
    fresh.download_as_bytes.return_value = _content(s)
    assert st.open_secret(s).data == "ciphertext"
    written = json.loads(fresh.upload_from_string.call_args.args[0])
    assert (written["data"], written["hash"]) == ("", "")
    assert fresh.upload_from_string.call_args.kwargs["if_generation_match"] == 4
    backend.bucket.delete_blob.assert_not_called()


def test_update_secret_does_not_recreate_deleted_secret(backend):
    backend.bucket.get_blob.return_value = None
    assert backend.update_secret(_make_secret()) is False
    backend.bucket.blob.return_value.upload_from_string.assert_not_called()


def test_update_secret_is_generation_conditioned(backend):
    backend.bucket.get_blob.return_value.generation = 3
    s = _make_secret()
    assert backend.update_secret(s) is True
    kwargs = backend.bucket.blob.return_value.upload_from_string.call_args.kwargs
    assert kwargs["if_generation_match"] == 3


def test_delete_expired_uses_metadata_and_skips_foreign_objects(backend):
    live, dead = "a" * 40, "b" * 40
    backend.client.list_blobs.return_value = [
        _listed_blob(f"secrets/{live}.json", {"create_date": "1", "expire_date": "9999999999"}),
        _listed_blob(f"secrets/{dead}.json", {"create_date": "1", "expire_date": "2"}),
        _listed_blob(f"secrets/nested/{dead}.json", {"create_date": "1", "expire_date": "2"}),
        _listed_blob("secrets/notes.txt", None),
    ]
    backend.delete_expired()
    backend.bucket.delete_blob.assert_called_once_with(f"secrets/{dead}.json")
    assert backend.client.list_blobs.call_args.kwargs["prefix"] == "secrets/"


def test_delete_expired_falls_back_to_object_without_metadata(backend):
    s = _make_secret()
    s.create_date -= 7200
    s.expire_date -= 7200
    backend.client.list_blobs.return_value = [_listed_blob(f"secrets/{s.id}.json", None)]
    backend.bucket.blob.return_value.download_as_bytes.return_value = json.dumps(
        s.__dict__
    ).encode()
    backend.delete_expired()
    backend.bucket.delete_blob.assert_called_once_with(f"secrets/{s.id}.json")


@pytest.mark.parametrize("bucket_path", ["secrets", "/secrets", "/secrets/", "secrets/"])
def test_secrets_are_stored_where_the_cleaner_looks(backend, bucket_path):
    backend.config.bucket_path = bucket_path
    assert backend._path(SID_FOR_PATHS) == f"secrets/{SID_FOR_PATHS}.json"
    assert backend._path(SID_FOR_PATHS).startswith(backend._list_prefix())


SID_FOR_PATHS = "c" * 64
