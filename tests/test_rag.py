import pytest

from deskd.skills.rag import RagIndex


class FakeEmbedder:
    """Deterministic vectors: first word decides direction."""

    def embed(self, docs, batch_size=None):
        import math
        import zlib

        out = []
        for d in docs:
            v = [0.0] * 64
            for w in d.lower().split():
                v[zlib.crc32(w.encode()) % 64] = 1.0   # binary presence
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return iter(out)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "notes").mkdir(parents=True)
    (v / "notes" / "ai.md").write_text(
        "# AI\n\nI love neural networks and transformers.\nSecond line about GPT.")
    (v / "cooking.md").write_text("# Cooking\n\nPasta needs salt and garlic.")
    return v


def test_chunker_splits_on_heading_and_size():
    text = "# A\n" + "x" * 800 + "\n# B\nshort"
    chunks = list(RagIndex._chunks_of(text))
    assert len(chunks) >= 2
    assert any(h == "B" for h, _ in chunks)


def test_search_ranks_relevant_note(vault, tmp_path):
    idx = RagIndex(vault, tmp_path / "rag.sqlite")
    idx._embedder = FakeEmbedder()          # inject fake; skip model download
    n = idx.build_sync()
    assert n > 0
    hits = idx.search_sync("neural networks transformers")
    assert hits
    assert "ai.md" in hits[0]["file"]
    hits2 = idx.search_sync("pasta garlic")
    assert "cooking.md" in hits2[0]["file"]
