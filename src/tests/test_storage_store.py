"""Tests for the storage base class and the background cleaner."""

import secrets
import threading
import time

import pytest

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


def test_wipe_secret_does_not_recreate_a_deleted_secret(tmp_path):
    for st in (_store_with_memory_backend(), _store_with_local_backend(tmp_path / "store")):
        s = _make_secret()
        st.set_secret(s)
        st.delete_secret(s.id)
        assert st.wipe_secret(s.id) is False
        assert st.backend.get_secret(s.id) is False


def test_wipe_secret_gives_up_quietly_when_busy(monkeypatch):
    from whisper.storage import StorageBusy

    st = _store_with_memory_backend()

    def busy(secret_id, change):
        raise StorageBusy()

    monkeypatch.setattr(st.backend, "modify_secret", busy)
    assert st.wipe_secret(_make_secret().id) is False


@pytest.fixture(params=["memory", "local"])
def st(request, tmp_path):
    if request.param == "memory":
        return _store_with_memory_backend()
    return _store_with_local_backend(tmp_path / "store")


def test_opening_a_one_time_secret_keeps_its_id_taken(st):
    """Its record stays, without the ciphertext, until it expires. Before,
    anyone with the link and password could store it again after reading
    it, and the recipient would never see "already viewed"."""
    s = _make_secret("One time use")
    st.set_secret(s)
    opened = st.open_secret(st.get_secret(s.id))
    assert opened.data == "ciphertext"
    stored = st.get_secret(s.id)
    assert (stored.data, stored.hash) == ("", "")
    assert (stored.create_date, stored.expire_date) == (s.create_date, s.expire_date)
    assert st.open_secret(s) is False
    assert st.set_secret(s) is False


def test_only_one_simultaneous_open_gets_a_one_time_secret(st):
    s = _make_secret("One time use")
    st.set_secret(s)
    start = threading.Barrier(20)
    results = []

    def open_it():
        loaded = st.get_secret(s.id)
        start.wait()
        results.append(st.open_secret(loaded))

    threads = [threading.Thread(target=open_it) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [r.data for r in results if r] == ["ciphertext"]


@pytest.mark.parametrize("expiration", ["One time use", "1 hour"])
def test_a_secret_locked_since_it_was_read_does_not_open(st, expiration):
    """Wrong passwords sent at the same moment as the right one count."""
    s = _make_secret(expiration)
    st.set_secret(s)
    loaded = st.get_secret(s.id)  # the right password's request reads it...
    for _ in range(3):  # ...and wrong passwords lock it meanwhile
        assert st.record_failed_attempt(st.get_secret(s.id)) is True
    assert st.open_secret(loaded, max_failed_attempts=3) is False
    assert st.get_secret(s.id).data == "ciphertext"  # not claimed
    assert st.open_secret(loaded, max_failed_attempts=4).data == "ciphertext"


@pytest.mark.parametrize("expiration", ["One time use", "1 hour"])
def test_a_secret_wiped_since_it_was_read_does_not_open(st, expiration):
    s = _make_secret(expiration)
    st.set_secret(s)
    loaded = st.get_secret(s.id)
    assert st.wipe_secret(s.id) is True
    assert st.open_secret(loaded) is False


def test_a_time_limited_secret_opens_from_the_stored_copy(st):
    s = _make_secret()
    st.set_secret(s)
    loaded = st.get_secret(s.id)
    loaded.data = "stale"
    assert st.open_secret(loaded).data == "ciphertext"
    assert st.open_secret(loaded).data == "ciphertext"  # not claimed
    loaded.hash = "another record"
    assert st.open_secret(loaded) is False


def test_record_failed_attempt_counts_on_the_stored_copy(st):
    s = _make_secret()
    st.set_secret(s)
    stale = st.get_secret(s.id)
    assert st.record_failed_attempt(st.get_secret(s.id)) is True
    assert st.record_failed_attempt(stale) is True
    assert stale.failed_attempts == 2
    assert st.get_secret(s.id).failed_attempts == 2
    assert st.record_failed_attempt(_make_secret()) is False  # not stored


def test_default_modify_secret_for_other_backends():
    """A backend without its own modify_secret gets one built on
    get_secret and update_secret."""
    from whisper.storage.memory import memory

    class plain(memory):
        modify_secret = store.modify_secret

    st = store("x", {}, clean_interval=86400)
    st.backend = plain()
    st.backend.start()
    s = _make_secret("One time use")
    st.set_secret(s)
    assert st.record_failed_attempt(st.get_secret(s.id)) is True
    assert st.open_secret(st.get_secret(s.id)).failed_attempts == 1
    assert st.get_secret(s.id).is_wiped()
    assert st.backend.modify_secret("b" * 64, lambda stored: stored) == (None, None)


def test_the_attempt_that_reaches_the_limit_wipes_in_the_same_write(st, monkeypatch):
    s = _make_secret()
    st.set_secret(s)
    for _ in range(2):
        assert st.record_failed_attempt(st.get_secret(s.id), max_failed_attempts=3) is True
    writes = []
    real = st.backend.modify_secret
    monkeypatch.setattr(st.backend, "modify_secret", lambda *a: writes.append(1) or real(*a))
    loaded = st.get_secret(s.id)
    assert st.record_failed_attempt(loaded, max_failed_attempts=3) is True
    assert loaded.failed_attempts == 3 and len(writes) == 1
    stored = st.get_secret(s.id)
    assert (stored.data, stored.hash, stored.failed_attempts) == ("", "", 3)


@pytest.mark.parametrize("state", ["locked", "read"])
def test_no_count_is_written_for_a_secret_that_cant_be_opened(st, state):
    """Not past the limit (contention for nothing), and not on a one-time
    secret's kept record (it would answer "locked" instead of "already
    viewed")."""
    s = _make_secret("One time use")
    st.set_secret(s)
    stale = st.get_secret(s.id)
    if state == "locked":
        for _ in range(3):
            st.record_failed_attempt(st.get_secret(s.id), max_failed_attempts=3)
    else:
        assert st.open_secret(st.get_secret(s.id))
    before = st.get_secret(s.id).__dict__
    assert st.record_failed_attempt(stale, max_failed_attempts=3) is False
    assert st.get_secret(s.id).__dict__ == before
