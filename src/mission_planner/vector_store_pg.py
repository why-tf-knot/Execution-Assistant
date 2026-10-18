import os
import json
from typing import List, Dict, Optional

try:
    import psycopg
    from pgvector.psycopg import register_vector, Vector
except Exception:
    psycopg = None
    register_vector = None
    Vector = None

DB_URL = os.environ.get("DATABASE_URL")
EMBED_DIM = int(os.environ.get("EA_EMBED_DIM", "1536"))


class PGVectorStore:
    """Postgres + pgvector connector.

    Requires `DATABASE_URL` env var pointing to a Postgres instance with the pgvector extension available.
    """

    def __init__(self, db_url: Optional[str] = None):
        if psycopg is None or register_vector is None or Vector is None:
            raise RuntimeError("psycopg or pgvector not installed; please install psycopg[binary] and pgvector")
        self.db_url = db_url or DB_URL
        if not self.db_url:
            raise RuntimeError("DATABASE_URL is not set")
        # Connect and register vector adapter
        self.conn = psycopg.connect(self.db_url)
        register_vector(self.conn)

    def init_db(self):
        with self.conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(f"CREATE TABLE IF NOT EXISTS document_chunks_pg (id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, title TEXT NOT NULL, section TEXT, content TEXT NOT NULL, metadata JSONB, embedding vector({EMBED_DIM}));")
            # create ivfflat index if not exists (note: requires REINDEX or ANALYZE after bulk load)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding ON document_chunks_pg USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);")
        self.conn.commit()

    def upsert_chunk(self, chunk: Dict[str, any]):
        emb = chunk.get("embedding")
        if emb is None:
            raise RuntimeError("embedding required for PG upsert; compute embedding before upsert")
        vec = Vector(emb)
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_chunks_pg (id, doc_id, title, section, content, metadata, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET doc_id = EXCLUDED.doc_id, title = EXCLUDED.title, section = EXCLUDED.section, content = EXCLUDED.content, metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding;",
                (chunk.get("id"), chunk.get("doc_id"), chunk.get("title"), chunk.get("section"), chunk.get("content"), json.dumps(chunk.get("metadata", {})), vec),
            )
        self.conn.commit()

    def search_by_embedding(self, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
        vec = Vector(query_embedding)
        with self.conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                "SELECT id, doc_id, title, section, content, metadata, (embedding <-> %s) AS distance FROM document_chunks_pg ORDER BY distance ASC LIMIT %s;",
                (vec, top_k),
            )
            rows = cur.fetchall()
        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "doc_id": r["doc_id"],
                "title": r["title"],
                "section": r["section"],
                "content": r["content"],
                "metadata": r["metadata"],
                "distance": r["distance"],
            })
        return results
