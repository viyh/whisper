"""HTTP-level tests for the Flask routes via ``app.test_client()``.

Scope: request/response contract, input validation, version enforcement,
create-only storage, one-time claim behavior, failed-attempt lockout, old
(pre-0.4.0) links, and the 413 oversize handler.

In the real browser, the secret ID is SHA-256 of the link's token and the
auth token comes from Argon2id + HKDF (see whisper.js). The server treats
both as opaque 64-character hex strings, so these tests use fixed stand-ins.
"""

import secrets

from whisper import CURRENT_SECRET_VERSION, auth_digest

GOOD_AUTH = "a1" * 32
BAD_AUTH = "b2" * 32


def _new_id():
    return secrets.token_hex(32)


def _create(client, **overrides):
    payload = {
        "id": _new_id(),
        "auth": GOOD_AUTH,
        "expiration": "One time use",
        "encrypted_data": "opaque-ciphertext",
        "version": CURRENT_SECRET_VERSION,
    }
    payload.update(overrides)
    return client.post("/", json=payload), payload["id"]


def _retrieve(client, secret_id, auth=GOOD_AUTH):
    return client.post("/retrieve", json={"id": secret_id, "auth": auth})


def test_index_get_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Whisper" in r.data
    assert b"older version" not in r.data


def test_create_secret_happy_path(client, app_module):
    r, sid = _create(client)
    assert r.status_code == 200
    assert r.get_json() == {"id": sid}
    stored = app_module.store.get_secret(sid)
    assert stored.version == CURRENT_SECRET_VERSION == 3
    # the server keeps an HMAC of the auth token, never the token itself
    assert stored.hash == auth_digest(GOOD_AUTH, app_module.config.secret_key)
    assert GOOD_AUTH not in str(stored.__dict__)


def test_create_never_replaces_an_existing_secret(client, app_module):
    r, sid = _create(client, expiration="1 hour")
    assert r.status_code == 200
    again, _ = _create(client, id=sid, auth=BAD_AUTH, encrypted_data="attacker-data")
    assert again.status_code == 409
    assert app_module.store.get_secret(sid).data == "opaque-ciphertext"
    assert _retrieve(client, sid).get_json()["encrypted_data"] == "opaque-ciphertext"


def test_create_rejects_bad_ids_and_tokens(client):
    for bad in ("a" * 40, "A" * 64, "g" * 64, "a" * 63, 123, None):
        assert _create(client, id=bad)[0].status_code == 400
        assert _create(client, auth=bad)[0].status_code == 400


def test_create_rejects_missing_or_bad_data(client):
    assert _create(client, encrypted_data="")[0].status_code == 400
    assert _create(client, encrypted_data=123)[0].status_code == 400
    assert client.post("/", json={"expiration": "1 hour", "version": 3}).status_code == 400


def test_create_rejects_invalid_expiration(client):
    assert _create(client, expiration="forever")[0].status_code == 400


def test_create_from_a_page_loaded_before_the_upgrade(client):
    """A tab opened before an upgrade sends version 2 (password hash, no ID)."""
    r = client.post(
        "/",
        json={"expiration": "1 hour", "password": "x", "encrypted_data": "y", "version": 2},
    )
    assert r.status_code == 400
    assert "reload" in r.get_json()["result"].lower()


def test_create_rejects_unparseable_or_non_object_json(client):
    assert client.post("/", data="not json", content_type="application/json").status_code == 400
    assert client.post("/", json=["a", "list"]).status_code == 400


def test_retrieve_with_correct_auth(client):
    _, sid = _create(client, expiration="1 hour")
    body = _retrieve(client, sid).get_json()
    assert body == {"encrypted_data": "opaque-ciphertext", "version": CURRENT_SECRET_VERSION}


def test_retrieve_with_wrong_auth_is_rejected(client, app_module):
    _, sid = _create(client, expiration="1 hour")
    assert _retrieve(client, sid, BAD_AUTH).get_json() == {"result": "Invalid password."}
    assert app_module.store.get_secret(sid).failed_attempts == 1


def test_retrieve_unknown_secret(client):
    body = _retrieve(client, _new_id()).get_json()
    assert "encrypted_data" not in body
    assert "doesn't exist" in body["result"]


def test_retrieve_rejects_malformed_requests(client):
    _, sid = _create(client)
    for payload in ({}, {"id": sid}, {"auth": GOOD_AUTH}, {"id": "a" * 40, "auth": GOOD_AUTH},
                    {"id": sid, "auth": "x"}, ["list"]):
        assert client.post("/retrieve", json=payload).status_code == 400


def test_one_time_secret_can_only_be_claimed_once(client):
    _, sid = _create(client, expiration="One time use")
    assert _retrieve(client, sid).get_json()["encrypted_data"] == "opaque-ciphertext"
    second = _retrieve(client, sid).get_json()
    assert "encrypted_data" not in second
    assert "already viewed" in second["result"]


def test_non_one_time_secret_is_reusable(client):
    _, sid = _create(client, expiration="1 hour")
    assert _retrieve(client, sid).get_json()["encrypted_data"] == "opaque-ciphertext"
    assert _retrieve(client, sid).get_json()["encrypted_data"] == "opaque-ciphertext"


