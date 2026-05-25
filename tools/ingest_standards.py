"""Ingest downloaded standards into the local VectorStore.

This script reads files from data/standards and chunks them before upserting
into the VectorStore used by the application.
"""
from pathlib import Path
from mission_planner.vector_store import VectorStore
import uuid
import json

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "standards"


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200):
    tokens = text.split()
    i = 0
    chunks = []
    while i < len(tokens):
        piece = " ".join(tokens[i : i + chunk_size])
        chunks.append(piece)
        i += chunk_size - overlap
    return chunks


def ingest_all():
    vs = VectorStore()
    for f in IN.glob("*.txt"):
        doc_id = f.stem
        text = f.read_text(encoding="utf-8")
        chunks = chunk_text(text, chunk_size=400, overlap=80)
        for idx, c in enumerate(chunks):
            chunk = {
                "id": f"{doc_id}-{idx}",
                "doc_id": doc_id,
                "title": f.name,
                "section": f"part-{idx}",
                "content": c,
                "metadata": {"source": str(f)},
            }
            vs.upsert_chunk(chunk)
        print(f"Ingested {len(chunks)} chunks from {f}")


if __name__ == "__main__":
    ingest_all()
