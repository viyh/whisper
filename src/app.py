import logging
import os

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from whisper import (
    CURRENT_SECRET_VERSION,
    apply_proxy_fix,
    check_max_failed_attempts,
    is_auth_token,
    is_legacy_secret_id,
    is_secret_id,
    load_config,
    secret,
    short_id,
)
from whisper.log_redaction import install_redaction
from whisper.storage import StorageBusy, store

__version__ = "0.5.2"

app = Flask("whisper")

if __name__ != "__main__":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

# Shorten secret IDs in everything written through the app logger's handlers,
# including Flask's own "Exception on /<path>" lines and tracebacks. Whisper's
# module loggers (whisper.storage.*) propagate here too.
install_redaction(app.logger)

# load configuration file
# (WHISPER_CONFIG, if set, holds the YAML itself and takes precedence)
config_filename = os.environ.get("CONFIG_FILE", "config.yaml")
config = load_config(
    config_filenames=[config_filename],
    config_text=os.environ.get("WHISPER_CONFIG") or None,
)

# trust X-Forwarded-For from the configured number of upstream proxies
app.wsgi_app = apply_proxy_fix(app.wsgi_app, config.trusted_proxy_count)

check_max_failed_attempts(config.max_failed_attempts)

# load_config refuses a missing or placeholder secret_key; a short one only
# gets a warning
if len(config.secret_key) < 32:
    app.logger.warning(
        "WARNING: secret_key is too short. "
        "Set a unique random string of 32+ characters in your config."
    )

# rate limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

VALID_EXPIRATIONS = {"One time use", "1 hour", "1 day", "1 week"}

# Security headers, added to every response.
#   - script-src: 'wasm-unsafe-eval' is required by argon2-browser (WASM).
#     The one third-party library (argon2-browser) is vendored under
#     assets/vendor and served from 'self', so no CDN is trusted or contacted.
#   - style-src: 'self' only. Tooltips are pure CSS and nothing sets inline
#     styles, so 'unsafe-inline' is not needed.
#   - form-action 'none': the forms are only ever handled by JavaScript. If the
#     scripts don't run, the browser can't submit them natively instead.
#   - HSTS: Whisper's threat model assumes HTTPS termination in front of this
#     container. Browsers ignore HSTS on plain-HTTP responses, so local
#     development over http://localhost is unaffected. No "preload": that
#     opts a whole domain into browsers' built-in list, which is the
#     operator's call, not Whisper's.
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self' 'wasm-unsafe-eval'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "form-action 'none';"
    ),
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@app.after_request
def add_security_headers(response):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    # Keep the page and API answers out of HTTP caches. Most browsers also
    # leave no-store pages out of the back/forward cache, so an opened secret
    # isn't restored by Back. Assets stay cacheable.
    if request.endpoint != "send_assets":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.route("/elb-status", methods=["GET"])
def health():
    """Health check for load balancers and container platforms."""
    return "OK", 200, {"Content-Type": "text/plain"}


@app.route(f"{config.app_url_base}assets/<path:path>")
def send_assets(path):
    """Serve asset files."""
    return send_from_directory("assets", path)


@app.route(f"{config.app_url_base}", methods=["GET"])
def new_secret():
    """The one page: creates secrets, or opens one when the URL has a
    #token (the browser decides; the token is never sent to the server)."""
    app.logger.debug(f"[{request.remote_addr}] Index")
    return render_template(
        "index.html",
        version=__version__,
        max_file_size_kb=config.max_data_size_kb,
        argon2_time_cost=config.argon2_time_cost,
        argon2_memory_cost=config.argon2_memory_cost,
        argon2_parallelism=config.argon2_parallelism,
        old_link=request.args.get("old_link") == "1",
    )


def create_rate_limit():
    return f"{config.create_rate_limit} per minute"


