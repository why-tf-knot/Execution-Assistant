from pathlib import Path
import json
from typing import List, Optional, Dict

from mission_planner import vector_store
from pathlib import Path
import os
try:
    from mission_planner.vector_store_pg import PGVectorStore
except Exception:
    PGVectorStore = None

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SQL = ROOT / "build-package" / "db" / "migrations" / "001_create_vector_table.sql"

ROOT = Path(__file__).resolve().parents[2]
CHUNKS_FILE = ROOT / "build-package" / "db" / "document_chunks.json"


def _load_chunks() -> List[Dict]:
    if not CHUNKS_FILE.exists():
        return []
    with CHUNKS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def search_chunks(query: Optional[str] = None, phase_tags: Optional[List[str]] = None, subsystem_tags: Optional[List[str]] = None, top_k: int = 5) -> List[Dict]:
    """Retrieval that prefers vector search when a query is provided.

    Falls back to naive keyword/tag filtering over the seed chunk file when vector DB is empty.
    """
    # If a DATABASE_URL is set and PG connector is available, prefer PG vector search
    db_url = os.environ.get("DATABASE_URL")
    if db_url and PGVectorStore is not None:
        try:
            pg = PGVectorStore(db_url)
            # compute embedding for query using VectorStore's EmbeddingClient
            # reuse local sqlite embedding client as a quick fallback
            vs_local = vector_store.VectorStore()
            qemb = vs_local.ec.embed(query or "")
            results = pg.search_by_embedding(qemb, top_k=top_k)
            if results:
                return results
        except Exception:
            # fallback to sqlite/file-based search
            pass
    else:
        vs = vector_store.VectorStore()
        # If a query is given, try vector search first
        if query:
            try:
                results = vs.search_by_embedding(query, top_k=top_k)
                if results:
                    return results
            except Exception:
                # fallback to file-based search
                pass

    # simple fallback: file-based tag and token match
    chunks = _load_chunks()
    results = []
    for c in chunks:
        meta = c.get("metadata", {})
        # filter by phase tag if requested
        if phase_tags:
            chunk_phases = meta.get("phase_tags", []) or []
            if not any(pt in chunk_phases for pt in phase_tags):
                continue
        if subsystem_tags:
            chunk_subs = meta.get("subsystem_tags", []) or []
            if not any(st in chunk_subs for st in subsystem_tags):
                continue
        score = 0
        text = " ".join([c.get("title", ""), c.get("section", ""), c.get("content", "")]).lower()
        if query:
            for token in query.lower().split():
                if token in text:
                    score += 1
        results.append((score, c))

    results.sort(key=lambda x: (-x[0], x[1].get("doc_id", "")))
    top = [r[1] for r in results[:top_k]]
    return top
