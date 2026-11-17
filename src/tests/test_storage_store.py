"""Tests for the storage base class and the background cleaner."""

import threading
import time

import pytest

import whisper
from whisper import create_argon2_hasher, secret
from whisper.storage import store, store_cleaner
from whisper.storage.memory import memory


@pytest.fixture(autouse=True)
def _fast_argon2(monkeypatch):
    fast = create_argon2_hasher(time_cost=1, memory_cost=8, parallelism=1)
    monkeypatch.setattr(whisper, "_argon2_hasher", fast)


def _store_with_memory_backend():
    st = store("whisper.storage.memory.memory", {}, clean_interval=86400)
    st.backend = memory()
    st.backend.start()
    return st


def test_get_secret_hides_expired_secret():
    st = _store_with_memory_backend()
    s = secret()
    s.create(expiration="1 hour", key_pass=b"pw", data="x")
    s.create_date -= 7200
    s.expire_date -= 7200
    st.set_secret(s)
    assert st.get_secret(s.id) is False


def test_get_secret_returns_live_secret():
    st = _store_with_memory_backend()
    s = secret()
    s.create(expiration="1 hour", key_pass=b"pw", data="x")
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
