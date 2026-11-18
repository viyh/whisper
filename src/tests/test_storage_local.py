"""Unit tests for the local-disk storage backend."""

import os
import secrets
import stat

import pytest

from whisper import AttrDict, secret
from whisper.storage.local import local


@pytest.fixture
def backend(tmp_path):
    b = local()
    b.config = AttrDict({"path": str(tmp_path / "store")})
    b.start()
    return b


def _make_secret(expiration="1 hour"):
    s = secret()
    s.create(
        secret_id=secrets.token_hex(32), expiration=expiration, auth="a" * 64, key="k",
        data="ciphertext",
    )
    return s


def test_roundtrip_and_owner_only_permissions(backend):
    s = _make_secret()
    assert backend.set_secret(s) is True
    path = os.path.join(backend.config.path, f"{s.id}.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert backend.get_secret(s.id).__dict__ == s.__dict__


def test_set_secret_never_replaces_an_existing_secret(backend):
    s = _make_secret()
    assert backend.set_secret(s) is True
    other = _make_secret()
    other.id, other.data = s.id, "attacker-data"
    assert backend.set_secret(other) is False
    assert backend.get_secret(s.id).data == "ciphertext"


def test_delete_expired_removes_leftover_v2_files(backend):
    import json

    path = os.path.join(backend.config.path, "a" * 40 + ".json")
    with open(path, "w") as f:
        json.dump({"id": "a" * 40, "create_date": 1, "expire_date": 2, "data": "x",
                   "hash": "$argon2id$...", "version": 2, "failed_attempts": 0}, f)
    backend.delete_expired()
    assert not os.path.exists(path)


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
