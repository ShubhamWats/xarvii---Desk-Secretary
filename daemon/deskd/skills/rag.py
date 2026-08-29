"""Obsidian RAG memory: local embeddings (fastembed) + SQLite. Private, offline."""

import asyncio
import logging
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("deskd.rag")

_CHUNK = 700
_OVERLAP = 100


class RagIndex:
    def __init__(self, vault: Path, db_path: Path,
                 model: str = "BAAI/bge-small-en-v1.5", top_k: int = 4):
        self.vault = Path(vault).expanduser()
        self.db = Path(db_path)
        self.model_name = model
        self.top_k = top_k
        self._embedder = None
        self._lock = asyncio.Lock()
        self.last_built = 0.0

    def _ensure(self):
        if self._embedder is None:
            from fastembed import TextEmbedding

            log.info("loading embedding model %s …", self.model_name)
            self._embedder = TextEmbedding(model_name=self.model_name)

    def _conn(self) -> sqlite3.Connection:
        self.db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks("
            "id INTEGER PRIMARY KEY, file TEXT, heading TEXT, body TEXT,"
            "mtime REAL, dim INTEGER, vec BLOB)")
        return conn

    # ------------------------------------------------------------- chunking

    @staticmethod
    def _chunks_of(text: str):
        lines, heading, buf = text.splitlines(), "(top)", []
        cur_len = 0
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                if buf:
                    body = "\n".join(buf).strip()
                    if body:
                        yield heading, body
                heading, buf, cur_len = (stripped.lstrip("#").strip() or "(top)",
                                         [], 0)
                continue
            buf.append(line)
            cur_len += len(line)
            while cur_len >= _CHUNK:
                yield heading, "\n".join(buf).strip()
                buf, cur_len = [], 0
        tail = "\n".join(buf).strip()
        if tail:
            yield heading, tail

    # -------------------------------------------------------------- indexing

    def build_sync(self) -> int:
        import numpy as np

        self._ensure()
        files = [p for p in self.vault.rglob("*.md")
                 if ".obsidian" not in p.parts and ".trash" not in p.parts]
        docs, meta = [], []
        mtimes = {}
        for p in files:
            try:
                text = p.read_text(errors="replace")
                mtime = p.stat().st_mtime
            except OSError:
                continue
            mtimes[str(p.relative_to(self.vault))] = mtime
            for heading, body in self._chunks_of(text):
                if len(body.strip()) < 15:
                    continue
                rel = str(p.relative_to(self.vault))
                docs.append(f"{rel}\n{heading}\n{body}")
                meta.append((rel, heading, body[:1500], mtime))
        if not docs:
            return 0
        vectors = list(self._embedder.embed(docs, batch_size=32))

        conn = self._conn()
        with conn:
            conn.execute("DELETE FROM chunks")
            conn.executemany(
                "INSERT INTO chunks(file,heading,body,mtime,dim,vec) "
                "VALUES(?,?,?,?,?,?)",
                [(f, h, b, m, len(v), np.asarray(v, dtype=np.float32).tobytes())
                 for (f, h, b, m), v in zip(meta, vectors)])
        conn.close()
        self.last_built = time.time()
        log.info("rag index built: %d chunks from %d notes", len(docs), len(files))
        return len(docs)

    async def rebuild_if_stale(self, max_age_s: float):
        if time.time() - self.last_built < max_age_s:
            return None
        async with self._lock:
            if time.time() - self.last_built < max_age_s:
                return None
            return await asyncio.to_thread(self.build_sync)

    # --------------------------------------------------------------- search

    def search_sync(self, query: str, k: int | None = None) -> list[dict]:
        import numpy as np

        self._ensure()
        k = k or self.top_k
        qvec = next(iter(self._embedder.embed([query])))
        conn = self._conn()
        rows = conn.execute(
            "SELECT file,heading,body,vec FROM chunks WHERE dim=?",
            (len(qvec),)).fetchall()
        conn.close()
        if not rows:
            return []
        q = np.asarray(qvec, dtype=np.float32)
        scored = []
        for f, h, b, blob in rows:
            v = np.frombuffer(blob, dtype=np.float32)
            denom = (np.linalg.norm(q) * np.linalg.norm(v)) or 1.0
            scored.append((float(np.dot(q, v) / denom), f, h, b))
        scored.sort(reverse=True)
        return [{"file": f, "heading": h, "body": b,
                 "score": round(s, 3)} for s, f, h, b in scored[:k]]
