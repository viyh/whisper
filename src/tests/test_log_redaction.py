"""Full secret IDs must not reach any log output, including error paths:
Flask's exception logging, cleaner tracebacks, and gunicorn's logs."""

import io
import logging
import threading
from datetime import timedelta
from types import SimpleNamespace

import pytest

from whisper.log_redaction import SecretIdRedactingFilter, install_redaction

SID = "0123456789abcdef" * 2 + "01234567"


@pytest.fixture
def captured(request):
    """Attach a redacting StringIO handler to a logger; yield (stream, logger)."""
    created = []

    def attach(name):
        logger = logging.getLogger(name)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)
        old_level = logger.level
        logger.setLevel(logging.DEBUG)
        install_redaction(logger)
        created.append((logger, handler, old_level))
        return stream

    yield attach
    for logger, handler, old_level in created:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_filter_redacts_message_args_traceback_and_stack():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretIdRedactingFilter())
    logger = logging.getLogger("test.redaction.unit")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        logger.warning("path %s", f"/{SID}")
        try:
            raise OSError(13, "Permission denied", f"/data/{SID}.json")
        except OSError:
            logger.exception("failed")
        logger.warning("with stack", stack_info=True, extra={"x": SID})
    finally:
        logger.removeHandler(handler)
    out = stream.getvalue()
    assert SID not in out
    assert "/0123456789..." not in out  # sanity: prefix is 8 chars
    assert "/01234567..." in out
    assert "Permission denied" in out


def test_filter_survives_bad_format_args():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "%(a)s %s", ({"a": SID},), None)
    assert SecretIdRedactingFilter().filter(record)
    assert SID not in record.getMessage()


def test_flask_exception_log_is_redacted(client, app_module, captured, monkeypatch):
    stream = captured(app_module.app.logger.name)
    sid, auth = "e" * 64, "f" * 64
    client.post(
        "/",
        json={"id": sid, "auth": auth, "expiration": "One time use",
              "encrypted_data": "x", "version": 3},
    )

    def boom(s, max_failed_attempts=0):
        raise RuntimeError(f"backend failed on secrets/{s.id}.json")

    monkeypatch.setattr(app_module.store, "open_secret", boom)
    monkeypatch.setitem(app_module.app.config, "PROPAGATE_EXCEPTIONS", False)
    r = client.post("/retrieve", json={"id": sid, "auth": auth})
    assert r.status_code == 500
    out = stream.getvalue()
    assert "Exception on /retrieve" in out and "RuntimeError" in out
    assert sid not in out
    assert sid[:8] + "..." in out


def test_cleaner_traceback_is_redacted(captured):
    from whisper.storage import store_cleaner

    # whisper.storage logs propagate to the "whisper" (Flask app) logger,
    # whose handlers carry the filter in production
    stream = captured("whisper")
    done = threading.Event()

    class FailingStore:
        clean_interval = 0.01

        def delete_expired(self):
            if done.is_set():
                return
            done.set()
            raise PermissionError(13, "Permission denied", f"/data/{SID}.json")

    store_cleaner(FailingStore())
    assert done.wait(timeout=5)
    for _ in range(100):
        if "Permission denied" in stream.getvalue():
            break
        threading.Event().wait(0.01)
    out = stream.getvalue()
    assert "Permission denied" in out
    assert SID not in out


def test_gunicorn_access_and_error_logs_are_redacted():
    from gunicorn.config import Config

    from whisper.gunicorn_logging import RedactingLogger

    cfg = Config()
    cfg.set("accesslog", "-")
    cfg.set("loglevel", "debug")
    logger = RedactingLogger(cfg)
    stream = io.StringIO()
    for h in logger.access_log.handlers + logger.error_log.handlers:
        h.setStream(stream)

    req = SimpleNamespace(
        method="POST", path=f"/{SID}", query="", version=(1, 1),
        uri=f"/{SID}", headers=[("REFERER", f"https://w.example/{SID}")],
    )
    resp = SimpleNamespace(status="200 OK", sent=10, headers=[])
    environ = {
        "REMOTE_ADDR": "203.0.113.9",
        "REQUEST_METHOD": "POST",
        "RAW_URI": f"/{SID}",
        "PATH_INFO": f"/{SID}",
        "QUERY_STRING": "",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_REFERER": f"https://w.example/{SID}",
    }
    logger.access(resp, req, environ, timedelta(seconds=0.1))
    logger.debug("%s %s", "POST", f"/{SID}")
    logger.critical("fatal on %s", f"/{SID}")
    try:
        raise ValueError(f"bad /{SID}")
    except ValueError:
        logger.exception("Error handling request %s", f"/{SID}")

    out = stream.getvalue()
    assert "POST /01234567... HTTP/1.1" in out
    assert "https://w.example/01234567..." in out
    assert "ValueError" in out
    assert SID not in out
