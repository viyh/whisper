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


def test_claim_secret_is_atomic(backend):
    """claim_secret is the one-shot retrieval primitive. The first caller
    must win, and every subsequent caller must lose."""
    s = _make_secret(expiration="One time use")
    backend.set_secret(s)

    assert backend.claim_secret(s.id) is True
    # Second attempt - the secret is gone.
    assert backend.claim_secret(s.id) is False
    # And a regular get should also fail.
    assert backend.get_secret(s.id) is False


def test_claim_nonexistent_secret_returns_false(backend):
    assert backend.claim_secret("b" * 40) is False


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
        assert backend.increment_failed_attempts(backend.get_secret(s.id)) is True

    threads = [threading.Thread(target=wrong_password) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert backend.get_secret(s.id).failed_attempts == 20
    assert backend.increment_failed_attempts(_make_secret()) is False  # not stored
