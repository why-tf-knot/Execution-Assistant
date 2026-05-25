import os
import json
import sqlite3
from typing import List, Dict, Optional
import math
import tenacity

try:
    import openai
except Exception:
    openai = None

DB_PATH = os.environ.get("EA_VECTOR_DB", "./build-package/db/vector_store.sqlite")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS document_chunks (
        id TEXT PRIMARY KEY,
        doc_id TEXT,
        title TEXT,
        section TEXT,
        content TEXT,
        metadata TEXT,
        embedding TEXT
    )
    """
    )
    conn.commit()
    conn.close()


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingClient:
    def __init__(self, api_key: Optional[str] = None, model: str = "text-embedding-3-small"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        if self.api_key and openai is not None:
            openai.api_key = self.api_key

    @tenacity.retry(wait=tenacity.wait_exponential(min=1, max=8), stop=tenacity.stop_after_attempt(3), reraise=True)
    def embed(self, text: str) -> List[float]:
        if not (self.api_key and openai is not None):
            # fallback: simple deterministic hashed vector
            h = [float(ord(c) % 10) for c in text[:256]]
            # pad/truncate to 128
            v = (h + [0.0] * 128)[:128]
            return v
        resp = openai.Embedding.create(model=self.model, input=text)
        if resp and resp.data and len(resp.data) > 0:
            return resp.data[0].embedding
        return []


class VectorStore:
    def __init__(self, embedding_client: Optional[EmbeddingClient] = None):
        init_db()
        self.ec = embedding_client or EmbeddingClient()

    def upsert_chunk(self, chunk: Dict[str, any]) -> None:
        conn = _connect()
        cur = conn.cursor()
        embedding = chunk.get("embedding")
        if not embedding:
            embedding = self.ec.embed(chunk.get("content", ""))
        cur.execute(
            "REPLACE INTO document_chunks (id, doc_id, title, section, content, metadata, embedding) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                chunk.get("id"),
                chunk.get("doc_id"),
                chunk.get("title"),
                chunk.get("section"),
                chunk.get("content"),
                json.dumps(chunk.get("metadata", {})),
                json.dumps(embedding),
            ),
        )
        conn.commit()
        conn.close()

    def search_by_embedding(self, query: str, top_k: int = 5) -> List[Dict]:
        qvec = self.ec.embed(query)
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM document_chunks")
        rows = cur.fetchall()
        scored = []
        for r in rows:
            emb = []
            try:
                emb = json.loads(r["embedding"]) if r["embedding"] else []
            except Exception:
                emb = []
            score = _cosine(qvec, emb)
            scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        results = []
        for s, r in scored[:top_k]:
            obj = {
                "id": r["id"],
                "doc_id": r["doc_id"],
                "title": r["title"],
                "section": r["section"],
                "content": r["content"],
                "metadata": json.loads(r["metadata"] or "{}"),
                "score": s,
            }
            results.append(obj)
        conn.close()
        return results
