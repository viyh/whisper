"""Shared pytest fixtures.

The `app` module has import-time side effects: it loads ``CONFIG_FILE``,
instantiates the rate limiter, builds the storage backend, and starts the
cleaner thread. To keep tests deterministic and isolated from any real config
on disk, we build a throwaway config file in a tmp directory at session scope,
point ``CONFIG_FILE`` at it, then import ``app``.
"""

import os
import sys

import pytest

# Ensure the ``src/`` directory (one level up) is importable, so ``import app``
# and ``import whisper`` work regardless of how pytest is invoked.
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


TEST_CONFIG_YAML = """\
secret_key: "test_secret_key_padding_to_at_least_32_bytes_xxx"
storage_class: whisper.storage.memory.memory
storage_config: {}
storage_clean_interval: 86400
max_data_size_kb: 100
app_listen_ip: 127.0.0.1
app_port: 5000
app_url_base: /
argon2_time_cost: 1
argon2_memory_cost: 8
argon2_parallelism: 1
"""


@pytest.fixture(scope="session")
def test_config_path(tmp_path_factory):
    """Write a minimal in-memory-backend config file for the whole test run."""
    config_path = tmp_path_factory.mktemp("whisper") / "config.yaml"
    config_path.write_text(TEST_CONFIG_YAML)
    return str(config_path)


@pytest.fixture(scope="session")
def app_module(test_config_path):
    """Import ``app`` with the test config active.

    Session-scoped so the module-level storage backend and Argon2 hasher are
    built exactly once across the run.
    """
    os.environ["CONFIG_FILE"] = test_config_path
    import app as app_module  # noqa: E402  (import after env setup is deliberate)

    # Disable rate limiting for tests. The per-secret failed-attempt lockout
    # in show_secret is still exercised — we just don't want to trip
    # flask-limiter's in-memory 10/min cap while testing that logic.
    app_module.limiter.enabled = False
    return app_module


@pytest.fixture
def client(app_module):
    """Flask test client, with a clean in-memory store per test."""
    # Wipe the in-memory store between tests so IDs don't leak across.
    app_module.store.backend.secrets.clear()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def config(app_module):
    """Shortcut to the loaded config object."""
    return app_module.config
