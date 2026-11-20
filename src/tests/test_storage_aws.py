"""Unit tests for the S3 backend, using botocore's Stubber (no network)."""

import secrets

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber

from whisper import AttrDict, secret
from whisper.storage.aws import s3

BUCKET = "test-bucket"
SID = "a" * 64
KEY = f"secrets/{SID}.json"


def _make_secret(expiration="1 hour"):
    s = secret()
    s.create(
        secret_id=secrets.token_hex(32), expiration=expiration, auth="a" * 64, key="k",
        data="ciphertext",
    )
    return s


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    b = s3()
    b.config = AttrDict({"bucket_name": BUCKET, "bucket_path": "secrets"})
    b.client = boto3.client("s3", region_name="us-east-1")
    with Stubber(b.client) as stub:
        b.stub = stub
        yield b
        stub.assert_no_pending_responses()


def test_set_secret_is_create_only(backend):
    s = _make_secret()
    backend.stub.add_response(
        "put_object",
        {},
        {"Bucket": BUCKET, "Key": f"secrets/{s.id}.json", "Body": ANY,
         "ContentType": "application/json", "Tagging": ANY, "IfNoneMatch": "*"},
    )
    assert backend.set_secret(s) is True


@pytest.mark.parametrize("code,status", [("PreconditionFailed", 412), ("ConditionalRequestConflict", 409)])
def test_set_secret_never_replaces_an_existing_secret(backend, code, status):
    backend.stub.add_client_error("put_object", service_error_code=code, http_status_code=status)
    assert backend.set_secret(_make_secret()) is False


def test_set_secret_propagates_unexpected_errors(backend):
    backend.stub.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(ClientError):
        backend.set_secret(_make_secret())


def test_update_secret_skips_missing_object(backend):
    s = secret(SID)
    s.create_date, s.expire_date = 1, -1
    backend.stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
    assert backend.update_secret(s) is False


def test_update_secret_is_conditional(backend):
    s = _make_secret()
    key = f"secrets/{s.id}.json"
    backend.stub.add_response("head_object", {"ETag": '"v1"'}, {"Bucket": BUCKET, "Key": key})
    backend.stub.add_client_error(
        "put_object", service_error_code="PreconditionFailed", http_status_code=412
    )
    assert backend.update_secret(s) is False


def test_get_secret_roundtrip(backend):
    import io
    import json

    from botocore.response import StreamingBody

    s = _make_secret()
    body = json.dumps(s.__dict__).encode()
    backend.stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(body), len(body))},
        {"Bucket": BUCKET, "Key": f"secrets/{s.id}.json"},
    )
    assert backend.get_secret(s.id).__dict__ == s.__dict__


def test_get_secret_missing(backend):
    backend.stub.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    assert backend.get_secret(SID) is False


def test_delete_expired_paginates_and_skips_foreign_objects(backend):
    live, dead = "c" * 40, "d" * 40
    backend.stub.add_response(
        "list_objects_v2",
        {"IsTruncated": True, "NextContinuationToken": "t",
         "Contents": [{"Key": f"secrets/{live}.json"}, {"Key": "secrets/readme.txt"}]},
        {"Bucket": BUCKET, "Prefix": "secrets/"},
    )
    backend.stub.add_response(
        "get_object_tagging",
        {"TagSet": [{"Key": "create_date", "Value": "1"}, {"Key": "expire_date", "Value": "9999999999"}]},
        {"Bucket": BUCKET, "Key": f"secrets/{live}.json"},
    )
    backend.stub.add_response(
        "list_objects_v2",
        {"IsTruncated": False,
         "Contents": [{"Key": f"secrets/nested/{dead}.json"}, {"Key": f"secrets/{dead}.json"}]},
        {"Bucket": BUCKET, "Prefix": "secrets/", "ContinuationToken": "t"},
    )
    backend.stub.add_response(
        "get_object_tagging",
        {"TagSet": [{"Key": "create_date", "Value": "1"}, {"Key": "expire_date", "Value": "2"}]},
        {"Bucket": BUCKET, "Key": f"secrets/{dead}.json"},
    )
    backend.stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": f"secrets/{dead}.json"})
    backend.delete_expired()


def test_delete_expired_falls_back_to_object_without_tags(backend):
    import io
    import json

    from botocore.response import StreamingBody

    s = _make_secret()
    s.create_date -= 7200
    s.expire_date -= 7200
    key = f"secrets/{s.id}.json"
    body = json.dumps(s.__dict__).encode()
    backend.stub.add_response("list_objects_v2", {"IsTruncated": False, "Contents": [{"Key": key}]})
    backend.stub.add_response("get_object_tagging", {"TagSet": []}, {"Bucket": BUCKET, "Key": key})
    backend.stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(body), len(body))})
    backend.stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": key})
    backend.delete_expired()


@pytest.mark.parametrize("bucket_path", ["secrets", "/secrets", "/secrets/", "secrets/"])
def test_secrets_are_stored_where_the_cleaner_looks(backend, bucket_path):
    backend.config.bucket_path = bucket_path
    assert backend._path(SID) == KEY
    assert backend._path(SID).startswith(backend._list_prefix())


