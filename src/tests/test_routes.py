"""HTTP-level tests for the Flask routes via ``app.test_client()``.

Scope: request/response contract, input validation, version enforcement,
one-time claim behavior, failed-attempt lockout, and the 413 oversize
handler.

The ``password`` field sent by the real browser is an Argon2id hash
(deterministic salt = ``origin.repeat(2)``). The server treats it as an
opaque string: it concatenates the server-side secret_key and the
client-sent password, then Argon2-hashes *that* for storage. So in these
tests we just send a plain constant string as ``password`` — the server's
hash/verify cycle is still fully exercised."""

from whisper import CURRENT_SECRET_VERSION

# Fixed stand-in for the browser-side Argon2 output. The exact value is
# irrelevant — the server treats it as an opaque string.
GOOD_PW = "browser-argon2-hash-stand-in"
BAD_PW = "wrong-password-stand-in"


def _create(client, **overrides):
    payload = {
        "expiration": "One time use",
        "password": GOOD_PW,
        "encrypted_data": "opaque-ciphertext",
        "version": CURRENT_SECRET_VERSION,
    }
    payload.update(overrides)
    return client.post("/", json=payload)


def test_index_get_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Whisper" in r.data


def test_create_secret_happy_path(client):
    r = _create(client)
    assert r.status_code == 200
    body = r.get_json()
    assert "id" in body
    assert len(body["id"]) == 40


def test_create_rejects_missing_fields(client):
    r = client.post("/", json={"expiration": "1 hour"})
    assert r.status_code == 400


def test_create_rejects_invalid_expiration(client):
    r = _create(client, expiration="forever")
    assert r.status_code == 400


def test_create_rejects_non_string_fields(client):
    r = _create(client, password=12345)
    assert r.status_code == 400


def test_create_rejects_unsupported_version(client):
    r = _create(client, version=1)
    assert r.status_code == 400
    assert "Unsupported version" in r.get_json()["result"]


def test_create_rejects_unparseable_json(client):
    r = client.post("/", data="not json", content_type="application/json")
    assert r.status_code == 400


def test_get_invalid_id_redirects_to_index(client):
    r = client.get("/" + "z" * 40)
    assert r.status_code == 302
    assert r.location.endswith("/")


def test_retrieve_secret_with_correct_password(client):
    create = _create(client, expiration="1 hour")
    secret_id = create.get_json()["id"]

    r = client.post("/" + secret_id, json={"password": GOOD_PW})
    body = r.get_json()
    assert body["encrypted_data"] == "opaque-ciphertext"
    assert body["version"] == CURRENT_SECRET_VERSION


def test_retrieve_secret_with_wrong_password_is_rejected(client):
    create = _create(client, expiration="1 hour")
    secret_id = create.get_json()["id"]

    r = client.post("/" + secret_id, json={"password": BAD_PW})
    assert r.get_json()["result"] == "Invalid password."


def test_one_time_secret_can_only_be_claimed_once(client):
    create = _create(client, expiration="One time use")
    secret_id = create.get_json()["id"]

    first = client.post("/" + secret_id, json={"password": GOOD_PW})
    assert first.get_json()["encrypted_data"] == "opaque-ciphertext"

    second = client.post("/" + secret_id, json={"password": GOOD_PW})
    body = second.get_json()
    # Either "already retrieved" (claim lost) or "Invalid ID" (already gone).
    assert "encrypted_data" not in body
    assert "result" in body


def test_non_one_time_secret_is_reusable(client):
    create = _create(client, expiration="1 hour")
    secret_id = create.get_json()["id"]

    first = client.post("/" + secret_id, json={"password": GOOD_PW})
    second = client.post("/" + secret_id, json={"password": GOOD_PW})
    assert first.get_json()["encrypted_data"] == "opaque-ciphertext"
    assert second.get_json()["encrypted_data"] == "opaque-ciphertext"


def test_failed_attempt_lockout(client, app_module):
    """After 10 failed password attempts, the secret locks out further
    attempts even if the correct password is supplied."""
    create = _create(client, expiration="1 hour")
    secret_id = create.get_json()["id"]

    for _ in range(10):
        client.post("/" + secret_id, json={"password": BAD_PW})

    # Even the correct password should now be refused with the lockout msg.
    r = client.post("/" + secret_id, json={"password": GOOD_PW})
    assert "locked" in r.get_json()["result"].lower()

    # And the secret object should reflect the failed count.
    s = app_module.store.get_secret(secret_id)
    assert s.failed_attempts >= 10


def test_oversize_request_returns_413(client, app_module):
    huge = "A" * (app_module.app.config["MAX_CONTENT_LENGTH"] + 1024)
    r = client.post(
        "/",
        json={
            "expiration": "1 hour",
            "password": "x",
            "encrypted_data": huge,
            "version": CURRENT_SECRET_VERSION,
        },
    )
    assert r.status_code == 413


def _expire_now(app_module, secret_id):
    """Backdate a stored secret so it is expired but not yet cleaned up."""
    stored = app_module.store.backend.secrets[secret_id]
    stored.create_date -= 7200
    stored.expire_date -= 7200


def test_expired_secret_cannot_be_retrieved_before_cleanup(client, app_module):
    sid = _create(client, expiration="1 hour").get_json()["id"]
    _expire_now(app_module, sid)
    r = client.post(f"/{sid}", json={"password": GOOD_PW})
    assert r.get_json() == {"result": "Invalid ID"}


def test_expired_secret_page_redirects(client, app_module):
    sid = _create(client, expiration="1 hour").get_json()["id"]
    _expire_now(app_module, sid)
    r = client.get(f"/{sid}")
    assert r.status_code == 302


def test_failed_attempt_does_not_resurrect_claimed_secret(client, app_module):
    """A wrong-password request that loaded the secret before a concurrent
    successful claim must not write it back into storage."""
    sid = _create(client).get_json()["id"]
    loaded = app_module.store.get_secret(sid)  # wrong-password request reads...
    assert app_module.store.claim_secret(sid) is True  # ...recipient claims...
    loaded.failed_attempts += 1
    assert app_module.store.update_secret(loaded) is False  # ...write-back is a no-op
    assert app_module.store.get_secret(sid) is False


def test_security_headers_on_pages_and_api(client):
    for r in (client.get("/"), _create(client), client.get("/assets/style.css")):
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
        assert "'unsafe-inline'" not in r.headers["Content-Security-Policy"].split("script-src")[1].split(";")[0]
        assert r.headers["Strict-Transport-Security"].startswith("max-age=63072000")


def test_health_check(client):
    r = client.get("/elb-status")
    assert r.status_code == 200
    assert r.get_data(as_text=True) == "OK"


def test_logs_never_contain_full_secret_ids(client, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    sid = _create(client).get_json()["id"]
    client.get(f"/{sid}")
    client.post(f"/{sid}", json={"password": BAD_PW})
    client.post(f"/{sid}", json={"password": GOOD_PW})
    client.post(f"/{sid}", json={"password": GOOD_PW})  # already claimed
    assert sid[:8] in caplog.text
    assert sid not in caplog.text
    assert sid[8:] not in caplog.text


def test_invalid_id_from_url_cannot_inject_log_lines(client, caplog):
    import logging

    caplog.set_level(logging.INFO)
    client.post("/" + "a" * 7 + "%0aFAKE", json={"password": "x"})
    assert "FAKE" not in caplog.text