@app.route(f"{config.app_url_base}", methods=["POST"])
@limiter.limit(create_rate_limit, exempt_when=lambda: config.create_rate_limit == 0)
def create_secret():
    """Store a new secret, encrypted in the browser."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"result": "Invalid request"}), 400

    # a page loaded before an upgrade sends an older format
    if data.get("version") != CURRENT_SECRET_VERSION:
        return jsonify({"result": "Whisper has been updated. Reload the page and try again."}), 400

    secret_id = data.get("id")
    auth = data.get("auth")
    expiration = data.get("expiration")
    encrypted_data = data.get("encrypted_data")

    if not is_secret_id(secret_id) or not is_auth_token(auth):
        return jsonify({"result": "Invalid request"}), 400

    if not isinstance(encrypted_data, str) or not encrypted_data:
        return jsonify({"result": "Missing required fields"}), 400

    if expiration not in VALID_EXPIRATIONS:
        return jsonify({"result": "Invalid expiration value"}), 400

    s = secret()
    s.create(
        secret_id=secret_id,
        expiration=expiration,
        auth=auth,
        key=config.secret_key,
        data=encrypted_data,
    )
    # create-only: an existing secret is never replaced
    if not store.set_secret(s):
        app.logger.info(f"[{request.remote_addr}] Secret exists: {short_id(s.id)}")
        return jsonify({"result": "Could not create the secret. Please try again."}), 409
    app.logger.info(f"[{request.remote_addr}] Secret create: {short_id(s.id)}")
    return jsonify({"id": s.id})


NOT_FOUND = "This secret doesn't exist, has expired, or was already viewed."
LOCKED = "This secret has been locked due to too many failed attempts."
TRY_AGAIN = "Too many attempts. Please try again later."


@app.route(f"{config.app_url_base}retrieve", methods=["POST"])
@limiter.limit("10 per minute")
def retrieve_secret():
    """Return the encrypted data if the auth token matches."""
    data = request.get_json(silent=True)
    if (
        not isinstance(data, dict)
        or not is_secret_id(data.get("id"))
        or not is_auth_token(data.get("auth"))
    ):
        return jsonify({"result": "Invalid request"}), 400
    secret_id = data["id"]

    s = store.get_secret(secret_id)
    if not s or s.version != CURRENT_SECRET_VERSION:
        app.logger.info(f"[{request.remote_addr}] Secret not found: {short_id(secret_id)}")
        return jsonify({"result": NOT_FOUND})

    # per-secret lock after max_failed_attempts wrong passwords (0 = off)
    max_failed = config.max_failed_attempts
    if s.is_locked(max_failed):
        app.logger.info(f"[{request.remote_addr}] Secret locked: {short_id(s.id)}")
        if s.data or s.hash:
            # locked by an older version, which didn't wipe or wiped in a
            # separate write that could fail
            store.wipe_secret(s.id)
        return jsonify({"result": LOCKED})

    # A one-time secret that was read keeps its record, without the
    # ciphertext, until it expires. (So does a locked secret, if
    # max_failed_attempts was raised since.)
    if s.is_wiped():
        app.logger.info(f"[{request.remote_addr}] Secret already viewed: {short_id(s.id)}")
        return jsonify({"result": NOT_FOUND})

    try:
        if not s.check_auth(data["auth"], config.secret_key):
            return _wrong_password(s, max_failed)
        # checks the stored copy again: it may have been read or locked
        # since s was read
        opened = store.open_secret(s, max_failed)
    except StorageBusy:
        # other requests kept writing to this secret first, so nothing was
        # counted or opened: say nothing about the password
        app.logger.warning(f"[{request.remote_addr}] Secret busy: {short_id(s.id)}")
        return jsonify({"result": TRY_AGAIN}), 429
    if not opened:
        return _no_longer_open(secret_id, max_failed)

    app.logger.info(f"[{request.remote_addr}] Secret retrieved: {short_id(s.id)}")
    return jsonify({"encrypted_data": opened.data, "version": opened.version})


def _wrong_password(s, max_failed):
    app.logger.info(f"[{request.remote_addr}] Secret invalid password: {short_id(s.id)}")
    # The attempt that reaches the limit also wipes the ciphertext, in the
    # same write. Raises StorageBusy if not counted.
    if max_failed and not store.record_failed_attempt(s, max_failed):
        # Locked, read or deleted since s was read, so not counted. Answered
        # as the right password is then, so a guess past the limit can't
        # tell whether it was right.
        return _no_longer_open(s.id, max_failed)
    return jsonify({"result": "Invalid password."})


def _no_longer_open(secret_id, max_failed):
    """The answer for a secret that was read, locked or deleted since the
    request first read it, whether the password was right or wrong:
    "locked" if it's locked, otherwise "doesn't exist or already viewed"."""
    current = store.get_secret(secret_id)
    if current and current.is_locked(max_failed):
        app.logger.info(f"[{request.remote_addr}] Secret locked: {short_id(secret_id)}")
        return jsonify({"result": LOCKED})
    app.logger.info(f"[{request.remote_addr}] Secret already viewed: {short_id(secret_id)}")
    return jsonify({"result": NOT_FOUND})


@app.route(f"{config.app_url_base}<string:secret_id>", methods=["GET", "POST"])
def old_link(secret_id):
    """Links from before 0.4.0 (/<40 hex characters>) can't be opened."""
    if request.method == "POST":
        if not is_legacy_secret_id(secret_id):
            return jsonify({"result": "Not found"}), 404
        # a page loaded before an upgrade, opening an old link
        return jsonify({"result": "Whisper has been updated. This link can no longer be opened."}), 410
    if is_legacy_secret_id(secret_id):
        return redirect(url_for("new_secret", old_link="1"))
    return redirect(url_for("new_secret"))


@app.errorhandler(404)
def not_found(error):
    return redirect(url_for("new_secret"))


@app.errorhandler(413)
def request_entity_too_large(error):
    return (
        jsonify(
            {"result": "Maximum upload size is " f"{config.max_data_size_kb} KB"}
        ),
        413,
    )


@app.errorhandler(429)
def ratelimit_handler(error):
    return (
        jsonify({"result": TRY_AGAIN}),
        429,
    )


# load backend store
store = store(
    config.storage_class,
    config.storage_config,
    clean_interval=config.storage_clean_interval,
)
store.start()

# set max content length
# Account for base64 encoding (~37% overhead) and JSON envelope when setting server limit
app.config["MAX_CONTENT_LENGTH"] = int(config.max_data_size_kb * 1000 * 2)

if __name__ == "__main__":
    # Dev-only entry point. Production runs under gunicorn and never reaches this block.
    # Flask's interactive debugger is intentionally NOT coupled to LOG_LEVEL - set
    # FLASK_DEBUG=1 explicitly if you want the Werkzeug debugger during local dev.
    app.run(
        host=config.app_listen_ip,
        port=config.app_port,
    )
