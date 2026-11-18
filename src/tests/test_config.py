"""Unit tests for the YAML config loader."""

import pytest

from whisper import (
    ConfigError,
    ConfigMissingError,
    ConfigUnknownError,
    load_config,
)

VALID_CONFIG = """\
secret_key: "abcdefghijklmnopqrstuvwxyz_0123456"
storage_class: whisper.storage.memory.memory
storage_config: {}
storage_clean_interval: 900
max_data_size_kb: 100
app_listen_ip: 127.0.0.1
app_port: 5000
app_url_base: /
argon2_time_cost: 1
argon2_memory_cost: 8
argon2_parallelism: 1
"""


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return str(p)


def test_load_valid_config(tmp_path):
    cfg = load_config(config_filenames=[_write(tmp_path, VALID_CONFIG)])
    assert cfg.secret_key == "abcdefghijklmnopqrstuvwxyz_0123456"
    assert cfg.storage_class == "whisper.storage.memory.memory"
    assert cfg.app_port == 5000
    assert cfg.argon2_time_cost == 1


def test_missing_required_key_raises(tmp_path):
    # Drop secret_key — load_config should refuse.
    missing = VALID_CONFIG.replace(
        'secret_key: "abcdefghijklmnopqrstuvwxyz_0123456"\n', ""
    )
    with pytest.raises(ConfigMissingError):
        load_config(config_filenames=[_write(tmp_path, missing)])


def test_unknown_key_raises(tmp_path):
    poisoned = VALID_CONFIG + "bogus_key: 42\n"
    with pytest.raises(ConfigUnknownError):
        load_config(config_filenames=[_write(tmp_path, poisoned)])


def test_duplicate_key_raises(tmp_path):
    dupe = VALID_CONFIG + "app_port: 9999\n"
    with pytest.raises(ConfigError):
        load_config(config_filenames=[_write(tmp_path, dupe)])


def test_missing_file_falls_back_to_defaults(tmp_path):
    # Non-existent file is logged and skipped; the resulting defaults-only
    # config is still missing required keys, so loading fails at check_config.
    with pytest.raises(ConfigMissingError):
        load_config(config_filenames=[str(tmp_path / "does-not-exist.yaml")])


def test_config_text_takes_precedence_over_files(tmp_path):
    file_path = _write(tmp_path, VALID_CONFIG)
    text = VALID_CONFIG.replace("abcdefghijklmnopqrstuvwxyz_0123456", "from_env_" + "x" * 30)
    cfg = load_config(config_filenames=[file_path], config_text=text)
    assert cfg.secret_key == "from_env_" + "x" * 30


def test_config_text_minimal_uses_defaults():
    cfg = load_config(
        config_text='secret_key: "k"\nstorage_class: whisper.storage.memory.memory\n'
    )
    assert cfg.trusted_proxy_count == 0
    assert cfg.max_data_size_kb == 100


def test_config_text_rejects_non_mapping():
    with pytest.raises(ConfigError):
        load_config(config_text="- just\n- a list\n")


def test_empty_config_file_reports_missing_keys(tmp_path):
    with pytest.raises(ConfigMissingError):
        load_config(config_filenames=[_write(tmp_path, "")])
