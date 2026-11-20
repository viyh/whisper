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


def _add_one(stored):
    stored.failed_attempts += 1
    return stored


def test_modify_secret_writes_the_change(backend):
    s = _make_secret()
    backend.set_secret(s)
    stored, written = backend.modify_secret(s.id, _add_one)
    assert (stored.failed_attempts, written.failed_attempts) == (0, 1)
    assert backend.get_secret(s.id).failed_attempts == 1
    assert backend.modify_secret(s.id, lambda stored: None)[1] is None
    assert backend.get_secret(s.id).failed_attempts == 1


def test_modify_secret_rejects_an_invalid_id(backend):
    assert backend.modify_secret("../other", _add_one) == (None, None)


def test_update_secret_does_not_recreate_deleted_secret(backend):
    s = _make_secret("One time use")
    backend.set_secret(s)
    backend.delete_secret(s.id)
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


def test_storage_directory_is_owner_only(backend):
    assert stat.S_IMODE(os.stat(backend.config.path).st_mode) == 0o700


def _start(path):
    b = local()
    b.config = AttrDict({"path": str(path)})
    b.start()
    return b


def test_an_existing_private_directory_is_used_quietly(tmp_path, caplog):
    os.mkdir(tmp_path / "store", 0o700)
    with caplog.at_level("WARNING"):
        _start(tmp_path / "store")
    assert not caplog.records


def test_a_directory_others_can_use_is_warned_about(tmp_path, caplog):
    """e.g. /tmp/whisper created by another user before whisper started."""
    os.mkdir(tmp_path / "store")
    os.chmod(tmp_path / "store", 0o777)
    with caplog.at_level("WARNING"):
        _start(tmp_path / "store")
    assert "isn't private" in caplog.text and "777" in caplog.text


def test_a_storage_path_that_is_not_a_directory_is_refused(tmp_path):
    from whisper import ConfigError

    (tmp_path / "store").write_text("")
    with pytest.raises(ConfigError):
        _start(tmp_path / "store")


def test_a_rewrite_does_not_write_through_a_planted_link(backend, tmp_path):
    """Another local user who controls the directory could link the
    predictable temp file to any file whisper can write."""
    s = _make_secret()
    backend.set_secret(s)
    victim = tmp_path / "victim"
    victim.write_text("keep")
    os.symlink(victim, os.path.join(backend.config.path, f"{s.id}.json.tmp"))
    assert backend.modify_secret(s.id, _add_one)[1]
    assert victim.read_text() == "keep"
    assert backend.get_secret(s.id).failed_attempts == 1
    assert os.listdir(backend.config.path) == [f"{s.id}.json"]


def test_a_secret_file_is_not_read_through_a_link(backend, tmp_path):
    import json

    s = _make_secret()
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps(s.__dict__))
    os.symlink(elsewhere, os.path.join(backend.config.path, f"{s.id}.json"))
    assert backend.get_secret(s.id) is False


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


def test_modify_does_not_recreate_deleted_secret(backend):
    s = _make_secret()
    backend.set_secret(s)
    backend.delete_secret(s.id)
    assert backend.modify_secret(s.id, _add_one) == (None, None)
    assert os.listdir(backend.config.path) == []


def test_cleaner_leaves_a_new_unreadable_file_alone(backend):
    """It may be another process halfway through writing it."""
    sid = secrets.token_hex(32)
    path = os.path.join(backend.config.path, f"{sid}.json")
    with open(path, "w") as f:
        f.write('{"id": "')  # half-written
    backend.delete_expired()
    assert os.path.exists(path)
    old = os.path.getmtime(path) - 120
    os.utime(path, (old, old))
    backend.delete_expired()
    assert not os.path.exists(path)


def test_delete_secret_tolerates_a_file_that_is_already_gone(backend, monkeypatch):
    s = _make_secret()
    backend.set_secret(s)
    os.remove(os.path.join(backend.config.path, f"{s.id}.json"))
    monkeypatch.setattr(os.path, "exists", lambda p: True)  # lose the race
    assert backend.delete_secret(s.id) is True


def test_modify_leaves_no_temp_file_behind(backend):
    s = _make_secret("One time use")
    backend.set_secret(s)
    assert backend.modify_secret(s.id, _add_one)[1]
    assert os.listdir(backend.config.path) == [f"{s.id}.json"]


def test_rewrite_replaces_the_file_whole(backend):
    s = _make_secret()
    backend.set_secret(s)
    s.failed_attempts = 2
    assert backend.update_secret(s) is True
    path = os.path.join(backend.config.path, f"{s.id}.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert os.listdir(backend.config.path) == [f"{s.id}.json"]


def test_rewrite_keeps_the_old_file_if_writing_fails(backend, monkeypatch):
    """A crash or full disk mid-write used to leave a cut-off secret."""
    import json

    s = _make_secret()
    backend.set_secret(s)

    def disk_full(obj, fp):
        fp.write('{"id": "')
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json, "dump", disk_full)
    s.failed_attempts = 1
    with pytest.raises(OSError):
        backend.update_secret(s)
    monkeypatch.undo()
    assert backend.get_secret(s.id).failed_attempts == 0
    assert os.listdir(backend.config.path) == [f"{s.id}.json"]


@pytest.mark.parametrize("suffix", [".tmp", ".claimed"])
def test_cleaner_removes_old_leftover_files(backend, suffix):
    path = os.path.join(backend.config.path, secrets.token_hex(32) + ".json" + suffix)
    foreign = os.path.join(backend.config.path, "notes.json" + suffix)
    for p in (path, foreign):
        with open(p, "w") as f:
            f.write("{}")
    backend.delete_expired()
    assert os.path.exists(path)  # may still be in use
    for p in (path, foreign):
        old = os.path.getmtime(p) - 120
        os.utime(p, (old, old))
    backend.delete_expired()
    assert not os.path.exists(path)
    assert os.path.exists(foreign)  # not named after a secret ID


@pytest.mark.parametrize("content", ["null", "[]", "123", '"text"'])
def test_a_file_that_is_not_an_object_does_not_stop_cleanup(backend, content):
    """It used to raise TypeError: a 500 on read, and every cleanup run
    stopped at that file."""
    sid = secrets.token_hex(32)
    path = os.path.join(backend.config.path, f"{sid}.json")
    with open(path, "w") as f:
        f.write(content)
    assert backend.get_secret(sid) is False
    expired = _make_secret()
    expired.create_date -= 7200
    expired.expire_date -= 7200
    backend.set_secret(expired)
    old = os.path.getmtime(path) - 120
    os.utime(path, (old, old))
    backend.delete_expired()
    assert not os.path.exists(path)
    assert backend.get_secret(expired.id) is False
