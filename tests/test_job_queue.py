import time

from fastapi.testclient import TestClient

from mission_planner.job_queue import JobQueue
import mission_planner.main as main_mod


def test_job_queue_reuses_same_fingerprint(tmp_path):
    queue = JobQueue(tmp_path)

    def handler():
        return {"ok": True}

    first = queue.submit("generate-plan", {"project_id": "p1"}, handler, project_id="p1")
    second = queue.submit("generate-plan", {"project_id": "p1"}, handler, project_id="p1")

    assert first["id"] == second["id"]

    deadline = time.time() + 5
    while time.time() < deadline:
        job = queue.load(first["id"])
        if job and job["status"] == "succeeded":
            assert job["result"] == {"ok": True}
            break
        time.sleep(0.05)
    else:
        raise AssertionError("job did not complete in time")


def test_async_plan_and_checklist_jobs(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    exports_dir = tmp_path / "exports"
    projects_dir.mkdir()
    exports_dir.mkdir()

    monkeypatch.setattr(main_mod, "DATA_DIR", projects_dir)
    monkeypatch.setattr(main_mod, "EXPORT_DIR", exports_dir)
    monkeypatch.setattr(main_mod, "JOB_QUEUE", JobQueue(tmp_path))

    client = TestClient(main_mod.app)

    created = client.post("/api/projects", json={"idea": "A small lunar mapping mission"})
    assert created.status_code == 200
    project_id = created.json()["project_id"]

    plan_job = client.post(f"/api/projects/{project_id}/generate-plan?async_job=true", json={})
    assert plan_job.status_code == 202
    plan_job_id = plan_job.json()["job_id"]

    deadline = time.time() + 5
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{plan_job_id}")
        assert job.status_code == 200
        body = job.json()
        if body["status"] == "succeeded":
            assert "checklists" in body["result"]
            break
        time.sleep(0.05)
    else:
        raise AssertionError("plan job did not complete in time")

    checklist_job = client.post(f"/api/projects/{project_id}/generate-checklists?async_job=true")
    assert checklist_job.status_code == 202
    checklist_job_id = checklist_job.json()["job_id"]

    deadline = time.time() + 5
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{checklist_job_id}")
        assert job.status_code == 200
        body = job.json()
        if body["status"] == "succeeded":
            assert "checklists" in body["result"]
            break
        time.sleep(0.05)
    else:
        raise AssertionError("checklist job did not complete in time")