def test_delete_expired_skips_a_secret_deleted_since_the_listing(backend, caplog):
    """No "unreadable" warning, and no further calls for it."""
    key = f"secrets/{SID}.json"
    backend.stub.add_response("list_objects_v2", {"IsTruncated": False, "Contents": [{"Key": key}]})
    backend.stub.add_client_error("get_object_tagging", service_error_code="NoSuchKey", http_status_code=404)
    with caplog.at_level("WARNING"):
        backend.delete_expired()
    assert not caplog.records


def _body(s, **changes):
    import json

    return json.dumps(dict(s.__dict__, **changes)).encode()


def _stored(s, etag, **changes):
    import io

    from botocore.response import StreamingBody

    body = _body(s, **changes)
    return {"Body": StreamingBody(io.BytesIO(body), len(body)), "ETag": etag}


def _put_params(s, etag, **changes):
    return {"Bucket": BUCKET, "Key": f"secrets/{s.id}.json", "Body": _body(s, **changes),
            "ContentType": "application/json", "Tagging": ANY, "IfMatch": etag}


def _add_one(stored):
    stored.failed_attempts += 1
    return stored


def test_modify_secret_is_a_compare_and_swap(backend):
    s = _make_secret()
    backend.stub.add_response("get_object", _stored(s, '"v1"', failed_attempts=2))
    backend.stub.add_response("put_object", {}, _put_params(s, '"v1"', failed_attempts=3))
    stored, written = backend.modify_secret(s.id, _add_one)
    assert (stored.failed_attempts, written.failed_attempts) == (2, 3)


def test_modify_secret_retries_and_keeps_other_writes(backend):
    """Another write got in between (more wrong passwords and a wipe):
    change it on top of that instead of writing the stale copy back."""
    s = _make_secret()
    backend.stub.add_response("get_object", _stored(s, '"v1"', failed_attempts=2))
    backend.stub.add_client_error("put_object", service_error_code="PreconditionFailed", http_status_code=412)
    backend.stub.add_response("get_object", _stored(s, '"v2"', failed_attempts=10, data="", hash=""))
    backend.stub.add_response(
        "put_object", {}, _put_params(s, '"v2"', failed_attempts=11, data="", hash="")
    )
    assert backend.modify_secret(s.id, _add_one)[1].failed_attempts == 11


def test_modify_secret_can_leave_it(backend):
    s = _make_secret()
    backend.stub.add_response("get_object", _stored(s, '"v1"'))
    stored, written = backend.modify_secret(s.id, lambda stored: None)  # no put
    assert (stored.data, written) == ("ciphertext", None)


@pytest.mark.parametrize("gone_at", ["get_object", "put_object"])
def test_modify_secret_for_a_deleted_secret(backend, gone_at):
    s = _make_secret()
    if gone_at == "put_object":
        backend.stub.add_response("get_object", _stored(s, '"v1"'))
    backend.stub.add_client_error(gone_at, service_error_code="NoSuchKey", http_status_code=404)
    assert backend.modify_secret(s.id, _add_one) == (None, None)


def test_modify_secret_gives_up_after_repeated_conflicts(backend, caplog):
    from whisper.storage import CAS_ATTEMPTS, StorageBusy

    s = _make_secret()
    for n in range(CAS_ATTEMPTS):
        backend.stub.add_response("get_object", _stored(s, f'"v{n}"'))
        backend.stub.add_client_error("put_object", service_error_code="PreconditionFailed", http_status_code=412)
    with caplog.at_level("WARNING"), pytest.raises(StorageBusy):
        backend.modify_secret(s.id, _add_one)
    assert "Too many concurrent writes" in caplog.text


def test_modify_secret_rejects_an_invalid_id(backend):
    assert backend.modify_secret("../other", _add_one) == (None, None)  # no S3 call stubbed


def _store(backend):
    from whisper.storage import store

    st = store("whisper.storage.aws.s3")
    st.backend = backend
    return st


def test_a_one_time_claim_overwrites_instead_of_deleting(backend):
    """Losers find the wiped record, so the claim doesn't depend on how a
    conditional delete of a deleted object is answered."""
    s = _make_secret("One time use")
    backend.stub.add_response("get_object", _stored(s, '"v1"'))
    backend.stub.add_response("put_object", {}, _put_params(s, '"v1"', data="", hash=""))
    assert _store(backend).open_secret(s).data == "ciphertext"


def test_a_one_time_claim_loses_to_another_claim(backend):
    s = _make_secret("One time use")
    backend.stub.add_response("get_object", _stored(s, '"v1"'))
    backend.stub.add_client_error("put_object", service_error_code="PreconditionFailed", http_status_code=412)
    backend.stub.add_response("get_object", _stored(s, '"v2"', data="", hash=""))
    assert _store(backend).open_secret(s) is False  # and no second put
