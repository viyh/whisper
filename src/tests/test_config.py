"""Unit tests for the YAML config loader."""

import pytest

from whisper import (
    ConfigError,
    ConfigMissingError,
    ConfigUnknownError,
    check_max_failed_attempts,
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
    # Drop secret_key - load_config should refuse.
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


def test_short_id():
    from whisper import short_id

    assert short_id("0123456789abcdef" * 2 + "01234567") == "01234567..."
    assert short_id("ab\ncd") == "abcd..."
    assert short_id(None) == "..."


def test_redact_secret_ids():
    from whisper import redact_secret_ids

    sid = "0123456789abcdef" * 2 + "01234567"
    assert redact_secret_ids(f"POST /{sid} HTTP/1.1") == "POST /01234567... HTTP/1.1"
    assert redact_secret_ids(f"https://w.example/{sid}?x=1") == "https://w.example/01234567...?x=1"
    assert redact_secret_ids("GET /assets/style.css") == "GET /assets/style.css"
    # no trailing slash on the URL base, uppercase, percent-encoded neighbour
    assert redact_secret_ids(f"/s{sid}") == "/s01234567..."
    assert sid.upper() not in redact_secret_ids(f"/{sid.upper()}")
    assert sid not in redact_secret_ids(f"https://w.example%2F{sid}")


def test_max_failed_attempts_defaults_to_10(tmp_path):
    cfg = load_config(config_filenames=[_write(tmp_path, VALID_CONFIG)])
    assert cfg.max_failed_attempts == 10


def test_max_failed_attempts_can_be_set_or_turned_off(tmp_path):
    for value in (0, 3):
        cfg = load_config(config_text=VALID_CONFIG + f"max_failed_attempts: {value}\n")
        assert check_max_failed_attempts(cfg.max_failed_attempts) == value


@pytest.mark.parametrize("bad", [-1, "10", 2.5, True, None])
def test_max_failed_attempts_rejects_invalid_values(bad):
    with pytest.raises(ConfigError):
        check_max_failed_attempts(bad)


@pytest.mark.parametrize("key", [
    "'CHANGE_ME_TO_A_RANDOM_STRING_OF_32_OR_MORE_CHARACTERS'",  # the placeholder
    "''",
    "'   '",
    "12345678901234567890123456789012345",  # YAML reads this as a number
])
def test_secret_key_must_be_a_real_string(tmp_path, key):
    text = VALID_CONFIG.replace('"abcdefghijklmnopqrstuvwxyz_0123456"', key)
    with pytest.raises(ConfigError) as e:
        load_config(config_filenames=[_write(tmp_path, text)])
    assert e.value.config_key == "secret_key"


@pytest.mark.parametrize("given,expected", [
    ("/", "/"), ("''", "/"), ("/whisper", "/whisper/"), ("whisper/", "/whisper/"),
    ("/a/b/", "/a/b/"),
])
def test_app_url_base_gets_leading_and_trailing_slash(tmp_path, given, expected):
    text = VALID_CONFIG.replace("app_url_base: /", f"app_url_base: {given}")
    assert load_config(config_filenames=[_write(tmp_path, text)]).app_url_base == expected


def test_create_rate_limit_defaults_to_30_and_can_be_turned_off(tmp_path):
    assert load_config(config_filenames=[_write(tmp_path, VALID_CONFIG)]).create_rate_limit == 30
    off = load_config(config_filenames=[_write(tmp_path, VALID_CONFIG + "create_rate_limit: 0\n")])
    assert off.create_rate_limit == 0


@pytest.mark.parametrize("bad", ["-1", "'30'", "true", "1.5"])
def test_create_rate_limit_rejects_invalid_values(tmp_path, bad):
    with pytest.raises(ConfigError):
        load_config(config_filenames=[_write(tmp_path, VALID_CONFIG + f"create_rate_limit: {bad}\n")])
