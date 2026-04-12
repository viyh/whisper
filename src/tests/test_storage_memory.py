"""Unit tests for the in-memory storage backend.

The memory backend is the reference implementation; the S3/GCS/local
backends implement the same contract. These tests lock down the contract
itself."""

import time

import pytest

import whisper
from whisper import create_argon2_hasher, secret
from whisper.storage.memory import memory


@pytest.fixture(autouse=True)
def _fast_argon2(monkeypatch):
    fast = create_argon2_hasher(time_cost=1, memory_cost=8, parallelism=1)
    monkeypatch.setattr(whisper, "_argon2_hasher", fast)


@pytest.fixture
def backend():
    b = memory()
    b.start()
    return b


def _make_secret(expiration="1 hour"):
    s = secret()
    s.create(expiration=expiration, key_pass=b"pw", data="ciphertext")
    return s


def test_set_then_get_roundtrip(backend):
    s = _make_secret()
    assert backend.set_secret(s) is True
    retrieved = backend.get_secret(s.id)
    assert retrieved is s
    assert retrieved.data == "ciphertext"


def test_get_missing_secret_returns_false(backend):
    assert backend.get_secret("a" * 40) is False


def test_set_secret_rejects_invalid_id(backend):
    s = secret()
    s.id = "too-short"
    assert backend.set_secret(s) is False


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
    # Second attempt — the secret is gone.
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

    assert backend.get_secret(fresh.id) is fresh
    assert backend.get_secret(stale.id) is False


def test_delete_expired_leaves_one_time_within_grace_window(backend):
    """Unclaimed one-time secrets should survive the cleaner sweep until
    they pass the 30-day grace window."""
    ot = _make_secret("One time use")
    backend.set_secret(ot)
    backend.delete_expired()
    assert backend.get_secret(ot.id) is ot

    ot.create_date = int(time.time()) - 86400 * 31
    backend.delete_expired()
    assert backend.get_secret(ot.id) is False
