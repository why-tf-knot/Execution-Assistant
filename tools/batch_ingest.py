"""Batch ingest selected repo files into the app's chunk store via HTTP API.

Usage: PYTHONPATH=src python tools/batch_ingest.py
"""
import requests
from pathlib import Path
import json

API = "http://127.0.0.1:8000/api/ingest-chunk"
ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "README.md",
    "build-package/prompts/checklist_generator_prompt.md",
    "build-package/prompts/requirements_agent_prompt.md",
    "build-package/schemas/project-plan.schema.json",
    "build-package/specs/starter-web-app-spec.md",
    "build-package/workflow/state-graph.json",
    "build-package/db/schema.sql",
    "src/mission_planner/planning_artifacts.py",
    "src/mission_planner/checklist_generator.py",
]

chunks = []
for p in FILES:
    f = ROOT / p
    if not f.exists():
        continue
    text = f.read_text(encoding="utf-8")
    doc_id = f.name
    # split into paragraph-sized chunks
    parts = [s.strip() for s in text.split('\n\n') if s.strip()]
    for i, part in enumerate(parts[:10]):  # limit to first 10 chunks per file
        chunk = {
            "id": f"{doc_id}-chunk-{i}",
            "doc_id": doc_id,
            "title": f.name,
            "section": f"part-{i}",
            "content": part,
            "metadata": {"source_path": str(f), "source_url": "", "phase_tags": [], "subsystem_tags": []},
        }
        chunks.append(chunk)

print(f"Prepared {len(chunks)} chunks to ingest")
for c in chunks:
    r = requests.post(API, json=c)
    if r.status_code == 200:
        print("ingested", c['id'])
    else:
        print("FAILED", c['id'], r.status_code, r.text)

print("Done")
