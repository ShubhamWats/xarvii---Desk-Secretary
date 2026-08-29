from deskd.config import BRAIN_KEYS, load_config, set_config_values


def test_setter_edits_existing_key(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[llm.tiers]\nfast = "ollama/qwen3:4b"\n\n[tts]\nengine = "piper"\n')
    set_config_values(str(cfg_file), {"llm.tiers.fast": "ollama/llama3.2:3b"})
    text = cfg_file.read_text()
    assert 'fast = "ollama/llama3.2:3b"' in text
    assert 'engine = "piper"' in text
    cfg = load_config(str(cfg_file))
    assert cfg.llm.tiers["fast"] == "ollama/llama3.2:3b"


def test_setter_appends_missing_section(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[tts]\nengine = \"none\"\n")
    set_config_values(str(cfg_file), {"llm.tiers.fast": "echo/test",
                                      "stt.engine": "faster-whisper"})
    text = cfg_file.read_text()
    assert '[llm.tiers]' in text
    assert '[stt]' in text
    assert 'engine = "faster-whisper"' in text
    cfg = load_config(str(cfg_file))
    assert cfg.stt.engine == "faster-whisper"
    assert cfg.llm.tiers["fast"] == "echo/test"


def test_setter_creates_file(tmp_path):
    cfg_file = tmp_path / "sub" / "config.toml"
    set_config_values(str(cfg_file), {"tts.engine": "none"})
    assert cfg_file.is_file()
    assert load_config(str(cfg_file)).tts.engine == "none"


def test_known_brain_keys_shape():
    assert all("." in k for k in BRAIN_KEYS)
