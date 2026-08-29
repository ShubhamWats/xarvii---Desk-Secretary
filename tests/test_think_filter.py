from deskd.textsplit import ThinkFilter


def feed_chars(f, text):
    return "".join(f.feed(ch) for ch in text) + f.flush()


def test_passthrough_without_think():
    assert feed_chars(ThinkFilter(), "hello world") == "hello world"


def test_simple_block_suppressed():
    out = feed_chars(ThinkFilter(), "<think>reasoning here</think>Visible answer.")
    assert out == "Visible answer."


def test_partial_tags_across_deltas():
    f = ThinkFilter()
    parts = ["<thi", "nk>secret</thi", "nk>ok"]
    out = "".join(f.feed(p) for p in parts) + f.flush()
    assert out == "ok"


def test_multiple_blocks():
    out = feed_chars(ThinkFilter(), "<think>a</think>X<think>b</think>Y")
    assert out == "XY"


def test_unclosed_block_suppressed_to_end():
    out = feed_chars(ThinkFilter(), "Hi <think>never closed")
    assert out == "Hi "


def test_word_split_across_boundary():
    f = ThinkFilter()
    out = f.feed("Hel") + f.feed("lo <think>x</think>!")
    out += f.flush()
    assert out == "Hello !"
