"""Unit tests for the ``secret`` class."""

import time

import pytest

import whisper
from whisper import CURRENT_SECRET_VERSION, create_argon2_hasher, secret


@pytest.fixture(autouse=True)
def _fast_argon2(monkeypatch):
    """Use the cheapest Argon2id parameters for unit tests so this file runs
    in well under a second."""
    fast = create_argon2_hasher(time_cost=1, memory_cost=8, parallelism=1)
    monkeypatch.setattr(whisper, "_argon2_hasher", fast)


def _make(expiration="1 hour", password=b"hunter2"):
    s = secret()
    s.create(expiration=expiration, key_pass=password, data="ciphertext")
    return s


def test_create_sets_version_and_id():
    s = _make()
    assert s.version == CURRENT_SECRET_VERSION
    assert s.check_id() is True
    assert len(s.id) == 40
    assert s.id.isalnum()


def test_new_id_is_stable_once_set():
    s = _make()
    first_id = s.id
    assert s.new_id() is False
    assert s.id == first_id


def test_check_id_rejects_non_alnum_and_wrong_length():
    s = secret()
    s.id = "not-40-chars"
    assert s.check_id() is False
    s.id = "g" * 40
    assert s.check_id() is True
    s.id = "!" * 40
    assert s.check_id() is False


def test_set_and_check_password_roundtrip():
    s = _make(password=b"correct horse battery staple")
    assert s.check_password(b"correct horse battery staple") is True
    assert s.check_password(b"wrong password") is False


def test_check_password_without_hash():
    s = secret()
    assert s.check_password(b"anything") is False


def test_is_one_time_truth_table():
    assert _make(expiration="One time use").is_one_time() is True
    assert _make(expiration="1 hour").is_one_time() is False
    assert _make(expiration="1 day").is_one_time() is False
    assert _make(expiration="1 week").is_one_time() is False


def test_expiration_periods():
    now = int(time.time())

    s1h = _make(expiration="1 hour")
    assert abs(s1h.expire_date - (now + 3600)) <= 2

    s1d = _make(expiration="1 day")
    assert abs(s1d.expire_date - (now + 86400)) <= 2

    s1w = _make(expiration="1 week")
    assert abs(s1w.expire_date - (now + 86400 * 7)) <= 2

    sot = _make(expiration="One time use")
    assert sot.expire_date == -1


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
    # 10 days old — still within the grace window, not expired.
    s.create_date = int(time.time()) - 86400 * 10
    assert s.is_expired() is False
    # 31 days old — past the grace window, should expire.
    s.create_date = int(time.time()) - 86400 * 31
    assert s.is_expired() is True


def test_get_key_pass_combines_key_and_password():
    s = secret()
    combined = s.get_key_pass("password", "server_key")
    assert combined == b"server_key" + b"password"


def test_load_from_dict_requires_all_fields():
    s = secret()
    incomplete = {
        "id": "a" * 40,
        "create_date": 1,
        "expire_date": 1,
        "data": "x",
        # missing "hash"
    }
    assert s.load_from_dict(incomplete) is False


def test_load_from_dict_rejects_unknown_fields():
    s = secret()
    poisoned = {
        "id": "a" * 40,
        "create_date": 1,
        "expire_date": 1,
        "data": "x",
        "hash": "y",
        "evil": True,
    }
    assert s.load_from_dict(poisoned) is False


def test_load_from_dict_accepts_valid_shape():
    s = secret()
    valid = {
        "id": "a" * 40,
        "create_date": 1,
        "expire_date": 1,
        "data": "x",
        "hash": "y",
        "version": 2,
        "failed_attempts": 0,
    }
    assert s.load_from_dict(valid) is True
    assert s.id == "a" * 40
    assert s.version == 2
