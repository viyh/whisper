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


def test_claim_secret_generation_match(backend):
    blob = backend.bucket.get_blob.return_value
    blob.generation = 7
    assert backend.claim_secret("a" * 40) is True
    blob.delete.assert_called_once_with(if_generation_match=7)


def test_claim_secret_lost_race(backend):
    backend.bucket.get_blob.return_value.delete.side_effect = PreconditionFailed("raced")
    assert backend.claim_secret("a" * 40) is False


def test_claim_secret_missing(backend):
    backend.bucket.get_blob.return_value = None
    assert backend.claim_secret("a" * 40) is False


def test_update_secret_does_not_recreate_claimed_secret(backend):
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
