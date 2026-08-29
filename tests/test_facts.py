from datetime import datetime

from deskd.skills.facts import try_datetime, try_math


def test_simple_addition():
    assert try_math("what is 247 + 31") == "That comes to 278."


def test_word_operators():
    assert try_math("what is 128 times 46") == "That comes to 5888."
    assert try_math("45 plus 66") == "That comes to 111."
    assert try_math("100 divided by 8") == "That comes to 12.5."


def test_precedence():
    assert try_math("2 plus 3 times 4") == "That comes to 14."


def test_percent_of():
    assert try_math("what is 15% of 240") == "That comes to 36."


def test_negative_and_float():
    assert try_math("-7 x 6") == "That comes to -42."
    out = try_math("10 / 4")
    assert out == "That comes to 2.5."


def test_non_math_ignored():
    assert try_math("what is love") is None
    assert try_math("tell me about coffee") is None


def test_garbage_expression_none():
    assert try_math("what is 5 banana split 3") is None


def test_time_question(now=None):
    now = datetime(2026, 8, 23, 21, 7)
    assert try_datetime("what time is it", now) == "It's 9:07 pm."


def test_day_questions():
    now = datetime(2026, 8, 23)
    assert try_datetime("what day is it", now) == "It's Sunday."
    assert try_datetime("what day is tomorrow", now) == "Tomorrow will be Monday, August 24."
    assert try_datetime("what was yesterday", now) == "Yesterday was Saturday, August 22."


def test_date_question():
    now = datetime(2026, 8, 23)
    assert try_datetime("what's the date today", now) == "Today is Sunday, August 23 2026."


def test_non_datetime_ignored():
    assert try_datetime("who is the president") is None
