"""Tests for client IP resolution behind proxies (trusted_proxy_count).

Gunicorn serves requests directly, so REMOTE_ADDR is whatever connected to
the container: the client itself, or the nearest proxy. Each proxy in front
appends the address it received the connection from to X-Forwarded-For."""

import pytest
from flask import Flask, jsonify, request

from whisper import ConfigError, apply_proxy_fix

CLIENT = "203.0.113.7"
SPOOFED = "198.51.100.66"
LB = "10.0.1.25"
GFE = "35.191.0.9"


def _client_ip(trusted_proxy_count, remote_addr, xff=None):
    app = Flask(__name__)
    app.wsgi_app = apply_proxy_fix(app.wsgi_app, trusted_proxy_count)

    @app.route("/")
    def ip():
        # JSON, not HTML, so the reflected value can't be rendered as markup
        return jsonify(ip=request.remote_addr)

    headers = {"X-Forwarded-For": xff} if xff else {}
    with app.test_client() as c:
        return c.get(
            "/", headers=headers, environ_base={"REMOTE_ADDR": remote_addr}
        ).get_json()["ip"]


def test_direct_client():
    assert _client_ip(0, CLIENT) == CLIENT


def test_direct_client_cannot_spoof():
    # with no proxies configured, X-Forwarded-For is ignored entirely
    assert _client_ip(0, CLIENT, xff=SPOOFED) == CLIENT


def test_behind_proxy_without_config_sees_only_the_proxy():
    assert _client_ip(0, LB, xff=CLIENT) == LB


def test_behind_one_proxy():
    # client -> load balancer (appends client) -> container
    assert _client_ip(1, LB, xff=CLIENT) == CLIENT


def test_behind_one_proxy_cannot_spoof():
    assert _client_ip(1, LB, xff=f"{SPOOFED}, {CLIENT}") == CLIENT


def test_behind_proxy_adding_two_entries():
    # e.g. a load balancer that appends "<client>, <lb ip>"
    assert _client_ip(2, GFE, xff=f"{SPOOFED}, {CLIENT}, 34.1.2.3") == CLIENT


@pytest.mark.parametrize("bad", [-1, "1", 1.5, True, None])
def test_rejects_invalid_values(bad):
    with pytest.raises(ConfigError):
        apply_proxy_fix(Flask(__name__).wsgi_app, bad)
