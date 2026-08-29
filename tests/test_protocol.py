from deskd.protocol import FRAME_BYTES, decode, encode
from deskd.protocol import hello, welcome, state, ptt, abort, reminder_msg


def test_frame_bytes_is_20ms_of_16k_mono_s16():
    assert FRAME_BYTES == 16000 * 2 * 20 // 1000 == 640


def test_encode_decode_roundtrip():
    msg = reminder_msg("r1", "standup", "2026-08-22T17:30:00")
    assert decode(encode(msg)) == msg


def test_helpers_shape():
    assert hello("esp", "0.1")["type"] == "hello"
    assert welcome("deskd/0.1.0")["proto"] == 1
    assert state("speaking")["to"] == "speaking"
    assert ptt("down")["event"] == "down"
    assert abort("barge-in")["reason"] == "barge-in"


def test_decode_rejects_non_object():
    import pytest

    with pytest.raises(ValueError):
        decode("[1,2,3]")
