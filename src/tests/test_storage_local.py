"""Unit tests for the local-disk storage backend."""

import os
import stat

import pytest

import whisper
from whisper import AttrDict, create_argon2_hasher, secret
from whisper.storage.local import local


@pytest.fixture(autouse=True)
def _fast_argon2(monkeypatch):
    fast = create_argon2_hasher(time_cost=1, memory_cost=8, parallelism=1)
    monkeypatch.setattr(whisper, "_argon2_hasher", fast)


@pytest.fixture
def backend(tmp_path):
    b = local()
    b.config = AttrDict({"path": str(tmp_path / "store")})
    b.start()
    return b


def _make_secret(expiration="1 hour"):
    s = secret()
    s.create(expiration=expiration, key_pass=b"pw", data="ciphertext")
    return s


def test_roundtrip_and_owner_only_permissions(backend):
    s = _make_secret()
    assert backend.set_secret(s) is True
    path = os.path.join(backend.config.path, f"{s.id}.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert backend.get_secret(s.id).__dict__ == s.__dict__


def test_claim_secret_only_once(backend):
    s = _make_secret("One time use")
    backend.set_secret(s)
    assert backend.claim_secret(s.id) is True
    assert backend.claim_secret(s.id) is False
    assert backend.get_secret(s.id) is False


def test_update_secret_does_not_recreate_claimed_secret(backend):
    s = _make_secret("One time use")
    backend.set_secret(s)
    backend.claim_secret(s.id)
    s.failed_attempts = 1
    assert backend.update_secret(s) is False
    assert backend.get_secret(s.id) is False


def test_update_secret_writes_existing_secret(backend):
    s = _make_secret()
    backend.set_secret(s)
    s.failed_attempts = 3
    assert backend.update_secret(s) is True
    assert backend.get_secret(s.id).failed_attempts == 3


def test_delete_expired(backend):
    live, dead = _make_secret(), _make_secret()
    dead.create_date -= 7200
    dead.expire_date -= 7200
    backend.set_secret(live)
    backend.set_secret(dead)
    backend.delete_expired()
    assert backend.get_secret(live.id)
    assert backend.get_secret(dead.id) is False
