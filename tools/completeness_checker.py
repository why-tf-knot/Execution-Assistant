"""Completeness checker for project plans.

Usage: PYTHONPATH=src python tools/completeness_checker.py <project_id>
"""
import sys
import json
from pathlib import Path
from mission_planner import main
from mission_planner.planning_artifacts import phase_names

if len(sys.argv) < 2:
    print("Usage: python tools/completeness_checker.py <project_id>")
    raise SystemExit(1)

project_id = sys.argv[1]
state = main._load_latest(project_id)
if state is None:
    print("Project not found", project_id)
    raise SystemExit(1)
plan = state.get("plan") or {}
profile = plan.get("project_profile") or {}
domain = profile.get("domain","other")
requirements = plan.get("requirements") or {"mission":[],"system":[],"subsystem":[],"interfaces":[]}
checklists = plan.get("checklists") or []
subsystems = [s.get("name") for s in plan.get("subsystems", []) or []]

report = {"project_id": project_id, "issues": [], "summary": {}}

# 1) Ensure every requirement is referenced by at least one checklist item
reqs = []
for bucket in ["mission","system","subsystem","interfaces"]:
    for r in (requirements.get(bucket,[]) or []):
        reqs.append(r)
missing_req_refs = []
for r in reqs:
    rid = r.get("id")
    found = any(rid in (it.get("trace_to_requirement") or []) for it in checklists)
    if not found:
        missing_req_refs.append(rid)
if missing_req_refs:
    report["issues"].append({"type":"missing_requirement_trace","count":len(missing_req_refs),"ids":missing_req_refs})

# 2) Ensure every objective is traced by at least one requirement
objectives = profile.get("objectives",[]) or []
obj_missing = []
for obj in objectives:
    found = any(obj in (r.get("trace_to_objective") or []) for r in reqs)
    if not found:
        obj_missing.append(obj)
if obj_missing:
    report["issues"].append({"type":"untraced_objective","count":len(obj_missing),"objectives":obj_missing})

# 3) Ensure each subsystem has at least one checklist item
subsys_missing = []
for s in subsystems:
    found = any(it.get("subsystem")==s for it in checklists)
    if not found:
        subsys_missing.append(s)
if subsys_missing:
    report["issues"].append({"type":"missing_subsystem_checklists","count":len(subsys_missing),"subsystems":subsys_missing})

# 4) Phase coverage: at least one checklist per phase
phases = phase_names(domain)
phase_missing = []
for ph in phases:
    found = any(it.get("phase")==ph for it in checklists)
    if not found:
        phase_missing.append(ph)
if phase_missing:
    report["issues"].append({"type":"missing_phase_checklists","count":len(phase_missing),"phases":phase_missing})

# 5) Basic counts
report['summary']['requirements_count'] = len(reqs)
report['summary']['checklist_count'] = len(checklists)
report['summary']['objectives_count'] = len(objectives)
report['summary']['subsystems_count'] = len(subsystems)

out_file = Path("build-package/exports") / f"completeness_report_{project_id}.json"
out_file.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
print('Wrote', out_file)
