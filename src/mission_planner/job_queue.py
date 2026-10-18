from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable, Optional
from uuid import uuid4
import hashlib
import json
import time


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str
    created_at: float
    updated_at: float
    payload_fingerprint: str
    payload: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    project_id: Optional[str] = None


class JobQueue:
    """Small persistent job store with background thread execution.

    This is intentionally simple: it gives the API an async execution path,
    durable job state, and idempotent reuse for identical requests.
    """

    def __init__(self, root_dir: Path):
        self.jobs_dir = root_dir / "build-package" / "db" / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._fingerprints_path = self.jobs_dir / "fingerprints.json"
        self._fingerprints: dict[str, str] = self._load_fingerprints()

    def _load_fingerprints(self) -> dict[str, str]:
        if not self._fingerprints_path.exists():
            return {}
        try:
            return json.loads(self._fingerprints_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_fingerprints(self) -> None:
        self._fingerprints_path.write_text(json.dumps(self._fingerprints, indent=2, sort_keys=True), encoding="utf-8")

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(json.dumps(payload, sort_keys=True, default=str))
        except Exception:
            return {"repr": repr(payload)}

    def fingerprint(self, kind: str, payload: dict[str, Any], idempotency_key: Optional[str] = None) -> str:
        normalized = self._normalize_payload(payload)
        envelope = {"kind": kind, "payload": normalized, "idempotency_key": idempotency_key or ""}
        digest = hashlib.sha256(json.dumps(envelope, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        return digest

    def load(self, job_id: str) -> Optional[dict[str, Any]]:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save(self, job: dict[str, Any]) -> dict[str, Any]:
        job["updated_at"] = time.time()
        self._job_path(job["id"]).write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
        return job

    def get_by_fingerprint(self, fingerprint: str) -> Optional[dict[str, Any]]:
        job_id = self._fingerprints.get(fingerprint)
        if not job_id:
            return None
        return self.load(job_id)

    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        handler: Callable[[], dict[str, Any]],
        project_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        fingerprint = self.fingerprint(kind, payload, idempotency_key=idempotency_key)
        with self._lock:
            existing = self.get_by_fingerprint(fingerprint)
            if existing and existing.get("status") in {"queued", "running", "succeeded"}:
                return existing

            job = JobRecord(
                id=uuid4().hex,
                kind=kind,
                status="queued",
                created_at=time.time(),
                updated_at=time.time(),
                payload_fingerprint=fingerprint,
                payload=self._normalize_payload(payload),
                project_id=project_id,
            )
            job_dict = asdict(job)
            self._fingerprints[fingerprint] = job.id
            self._save_fingerprints()
            self.save(job_dict)

        thread = Thread(target=self._run, args=(job.id, handler), daemon=True)
        thread.start()
        return job_dict

    def _run(self, job_id: str, handler: Callable[[], dict[str, Any]]) -> None:
        job = self.load(job_id)
        if not job:
            return
        job["status"] = "running"
        self.save(job)
        try:
            result = handler()
            job["status"] = "succeeded"
            job["result"] = result
            job["error"] = None
        except Exception as exc:  # pragma: no cover - safety path
            job["status"] = "failed"
            job["error"] = repr(exc)
        self.save(job)
