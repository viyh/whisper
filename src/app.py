import logging

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from whisper import load_config, secret
from whisper.storage import store

__version__ = "0.1.0"

app = Flask("whisper")
app.wsgi_app = ProxyFix(app.wsgi_app, x_host=1)

if __name__ != "__main__":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)


@app.route("/assets/<path:path>")
def send_assets(path):
    """Serve asset files."""
    return send_from_directory("assets", path)


@app.route("/", methods=["GET"])
def new_secret():
    """Index page, start a new secret"""
    app.logger.debug(f"[{request.remote_addr}] Index")
    return render_template("index.html", version=__version__)


@app.route("/", methods=["POST"])
def create_secret():
    """Create a new secret"""
    # This has to be here in order for Flask to check against MAX_CONTENT_LENGTH
    # See: https://github.com/pallets/flask/issues/2690
    request.data
    # create secret object
    s = secret()
    s.create(
        expiration=request.json["expiration"],
        key_pass=s.get_key_pass(request.json["password"], config.get("secret_key")),
        data=request.json["encrypted_data"],
    )
    app.logger.info(f"[{request.remote_addr}] Secret create: {s.id}")
    # store the secret
    store.set_secret(s)
    return jsonify({"id": s.id})


@app.route("/<string:secret_id>", methods=["GET"])
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
        )
    else:
        return redirect(url_for("new_secret"))


@app.route("/<string:secret_id>", methods=["POST"])
def show_secret(secret_id):
    """Retrieve encrypted data."""
    # get secret
    s = store.get_secret(secret_id)
    if not s or not s.check_id():
        app.logger.info(
            f"[{request.remote_addr}] Secret invalid secret_id: {secret_id}"
        )
        return jsonify({"result": "Invalid ID"})

    # check the password
    key_pass = s.get_key_pass(request.json["password"], config.get("secret_key"))
    if not s.check_password(key_pass):
        app.logger.info(f"[{request.remote_addr}] Secret invalid password: {s.id}")
        return jsonify({"result": "Invalid password."})

    # delete if one-time secret
    if s.is_one_time():
        store.delete_secret(secret_id)

    # return the secret
    app.logger.info(f"[{request.remote_addr}] Secret retrieved: {s.id}")
    return jsonify({"encrypted_data": s.data})


@app.errorhandler(404)
def not_found(error):
    return redirect(url_for("new_secret"))


@app.errorhandler(413)
def request_entity_too_large(error):
    return (
        jsonify(
            {
                "result": "Maximum file upload size is "
                f"{config.get('max_data_size_mb', 1)} MB"
            }
        ),
        413,
    )


config = load_config()
store = store(
    config.get("storage_class"),
    config.get("storage_config"),
    clean_interval=config.get("storage_clean_interval", 3600),
)
store.start()
app.config["MAX_CONTENT_LENGTH"] = config.get("max_data_size_mb", 1) * 1000 * 1000

if __name__ == "__main__":
    app.run(
        host=config["app_listen_ip"],
        port=config["app_port"],
        debug=config["debug"],
    )