def test_failed_attempt_lockout(client, app_module):
    """After 10 wrong passwords the secret refuses even the right one."""
    _, sid = _create(client, expiration="1 hour")
    for _ in range(10):
        _retrieve(client, sid, BAD_AUTH)
    assert "locked" in _retrieve(client, sid).get_json()["result"].lower()
    assert app_module.store.get_secret(sid).failed_attempts == 10


def test_failed_attempt_lock_is_configurable(client, app_module, monkeypatch):
    monkeypatch.setitem(app_module.config, "max_failed_attempts", 3)
    _, sid = _create(client, expiration="1 hour")
    for _ in range(3):
        assert _retrieve(client, sid, BAD_AUTH).get_json() == {"result": "Invalid password."}
    assert "locked" in _retrieve(client, sid).get_json()["result"].lower()


def test_failed_attempt_lock_can_be_turned_off(client, app_module, monkeypatch):
    monkeypatch.setitem(app_module.config, "max_failed_attempts", 0)
    _, sid = _create(client, expiration="1 hour")
    for _ in range(25):
        assert _retrieve(client, sid, BAD_AUTH).get_json() == {"result": "Invalid password."}
    assert _retrieve(client, sid).get_json()["encrypted_data"] == "opaque-ciphertext"
    # not counted at all while the lock is off (no storage write per attempt)
    assert app_module.store.get_secret(sid).failed_attempts == 0


def test_oversize_request_returns_413(client, app_module):
    huge = "A" * (app_module.app.config["MAX_CONTENT_LENGTH"] + 1024)
    r, _ = _create(client, encrypted_data=huge)
    assert r.status_code == 413


def _expire_now(app_module, secret_id):
    """Backdate a stored secret so it is expired but not yet cleaned up."""
    stored = app_module.store.backend.secrets[secret_id]
    stored.create_date -= 7200
    stored.expire_date -= 7200


def test_expired_secret_cannot_be_retrieved_before_cleanup(client, app_module):
    _, sid = _create(client, expiration="1 hour")
    _expire_now(app_module, sid)
    assert "encrypted_data" not in _retrieve(client, sid).get_json()


def test_failed_attempt_does_not_resurrect_claimed_secret(client, app_module):
    """A wrong-password request that loaded the secret before a concurrent
    successful claim must not write it back into storage."""
    _, sid = _create(client)
    loaded = app_module.store.get_secret(sid)  # wrong-password request reads...
    assert app_module.store.claim_secret(sid) is True  # ...recipient claims...
    loaded.failed_attempts += 1
    assert app_module.store.update_secret(loaded) is False  # ...write-back is a no-op
    assert app_module.store.get_secret(sid) is False


def test_old_links_explain_instead_of_failing_silently(client):
    """Links from before 0.4.0 were /<40 hex characters>."""
    r = client.get("/" + "a" * 40)
    assert r.status_code == 302
    assert r.location.endswith("/?old_link=1")
    page = client.get("/?old_link=1")
    assert b"older version of Whisper" in page.data
    # a page loaded before the upgrade posting the old way
    old = client.post("/" + "a" * 40, json={"password": "x"})
    assert old.status_code == 410
    assert "updated" in old.get_json()["result"]


def test_other_paths_redirect_to_index(client):
    r = client.get("/" + "z" * 40)
    assert r.status_code == 302
    assert r.location.endswith("/")


def test_security_headers_on_pages_and_api(client):
    for r in (client.get("/"), _create(client)[0], client.get("/assets/style.css")):
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
        csp = r.headers["Content-Security-Policy"]
        assert "'unsafe-inline'" not in csp
        assert "http" not in csp  # no third-party origins (no CDN)
        assert r.headers["Strict-Transport-Security"].startswith("max-age=63072000")


def test_page_loads_no_third_party_assets(client):
    """Every script and stylesheet is served by Whisper itself, and exists."""
    import re

    html = client.get("/").get_data(as_text=True)
    refs = re.findall(r'<(?:script|link)[^>]*(?:src|href)="([^"]+)"', html)
    assert refs, "expected script/stylesheet references"
    for ref in refs:
        assert not re.match(r"(https?:)?//", ref), ref
        assert client.get("/" + ref).status_code == 200, ref
    assert "style=" not in html  # CSP has no 'unsafe-inline' for styles

    # argon2-browser loads one of these at runtime (not referenced in HTML)
    for wasm in ("argon2.wasm", "argon2-simd.wasm"):
        r = client.get(f"/assets/vendor/argon2-browser-1.18.0/dist/{wasm}")
        assert r.status_code == 200
        assert r.mimetype == "application/wasm"
        assert r.data[:4] == b"\0asm"
    assert client.get("/assets/vendor/argon2-browser-1.18.0/dist/argon2.js").status_code == 200


def test_health_check(client):
    r = client.get("/elb-status")
    assert r.status_code == 200
    assert r.get_data(as_text=True) == "OK"


def test_logs_never_contain_full_ids_or_tokens(client, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    _, sid = _create(client)
    _retrieve(client, sid, BAD_AUTH)
    _retrieve(client, sid)
    _retrieve(client, sid)  # already claimed
    assert sid[:8] in caplog.text
    assert sid not in caplog.text
    assert sid[8:] not in caplog.text
    assert GOOD_AUTH not in caplog.text and BAD_AUTH not in caplog.text


def test_malformed_ids_are_not_logged(client, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    r = client.post("/retrieve", json={"id": "aa\nZZZZ" + "a" * 57, "auth": GOOD_AUTH})
    assert r.status_code == 400
    assert "ZZZZ" not in caplog.text
