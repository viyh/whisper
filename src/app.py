from flask import (
    Flask,
    render_template,
    send_from_directory,
    redirect,
    url_for,
    jsonify,
    request,
)

import logging
from whisper.storage import store
from whisper import secret, load_config
from werkzeug.middleware.proxy_fix import ProxyFix

__version__ = "0.1.0"

app = Flask("whisper")
app.wsgi_app = ProxyFix(app.wsgi_app, x_host=1)

if __name__ != "__main__":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)


@app.route("/assets/whisper.js")
def send_whisperjs():
    """Serve js files."""
    return render_template("whisper.js", web_url=config["web_url"])


@app.route("/assets/<path:path>")
def send_assets(path):
    """Serve asset files."""
    return send_from_directory("assets", path)


@app.route("/", methods=["GET"])
def new_secret():
    """Create a new secret"""
    app.logger.debug(f"[{request.remote_addr}] Index")
    return render_template("index.html", version=__version__)


@app.route("/", methods=["POST"])
def create_secret():
    """Create a new secret"""
    s = secret()
    # This has to be here in order for Flask to check against MAX_CONTENT_LENGTH
    # See: https://github.com/pallets/flask/issues/2690
    request.data
    s.create(
        expiration=request.json["expiration"],
        key_pass=s.get_key_pass(request.json["password"], config.get("secret_key")),
        data=request.json["encrypted_data"],
    )
    app.logger.info(f"[{request.remote_addr}] Secret create: {s.id}")
    store.set_secret(s)
    return jsonify({"id": s.id})


@app.route("/<string:secret_id>", methods=["GET"])
def get_secret(secret_id):
    """Display page to retrieve secret"""
    s = store.get_secret(secret_id)
    if s and s.check_id():
        app.logger.info(f"[{request.remote_addr}] Secret request: {s.id}")
        return render_template("show.html", version=__version__, secret_id=secret_id)
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

    # check secret
    key_pass = s.get_key_pass(request.json["password"], config.get("secret_key"))
    if not s.check_password(key_pass):
        app.logger.info(f"[{request.remote_addr}] Secret invalid password: {s.id}")
        return jsonify({"result": "Invalid password."})

    # delete one-time secrets
    if s.is_one_time():
        store.delete_secret(secret_id)

    app.logger.info(f"[{request.remote_addr}] Secret retrieved: {s.id}")
    return jsonify({"encrypted_data": s.data})


@app.errorhandler(413)
def request_entity_too_large(error):
    return (
        {
            "result": "Maximum file upload size is "
            f"{config.get('max_data_size_mb', 1)} MB"
        },
        413,
    )


config = load_config()
store = store(config.get("storage_class"), config.get("storage_config"))
store.start()
app.config["MAX_CONTENT_LENGTH"] = config.get("max_data_size_mb", 1) * 1000 * 1000

if __name__ == "__main__":
    app.run(
        host=config["app_listen_ip"],
        port=config["app_port"],
        debug=config["debug"],
    )
