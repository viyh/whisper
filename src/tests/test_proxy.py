"""Tests for client IP resolution behind proxies (trusted_proxy_count).

Requests are simulated the way they arrive in the container: nginx connects
from 127.0.0.1 and appends the address it received the connection from to
X-Forwarded-For. Upstream proxies add their own entries before that."""

import pytest
from flask import Flask, request

from whisper import ConfigError, apply_proxy_fix

NGINX = "127.0.0.1"
CLIENT = "203.0.113.7"
SPOOFED = "198.51.100.66"
ALB = "10.0.1.25"


def _client_ip(trusted_proxy_count, xff):
    app = Flask(__name__)
    app.wsgi_app = apply_proxy_fix(app.wsgi_app, trusted_proxy_count)

    @app.route("/")
    def ip():
        return request.remote_addr

    with app.test_client() as c:
        return c.get(
            "/", headers={"X-Forwarded-For": xff}, environ_base={"REMOTE_ADDR": NGINX}
        ).get_data(as_text=True)


def test_direct_clients_use_nginx_entry():
    # client -> nginx: nginx appends the client's address
    assert _client_ip(0, CLIENT) == CLIENT


def test_direct_clients_cannot_spoof():
    # client sends a fake XFF; nginx appends the real address after it
    assert _client_ip(0, f"{SPOOFED}, {CLIENT}") == CLIENT


def test_behind_alb_without_config_sees_only_the_proxy():
    # the 0.2.1 behaviour: every client collapses to the load balancer's IP
    assert _client_ip(0, f"{CLIENT}, {ALB}") == ALB


def test_behind_one_proxy():
    # client -> ALB (appends client) -> nginx (appends ALB)
    assert _client_ip(1, f"{CLIENT}, {ALB}") == CLIENT


def test_behind_one_proxy_cannot_spoof():
    assert _client_ip(1, f"{SPOOFED}, {CLIENT}, {ALB}") == CLIENT


def test_behind_proxy_adding_two_entries():
    # e.g. a load balancer that appends "<client>, <lb ip>"
    assert _client_ip(2, f"{SPOOFED}, {CLIENT}, 34.1.2.3, 35.191.0.9") == CLIENT


@pytest.mark.parametrize("bad", [-1, "1", 1.5, True, None])
def test_rejects_invalid_values(bad):
    with pytest.raises(ConfigError):
        apply_proxy_fix(Flask(__name__).wsgi_app, bad)
