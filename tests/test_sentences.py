from deskd.textsplit import SentenceSplitter


def feed_all(splitter, text):
    out = []
    for ch in text:
        out.extend(splitter.feed(ch))
    return out + splitter.flush()


def test_basic_sentence_boundaries():
    s = SentenceSplitter(min_len=5)
    parts = feed_all(s, "Hello there! How are you? I am fine.")
    assert len(parts) >= 3
    assert "".join(parts).replace("\n", " ").strip().startswith("Hello")


def test_short_fragments_held_until_flush():
    s = SentenceSplitter(min_len=50)
    assert s.feed("Hi. Ok.") == []
    assert s.flush() == ["Hi. Ok."]


def test_newline_forces_split():
    s = SentenceSplitter(min_len=100)
    parts = feed_all(s, "First line\nSecond line")
    assert parts[0].strip() == "First line"


def test_no_premature_flush_mid_word():
    s = SentenceSplitter(min_len=12)
    assert s.feed("Wait for it") == []
    assert len(s.buf) > 0
