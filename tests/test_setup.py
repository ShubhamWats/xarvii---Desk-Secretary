import os
from pathlib import Path

from deskd.config import load_config, upsert_env_file
from deskd.setup import validate_gmail, validate_ics


def test_upsert_creates_and_sets_perms(tmp_path):
    env = tmp_path / "env"
    upsert_env_file(env, {"A_KEY": "1"})
    assert env.read_text().strip() == "A_KEY=1"
    assert os.stat(env).st_mode & 0o777 == 0o600


def test_upsert_replaces_only_target_key(tmp_path):
    env = tmp_path / "env"
    env.write_text("GEMINI_API_KEY=old\n# comment\nOTHER=x\n")
    upsert_env_file(env, {"GEMINI_API_KEY": "new"})
    text = env.read_text()
    assert "GEMINI_API_KEY=new" in text
    assert "GEMINI_API_KEY=old" not in text
    assert "# comment" in text
    assert "OTHER=x" in text


def test_upsert_appends_multiple(tmp_path):
    env = tmp_path / "env"
    upsert_env_file(env, {"K1": "a", "K2": "b"})
    text = env.read_text()
    assert "K1=a" in text and "K2=b" in text


def test_load_config_still_works_after_env_ops(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[gmail]\nuser = "me@gmail.com"\n')
    assert load_config(str(cfg)).gmail.user == "me@gmail.com"


def test_gmail_validator_shape():
    ok, msg = validate_gmail("not-an-email", "bad")
    assert ok is False and msg


def test_ics_validator_rejects_non_google():
    ok, msg = validate_ics("https://example.com/cal.ics")
    assert ok is False


def test_setup_bool_writer(tmp_path):
    from deskd.setup import _write_bools

    cfg = tmp_path / "config.toml"
    cfg.write_text("[wake_word]\nenabled = false\n")
    _write_bools(cfg, {"wake_word.enabled": True})
    assert "enabled = true" in cfg.read_text()
    _write_bools(cfg, {"telegram.enabled": False})
    body = cfg.read_text()
    assert "[telegram]" in body and "enabled = false" in body.split("[telegram]")[1]
