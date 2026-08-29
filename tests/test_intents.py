from datetime import datetime, timedelta

from deskd.conversation import (_fix_transcription, _split_list_items,
                                _try_reminder_intent)


def test_exact_failed_sentence_1():
    title, due, unclear = _try_reminder_intent(
        "Okay then remind me at 12.38 am, two minutes later that is.")
    assert not unclear and due is not None


def test_exact_failed_sentence_2():
    t = _fix_transcription("You have to remind me of my 2D list at 1238 AM.")
    assert "to-do list" in t
    title, due, unclear = _try_reminder_intent(t)
    assert not unclear and due is not None
    assert "list" in title.lower()


def test_plain_title_case():
    title, due, unclear = _try_reminder_intent("remind me to drink water in 30 minutes")
    assert title == "drink water"
    assert due is not None and not unclear


def test_no_time_is_chat():
    assert _try_reminder_intent("can you remind me these things when I ask you") is None


def test_unclear_time_flags_clarification():
    title, due, unclear = _try_reminder_intent("remind me at banana o'clock")
    assert unclear or due is None


def test_transcription_fixups():
    assert _fix_transcription("my 2D list") == "my to-do list"


def test_list_splitting():
    items = _split_list_items(
        "I want to make a to do list for today. study maths, physics and chemistry")
    assert any("maths" in i.lower() for i in items)
    assert any("physics" in i.lower() for i in items)
    assert any("chemistry" in i.lower() for i in items)


def test_sweep_expires_old_lines(tmp_path):
    from deskd.integrations.obsidian import ObsidianVault

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    old_date = (datetime.now() - timedelta(days=9)).strftime("%Y-%m-%d %H:%M")
    new_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    note = vault_dir / "Inbox.md"
    note.write_text(
        f"- [ ] old task  `[{old_date}]`\n"
        f"- [ ] fresh task  `[{new_date}]`\n"
        "- [ ] undated stays\n")
    v = ObsidianVault(vault_dir)
    removed = v.sweep_expired_inbox(max_age_days=7)
    body = note.read_text()
    assert removed == 1
    assert "old task" not in body
    assert "fresh task" in body
    assert "undated" in body
