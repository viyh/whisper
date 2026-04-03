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
from werkzeug.middleware.proxy_fix import ProxyFix

import whisper as whisper_module
from whisper import create_argon2_hasher, load_config, secret
from whisper.storage import store

__version__ = "0.2.0"

app = Flask("whisper")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0)

if __name__ != "__main__":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

# load configuration file
config_filename = os.environ.get("CONFIG_FILE", "config.yaml")
config = load_config(config_filenames=[config_filename])

# warn if secret_key looks like a default/placeholder
if "CHANGE_ME" in config.secret_key or len(config.secret_key) < 32:
    app.logger.warning(
        "WARNING: secret_key appears to be a default or is too short. "
        "Set a unique random string of 32+ characters in your config."
    )

# rate limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# initialize Argon2id hasher from config
whisper_module._argon2_hasher = create_argon2_hasher(
    time_cost=config.argon2_time_cost,
    memory_cost=config.argon2_memory_cost,
    parallelism=config.argon2_parallelism,
)

VALID_EXPIRATIONS = {"One time use", "1 hour", "1 day", "1 week"}


@app.route(f"{config.app_url_base}assets/<path:path>")
def send_assets(path):
    """Serve asset files."""
    return send_from_directory("assets", path)


@app.route(f"{config.app_url_base}", methods=["GET"])
def new_secret():
    """Index page, start a new secret"""
    app.logger.debug(f"[{request.remote_addr}] Index")
    return render_template(
        "index.html",
        version=__version__,
        max_file_size_kb=config.max_data_size_kb,
        argon2_time_cost=config.argon2_time_cost,
        argon2_memory_cost=config.argon2_memory_cost,
        argon2_parallelism=config.argon2_parallelism,
    )


@app.route(f"{config.app_url_base}", methods=["POST"])
def create_secret():
    """Create a new secret"""
    # validate JSON input
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"result": "Invalid request"}), 400

    expiration = data.get("expiration")
    password = data.get("password")
    encrypted_data = data.get("encrypted_data")

    if not all([expiration, password, encrypted_data]):
        return jsonify({"result": "Missing required fields"}), 400

    if not isinstance(password, str) or not isinstance(encrypted_data, str):
        return jsonify({"result": "Invalid field types"}), 400

    if expiration not in VALID_EXPIRATIONS:
        return jsonify({"result": "Invalid expiration value"}), 400

    # This has to be here in order for Flask to check against MAX_CONTENT_LENGTH
    # See: https://github.com/pallets/flask/issues/2690
    request.data
    # determine version (default to 2 for new secrets)
    version = data.get("version", 2)
    if version not in (1, 2):
        version = 2

    # create secret object
    s = secret()
    s.create(
        expiration=expiration,
        key_pass=s.get_key_pass(password, config.secret_key),
        data=encrypted_data,
        version=version,
    )
    app.logger.info(f"[{request.remote_addr}] Secret create: {s.id}")
    # store the secret
    store.set_secret(s)
    return jsonify({"id": s.id})


@app.route(f"{config.app_url_base}<string:secret_id>", methods=["GET"])
def get_secret(secret_id):
    """Display page to retrieve secret"""
    # get secret object if it exists in storage
    s = store.get_secret(secret_id)
    # if the secret exists, display the password page
    if s and s.check_id():
        app.logger.info(f"[{request.remote_addr}] Secret request: {s.id}")
        return render_template(
            "show.html",
            version=__version__,
            secret_version=getattr(s, "version", 1),
            argon2_time_cost=config.argon2_time_cost,
            argon2_memory_cost=config.argon2_memory_cost,
            argon2_parallelism=config.argon2_parallelism,
        )
    else:
        return redirect(url_for("new_secret"))


@app.route(f"{config.app_url_base}<string:secret_id>", methods=["POST"])
@limiter.limit("10 per minute")
def show_secret(secret_id):
    """Retrieve encrypted data."""
    # validate JSON input
    data = request.get_json(silent=True)
    if not data or not isinstance(data.get("password"), str):
        return jsonify({"result": "Invalid request"}), 400

    # get secret
    s = store.get_secret(secret_id)
    if not s or not s.check_id():
        app.logger.info(
            f"[{request.remote_addr}] Secret invalid secret_id: {secret_id}"
        )
        return jsonify({"result": "Invalid ID"})

    # check per-secret failed attempt lockout
    if hasattr(s, "failed_attempts") and s.failed_attempts >= 10:
        app.logger.info(f"[{request.remote_addr}] Secret locked: {s.id}")
        return jsonify({"result": "This secret has been locked due to too many failed attempts."})

    # check the password
    key_pass = s.get_key_pass(data["password"], config.secret_key)
    if not s.check_password(key_pass):
        app.logger.info(f"[{request.remote_addr}] Secret invalid password: {s.id}")
        # increment failed attempts
        s.failed_attempts = getattr(s, "failed_attempts", 0) + 1
        store.set_secret(s)
        return jsonify({"result": "Invalid password."})

    # for one-time secrets, atomically claim before returning data
    if s.is_one_time():
        if not store.claim_secret(secret_id):
            app.logger.info(
                f"[{request.remote_addr}] Secret already claimed: {secret_id}"
            )
            return jsonify({"result": "This secret has already been retrieved."})

    # return the secret
    app.logger.info(f"[{request.remote_addr}] Secret retrieved: {s.id}")
    return jsonify({"encrypted_data": s.data, "version": getattr(s, "version", 1)})


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
        jsonify({"result": "Too many attempts. Please try again later."}),
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
    # run the app
    app.run(
        host=config.app_listen_ip,
        port=config.app_port,
        debug=os.environ.get("LOG_LEVEL", False) == "DEBUG",
    )
