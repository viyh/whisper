"""Unit tests for the in-memory storage backend.

The memory backend is the reference implementation; the S3/GCS/local
backends implement the same contract. These tests lock down the contract
itself."""

import secrets
import time

import pytest

from whisper import secret
from whisper.storage.memory import memory


@pytest.fixture
def backend():
    b = memory()
    b.start()
    return b


def _make_secret(expiration="1 hour"):
    s = secret()
    s.create(
        secret_id=secrets.token_hex(32), expiration=expiration, auth="a" * 64, key="k",
        data="ciphertext",
    )
    return s


def test_set_then_get_roundtrip(backend):
    s = _make_secret()
    assert backend.set_secret(s) is True
    retrieved = backend.get_secret(s.id)
    assert retrieved is not s  # backend returns a copy, not live state
    assert retrieved.__dict__ == s.__dict__
    assert retrieved.data == "ciphertext"


def test_get_missing_secret_returns_false(backend):
    assert backend.get_secret("a" * 40) is False


def test_set_secret_rejects_invalid_id(backend):
    s = secret()
    s.id = "too-short"
    assert backend.set_secret(s) is False


def test_set_secret_never_replaces_an_existing_secret(backend):
    s = _make_secret()
    assert backend.set_secret(s) is True
    other = _make_secret()
    other.id, other.data = s.id, "attacker-data"
    assert backend.set_secret(other) is False
    assert backend.get_secret(s.id).data == "ciphertext"


def test_delete_secret(backend):
    s = _make_secret()
    backend.set_secret(s)
    assert backend.delete_secret(s.id) is True
    assert backend.get_secret(s.id) is False


def _add_one(stored):
    stored.failed_attempts += 1
    return stored


def test_modify_secret_writes_the_change(backend):
    s = _make_secret()
    backend.set_secret(s)
    stored, written = backend.modify_secret(s.id, _add_one)
    assert (stored.failed_attempts, written.failed_attempts) == (0, 1)
    assert backend.get_secret(s.id).failed_attempts == 1
    written.failed_attempts = 5  # the caller's copy, not stored state
    assert backend.get_secret(s.id).failed_attempts == 1


def test_modify_secret_can_leave_it(backend):
    s = _make_secret()
    backend.set_secret(s)
    stored, written = backend.modify_secret(s.id, lambda stored: None)
    assert (stored.__dict__, written) == (s.__dict__, None)


def test_modify_missing_secret(backend):
    assert backend.modify_secret("b" * 64, _add_one) == (None, None)
    assert backend.get_secret("b" * 64) is False  # not created


def test_delete_expired_removes_expired_entries(backend):
    fresh = _make_secret("1 hour")
    stale = _make_secret("1 hour")
    stale.expire_date = int(time.time()) - 10  # forcibly expired
    backend.set_secret(fresh)
    backend.set_secret(stale)

    backend.delete_expired()

    assert backend.get_secret(fresh.id).id == fresh.id
    assert backend.get_secret(stale.id) is False


def test_delete_expired_leaves_one_time_within_grace_window(backend):
    """Unclaimed one-time secrets should survive the cleaner sweep until
    they pass the 30-day grace window."""
    ot = _make_secret("One time use")
    backend.set_secret(ot)
    backend.delete_expired()
    assert backend.get_secret(ot.id).id == ot.id

    ot.create_date = int(time.time()) - 86400 * 31
    backend.update_secret(ot)  # backend stores copies, so persist the change
    backend.delete_expired()
    assert backend.get_secret(ot.id) is False


def test_failed_attempts_count_atomically(backend):
    import threading

    s = _make_secret()
    backend.set_secret(s)
    start = threading.Barrier(20)

    def wrong_password():
        start.wait()
        assert backend.modify_secret(s.id, _add_one)[1]

    threads = [threading.Thread(target=wrong_password) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert backend.get_secret(s.id).failed_attempts == 20
