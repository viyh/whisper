"""Tests for the storage base class and the background cleaner."""

import secrets
import threading
import time

from whisper import secret
from whisper.storage import store, store_cleaner
from whisper.storage.memory import memory


def _make_secret(expiration="1 hour"):
    s = secret()
    s.create(
        secret_id=secrets.token_hex(32), expiration=expiration, auth="a" * 64, key="k",
        data="ciphertext",
    )
    return s


def _store_with_memory_backend():
    st = store("whisper.storage.memory.memory", {}, clean_interval=86400)
    st.backend = memory()
    st.backend.start()
    return st


def test_get_secret_hides_expired_secret():
    st = _store_with_memory_backend()
    s = _make_secret()
    s.create_date -= 7200
    s.expire_date -= 7200
    st.set_secret(s)
    assert st.get_secret(s.id) is False


def test_get_secret_returns_live_secret():
    st = _store_with_memory_backend()
    s = _make_secret()
    st.set_secret(s)
    assert st.get_secret(s.id).id == s.id


def test_cleaner_survives_backend_errors():
    calls = []
    done = threading.Event()

    class FlakyStore:
        clean_interval = 0.01

        def delete_expired(self):
            calls.append(time.time())
            if len(calls) == 1:
                raise RuntimeError("transient backend failure")
            done.set()

    store_cleaner(FlakyStore())
    assert done.wait(timeout=5), "cleaner thread died after the first error"
    assert len(calls) >= 2


def _store_with_local_backend(path):
    from whisper import AttrDict
    from whisper.storage.local import local

    st = store("whisper.storage.local.local", {}, clean_interval=86400)
    st.backend = local()
    st.backend.config = AttrDict({"path": str(path)})
    st.backend.start()
    return st


def test_wipe_secret_keeps_only_the_locked_record(tmp_path):
    for st in (_store_with_memory_backend(), _store_with_local_backend(tmp_path / "store")):
        s = _make_secret()
        s.failed_attempts = 10
        st.set_secret(s)
        assert st.wipe_secret(s.id) is True
        stored = st.get_secret(s.id)
        assert (stored.data, stored.hash, stored.failed_attempts) == ("", "", 10)
        assert (stored.create_date, stored.expire_date) == (s.create_date, s.expire_date)
        assert st.wipe_secret(s.id) is True  # already wiped: nothing to write


def test_wipe_secret_does_not_recreate_a_secret_claimed_meanwhile(tmp_path, monkeypatch):
    for st in (_store_with_memory_backend(), _store_with_local_backend(tmp_path / "store")):
        s = _make_secret("One time use")
        st.set_secret(s)
        loaded = st.backend.get_secret(s.id)  # the wipe reads it...
        assert st.claim_secret(s.id) is True  # ...the recipient claims it...
        monkeypatch.setattr(st.backend, "get_secret", lambda _id, loaded=loaded: loaded)
        assert st.wipe_secret(s.id) is False  # ...and the wipe writes nothing
        monkeypatch.undo()
        assert st.get_secret(s.id) is False
