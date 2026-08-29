from datetime import datetime, timedelta

from deskd.scheduler.reminders import ReminderStore, parse_when, parse_when_ex


def test_parse_in_minutes():
    now = datetime(2026, 8, 22, 17, 0)
    assert parse_when("in 30m", now) == now + timedelta(minutes=30)


def test_parse_in_hours_and_days():
    now = datetime(2026, 8, 22, 10, 0)
    assert parse_when("in 2 hours", now) == now + timedelta(hours=2)
    assert parse_when("in 1 day", now) == now + timedelta(days=1)
    assert parse_when("in 1 week", now) == now + timedelta(days=7)


def test_parse_at_time_today_or_tomorrow():
    now = datetime(2026, 8, 22, 10, 0)
    assert parse_when("at 17:30", now) == datetime(2026, 8, 22, 17, 30)
    assert parse_when("at 11pm", now) == datetime(2026, 8, 22, 23, 0)
    # 9am requested after 10am rolls to the next occurrence
    assert parse_when("at 9am", now) == datetime(2026, 8, 23, 9, 0)
    past = parse_when("at 08:00", now)
    assert past == datetime(2026, 8, 23, 8, 0)


def test_parse_tomorrow():
    now = datetime(2026, 8, 22, 20, 0)
    assert parse_when("tomorrow 9am", now) == datetime(2026, 8, 23, 9, 0)


def test_parse_iso():
    now = datetime(2026, 8, 22, 10, 0)
    assert parse_when("2026-08-22T18:00:00", now) == datetime(2026, 8, 22, 18, 0)


def test_parse_garbage_returns_none():
    assert parse_when("banana time", datetime(2026, 8, 22, 10, 0)) is None


def test_store_roundtrip(tmp_path):
    store = ReminderStore(tmp_path / "rem.json")
    due = datetime.now() + timedelta(hours=1)
    item = store.add("standup", due)
    again = ReminderStore(tmp_path / "rem.json")
    assert [i["id"] for i in again.list()] == [item["id"]]


def test_due_now_fires_once(tmp_path):
    store = ReminderStore(tmp_path / "rem.json")
    past = datetime.now() - timedelta(minutes=5)
    item = store.add("old", past)
    fired = store.due_now()
    assert [i["id"] for i in fired] == [item["id"]]
    assert store.due_now() == []


def test_parse_dot_time():
    now = datetime(2026, 8, 24, 0, 36)
    dt, span = parse_when_ex("remind me at 12.38 am", now)
    assert dt is not None and (dt.hour, dt.minute) == (0, 38)
    assert span is not None


def test_parse_compact_time():
    now = datetime(2026, 8, 24, 0, 36)
    dt, _ = parse_when_ex("to-do list at 1238 am", now)
    assert (dt.hour, dt.minute) == (0, 38)


def test_word_number_durations():
    now = datetime(2026, 8, 24, 0, 36)
    assert parse_when("in two minutes", now) == now + timedelta(minutes=2)
    assert parse_when("call mom after thirty minutes", now) == now + timedelta(minutes=30)
    assert parse_when("half an hour later check oven", now) == now + timedelta(minutes=30)
