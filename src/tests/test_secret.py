"""Unit tests for the ``secret`` class and the v3 ID/auth helpers."""

import hashlib
import hmac
import time

import pytest

from whisper import (
    CURRENT_SECRET_VERSION,
    auth_digest,
    is_auth_token,
    is_legacy_secret_id,
    is_secret_id,
    secret,
)

SID = "0123456789abcdef" * 4
AUTH = "fedcba9876543210" * 4
KEY = "server-secret-key"


def _make(expiration="1 hour", auth=AUTH, key=KEY):
    s = secret()
    s.create(secret_id=SID, expiration=expiration, auth=auth, key=key, data="ciphertext")
    return s


def test_create_sets_fields():
    s = _make()
    assert s.id == SID
    assert s.version == CURRENT_SECRET_VERSION == 3
    assert s.data == "ciphertext"
    assert s.failed_attempts == 0
    assert s.check_id() is True


def test_stored_hash_is_hmac_of_auth_not_the_auth_itself():
    s = _make()
    assert s.hash != AUTH
    assert s.hash == hmac.new(KEY.encode(), AUTH.encode(), hashlib.sha256).hexdigest()
    assert s.hash == auth_digest(AUTH, KEY)


def test_check_auth():
    s = _make()
    assert s.check_auth(AUTH, KEY) is True
    assert s.check_auth("0" * 64, KEY) is False  # wrong token
    assert s.check_auth(AUTH, "other-key") is False  # wrong server key
    for bad in (None, 123, "", AUTH.upper(), AUTH[:-1], AUTH + "0"):
        assert s.check_auth(bad, KEY) is False


def test_check_auth_without_hash():
    assert secret(SID).check_auth(AUTH, KEY) is False


def test_id_and_auth_formats():
    assert is_secret_id(SID) and is_auth_token(AUTH)
    for bad in (None, 5, "", "g" * 64, SID.upper(), SID[:-1], SID + "0", "a" * 40):
        assert not is_secret_id(bad)
        assert not is_auth_token(bad)
    # v2 IDs (40 hex) are only recognized as leftovers, for cleanup
    assert is_legacy_secret_id("a" * 40)
    assert not is_legacy_secret_id(SID)


def test_check_id_accepts_v3_and_leftover_v2_ids():
    assert secret(SID).check_id() is True
    assert secret("a" * 40).check_id() is True
    for bad in (None, "too-short", "g" * 64, "!" * 40, SID.upper()):
        assert secret(bad).check_id() is False


def test_is_one_time_truth_table():
    assert _make(expiration="One time use").is_one_time() is True
    assert _make(expiration="1 hour").is_one_time() is False
    assert _make(expiration="1 day").is_one_time() is False
    assert _make(expiration="1 week").is_one_time() is False


def test_expiration_periods():
    now = int(time.time())
    assert abs(_make(expiration="1 hour").expire_date - (now + 3600)) <= 2
    assert abs(_make(expiration="1 day").expire_date - (now + 86400)) <= 2
    assert abs(_make(expiration="1 week").expire_date - (now + 86400 * 7)) <= 2
    assert _make(expiration="One time use").expire_date == -1


def test_is_expired_fresh_secret_not_expired():
    assert _make("1 hour").is_expired() is False
    assert _make("One time use").is_expired() is False


def test_is_expired_past_expire_date():
    s = _make("1 hour")
    s.expire_date = int(time.time()) - 1
    assert s.is_expired() is True


def test_is_expired_one_time_grace_window():
    """Unclaimed one-time secrets live for 30 days before the cleaner drops
    them. Before 30 days they are not considered expired; after, they are."""
    s = _make("One time use")
    s.create_date = int(time.time()) - 86400 * 10
    assert s.is_expired() is False
    s.create_date = int(time.time()) - 86400 * 31
    assert s.is_expired() is True


def test_load_from_dict_requires_all_fields():
    incomplete = {"id": SID, "create_date": 1, "expire_date": 1, "data": "x"}  # no "hash"
    assert secret().load_from_dict(incomplete) is False


def test_load_from_dict_rejects_unknown_fields():
    poisoned = {"id": SID, "create_date": 1, "expire_date": 1, "data": "x", "hash": "y", "evil": True}
    assert secret().load_from_dict(poisoned) is False


def test_load_from_dict_accepts_valid_shape():
    s = secret()
    valid = {
        "id": SID,
        "create_date": 1,
        "expire_date": 1,
        "data": "x",
        "hash": "y",
        "version": 3,
        "failed_attempts": 0,
    }
    assert s.load_from_dict(valid) is True
    assert s.id == SID
    assert s.version == 3


def test_load_from_dict_accepts_leftover_v2_records():
    """So the cleaner can read their dates and delete them when they expire."""
    s = secret()
    v2 = {"id": "a" * 40, "create_date": 1, "expire_date": 2, "data": "x",
          "hash": "$argon2id$v=19$m=131072,t=5,p=1$...", "version": 2, "failed_attempts": 0}
    assert s.load_from_dict(v2) is True
    assert s.check_id() is True
    assert s.is_expired()
    assert s.check_auth(AUTH, KEY) is False


@pytest.mark.parametrize("damaged", [None, [], 123, "text"])
def test_load_from_dict_rejects_json_that_is_not_an_object(damaged):
    assert secret().load_from_dict(damaged) is False


@pytest.mark.parametrize(
    "expiration,dates",
    [("1 hour", {"expire_date": None}), ("1 hour", {"expire_date": 0}),
     ("1 hour", {"expire_date": "soon"}), ("One time use", {"create_date": None})],
)
def test_is_expired_treats_damaged_dates_as_expired(expiration, dates):
    """A damaged record is never served, and the cleaner removes it."""
    s = _make(expiration)
    for name, value in dates.items():
        setattr(s, name, value)
    assert s.is_expired() is True
