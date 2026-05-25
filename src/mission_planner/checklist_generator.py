from __future__ import annotations

from typing import Any, Dict, List, Optional
import json
from pathlib import Path

from .llm import get_default_llm
from . import retrieval

from .models import make_id, ChecklistItem
from .planning_artifacts import build_full_subsystem_set, phase_names, phase_review_gate


def _short_code(name: str) -> str:
    parts = [p for p in name.replace("/", " ").replace("-", " ").split() if p]
    if not parts:
        return "SYS"
    code = "".join(p[0] for p in parts[:3]).upper()
    return code[:4] or "SYS"


def _requirement_refs(requirements: Dict[str, Any], subsystem_name: str) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for bucket in ["mission", "system", "subsystem", "interfaces"]:
        for req in requirements.get(bucket, []) or []:
            if req.get("subsystem") in (subsystem_name, "System"):
                refs.append(req)
    return refs


def _objective_refs(project_profile: Dict[str, Any]) -> List[str]:
    return list(project_profile.get("objectives", []) or [])


def _source_refs(requirements: Dict[str, Any], subsystem_name: str) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for req in _requirement_refs(requirements, subsystem_name):
        for src in req.get("source_refs", []) or []:
            if src not in refs:
                refs.append(src)
    return refs


def _task_templates(domain: str) -> Dict[str, List[Dict[str, Any]]]:
    # Use the shared phase list and a deterministic set of tasks per phase.
    if domain == "space_mission":
        return {
            "Pre-Phase A": [
                {"phase": "Pre-Phase A", "suffix": "-001", "task": "Confirm mission need, mission class, and top-level success criteria", "purpose": "Establish credible mission need and feasibility bounds", "inputs": ["idea", "stakeholder needs", "constraints"], "dependencies": ["project intake complete"], "owner_role": "mission lead", "evidence_artifact": ["mission statement", "feasibility note"], "exit_criteria": ["mission need documented", "top risks identified"], "risk_if_skipped": "high"},
                {"phase": "Pre-Phase A", "suffix": "-002", "task": "Record initial assumptions and unknowns for concept study", "purpose": "Preserve decision context for later iteration", "inputs": ["intake profile"], "dependencies": ["mission need documented"], "owner_role": "systems engineer", "evidence_artifact": ["assumption log", "unknowns register"], "exit_criteria": ["assumptions captured", "unknowns assigned"], "risk_if_skipped": "medium"},
            ],
            "Phase A": [
                {"phase": "Phase A", "suffix": "-001", "task": "Finalize ConOps scenario, modes, and success/failure conditions", "purpose": "Support mission concept maturity and requirement derivation", "inputs": ["project profile", "stakeholder needs"], "dependencies": ["mission need documented"], "owner_role": "systems engineer", "evidence_artifact": ["ConOps", "mode table"], "exit_criteria": ["nominal and off-nominal modes defined", "success criteria traceable"], "risk_if_skipped": "high"},
                {"phase": "Phase A", "suffix": "-002", "task": "Baseline top-level mission requirements and validation approach", "purpose": "Establish the requirements baseline for SRR", "inputs": ["ConOps", "objective list"], "dependencies": ["ConOps approved"], "owner_role": "requirements lead", "evidence_artifact": ["requirements baseline", "validation matrix"], "exit_criteria": ["requirements traceable", "validation owners assigned"], "risk_if_skipped": "high"},
            ],
            "Phase B": [
                {"phase": "Phase B", "suffix": "-001", "task": "Close subsystem budgets and interface allocations", "purpose": "Prepare preliminary design package and integration boundaries", "inputs": ["ConOps", "requirements", "candidate architecture"], "dependencies": ["architecture selected"], "owner_role": "systems engineer", "evidence_artifact": ["budget package", "ICD draft"], "exit_criteria": ["budget margins captured", "interfaces allocated"], "risk_if_skipped": "high"},
                {"phase": "Phase B", "suffix": "-002", "task": "Produce subsystem verification plans and test ownership", "purpose": "Connect requirements to executable verification work", "inputs": ["requirements", "subsystem list"], "dependencies": ["requirements baseline"], "owner_role": "verification lead", "evidence_artifact": ["verification plan", "test ownership matrix"], "exit_criteria": ["every requirement has a method", "owners assigned"], "risk_if_skipped": "high"},
            ],
            "Phase C": [
                {"phase": "Phase C", "suffix": "-001", "task": "Freeze detailed subsystem designs and procurement packages", "purpose": "Support CDR readiness and build execution", "inputs": ["preliminary designs", "ICDs"], "dependencies": ["PDR complete"], "owner_role": "subsystem lead", "evidence_artifact": ["build package", "drawings"], "exit_criteria": ["design frozen", "build artifacts released"], "risk_if_skipped": "high"},
                {"phase": "Phase C", "suffix": "-002", "task": "Finalize supplier selection and order long-lead items", "purpose": "Ensure build schedule and procurement readiness", "inputs": ["procurement spec", "budget approval"], "dependencies": ["design frozen"], "owner_role": "procurement lead", "evidence_artifact": ["purchase orders", "supplier agreements"], "exit_criteria": ["POs issued", "lead times acknowledged"], "risk_if_skipped": "high"},
            ],
            "Phase D": [
                {"phase": "Phase D", "suffix": "-001", "task": "Execute integration and test procedures for subsystem acceptance", "purpose": "Demonstrate end-to-end readiness for operations", "inputs": ["build package", "test procedures"], "dependencies": ["hardware/software available"], "owner_role": "AIT lead", "evidence_artifact": ["test report", "anomaly log"], "exit_criteria": ["all critical tests executed", "open anomalies dispositioned"], "risk_if_skipped": "high"},
                {"phase": "Phase D", "suffix": "-002", "task": "Complete system-level regression and environmental tests", "purpose": "Verify full mission performance under expected environments", "inputs": ["system test plan", "environmental limits"], "dependencies": ["integration complete"], "owner_role": "test lead", "evidence_artifact": ["regression reports", "env test records"], "exit_criteria": ["regression passed", "no critical anomalies"], "risk_if_skipped": "high"},
            ],
            "Phase E": [
                {"phase": "Phase E", "suffix": "-001", "task": "Prepare operations readiness package and anomaly response playbooks", "purpose": "Ensure operational control and recovery paths are defined", "inputs": ["flight rules", "telemetry limits"], "dependencies": ["system validated"], "owner_role": "operations lead", "evidence_artifact": ["ORR package", "anomaly playbook"], "exit_criteria": ["operators trained", "response plans approved"], "risk_if_skipped": "high"},
                {"phase": "Phase E", "suffix": "-002", "task": "Perform launch/transfer readiness and mission commissioning rehearsals", "purpose": "Reduce launch/commissioning execution risk", "inputs": ["launch procedures", "ops playbook"], "dependencies": ["ORR complete"], "owner_role": "launch/operations lead", "evidence_artifact": ["rehearsal logs", "commissioning checklist"], "exit_criteria": ["rehearsals complete", "commissioning plan validated"], "risk_if_skipped": "high"},
            ],
            "Disposal/closeout": [
                {"phase": "Disposal/closeout", "suffix": "-001", "task": "Confirm disposal, deorbit, or end-of-life archive actions", "purpose": "Close mission responsibly and preserve data records", "inputs": ["end-of-life plan", "ops logs"], "dependencies": ["operations complete"], "owner_role": "mission manager", "evidence_artifact": ["closeout report", "archive index"], "exit_criteria": ["disposal executed", "data archived"], "risk_if_skipped": "medium"},
            ],
        }

    return {
        "Discover": [{"phase": "Discover", "suffix": "-001", "task": "Confirm product vision, user outcomes, and constraints", "purpose": "Set the initial scope and success definition", "inputs": ["idea", "stakeholder needs"], "dependencies": ["intake complete"], "owner_role": "product lead", "evidence_artifact": ["vision brief"], "exit_criteria": ["problem statement approved"], "risk_if_skipped": "high"}],
        "Define": [{"phase": "Define", "suffix": "-001", "task": "Baseline requirements and acceptance criteria", "purpose": "Establish the work to be executed and verified", "inputs": ["objectives", "ConOps or equivalent"], "dependencies": ["scope agreed"], "owner_role": "requirements lead", "evidence_artifact": ["requirements baseline"], "exit_criteria": ["requirements traceable"], "risk_if_skipped": "high"}],
        "Design": [{"phase": "Design", "suffix": "-001", "task": "Allocate budgets and interfaces across subsystems", "purpose": "Prepare for build and integration", "inputs": ["requirements", "architecture"], "dependencies": ["requirements baseline"], "owner_role": "systems engineer", "evidence_artifact": ["interface matrix"], "exit_criteria": ["allocations complete"], "risk_if_skipped": "high"}],
        "Build": [{"phase": "Build", "suffix": "-001", "task": "Release build packages and acceptance tests", "purpose": "Enable implementation with clear verification hooks", "inputs": ["design package", "test plan"], "dependencies": ["design frozen"], "owner_role": "build lead", "evidence_artifact": ["build package"], "exit_criteria": ["package released"], "risk_if_skipped": "high"}],
        "Launch": [{"phase": "Launch", "suffix": "-001", "task": "Confirm launch readiness and contingency procedures", "purpose": "Minimize launch-day execution risk", "inputs": ["launch criteria", "range interfaces"], "dependencies": ["integration complete"], "owner_role": "launch manager", "evidence_artifact": ["launch readiness package"], "exit_criteria": ["launch authority approval"], "risk_if_skipped": "high"}],
        "Operate": [{"phase": "Operate", "suffix": "-001", "task": "Prepare monitoring, support, and anomaly response procedures", "purpose": "Sustain service and detect issues quickly", "inputs": ["operational limits", "telemetry plan"], "dependencies": ["system validated"], "owner_role": "operations lead", "evidence_artifact": ["ops playbook"], "exit_criteria": ["operators trained"], "risk_if_skipped": "high"}],
        "Closeout": [{"phase": "Closeout", "suffix": "-001", "task": "Archive project records and complete end-of-life actions", "purpose": "Preserve traceability and finalize commitments", "inputs": ["closure plan", "project records"], "dependencies": ["operational closure"], "owner_role": "project manager", "evidence_artifact": ["closeout report"], "exit_criteria": ["records archived"], "risk_if_skipped": "medium"}],
    }


def generate_checklists(project_profile: Dict[str, Any], conops: Dict[str, Any], requirements: Dict[str, Any], subsystems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    domain = project_profile.get("domain", "other")
    phases = phase_names(domain)
    templates = _task_templates(domain)
    objectives = _objective_refs(project_profile)
    full_subsystems = build_full_subsystem_set(domain, subsystems)

    items: List[Dict[str, Any]] = []
    for phase in phases:
        phase_templates = templates.get(phase, [])
        for subsystem in full_subsystems or [{"name": "System", "drivers": [], "interfaces": [], "artifacts": []}]:
            subsystem_name = subsystem.get("name", "System")
            subsystem_code = _short_code(subsystem_name)
            related_requirements = _requirement_refs(requirements or {}, subsystem_name)
            requirement_ids = [r.get("id") for r in related_requirements if r.get("id")]
            source_refs = _source_refs(requirements or {}, subsystem_name)

            for template in phase_templates:
                # Build a compact phase abbreviation to avoid id collisions across phases
                phase_abbrev = ''.join([p[0] for p in phase.split()]).upper()
                item_id = f"{subsystem_code}-{phase_abbrev}-{template['suffix'].lstrip('-')}"
                item = {
                    "id": item_id,
                    "phase": template["phase"],
                    "subsystem": subsystem_name,
                    "task": template["task"],
                    "purpose": template["purpose"],
                    "inputs": list(template["inputs"]),
                    "dependencies": list(template["dependencies"]),
                    "owner_role": template["owner_role"],
                    "trace_to_objective": objectives[:2],
                    "trace_to_requirement": requirement_ids[:5],
                    "evidence_artifact": list(template["evidence_artifact"]),
                    "exit_criteria": list(template["exit_criteria"]),
                    "review_gate": phase_review_gate(domain, phase),
                    "risk_if_skipped": template["risk_if_skipped"],
                    "source_refs": source_refs,
                }
                # Slightly specialize task text when subsystem drivers are available.
                drivers = subsystem.get("drivers", []) or []
                if drivers and phase in {"Phase B", "Design", "Build"}:
                    item["task"] = f"{template['task']} for {subsystem_name} ({', '.join(drivers[:2])})"
                if phase == "Phase A" and subsystem_name != "System":
                    # keep phase A focused on system-level items; avoid too many subsystem duplicates
                    continue
                items.append(item)

    # Add a requirement-specific checklist item for every requirement, so the checklist covers the whole baseline.
    for bucket in ["mission", "system", "subsystem", "interfaces"]:
        for req in (requirements or {}).get(bucket, []) or []:
            req_id = req.get("id")
            subsystem_name = req.get("subsystem", "System")
            phase = req.get("phase") or ("Phase A" if bucket == "mission" else "Phase B")
            item = {
                "id": f"{_short_code(subsystem_name)}-{(req_id or make_id('REQ'))[-6:].upper()}",
                "phase": phase,
                "subsystem": subsystem_name,
                "task": f"Close the requirement implementation and verification plan for {req.get('statement')}",
                "purpose": "Connect requirement evidence to a concrete execution step",
                "inputs": [req.get("statement", ""), req.get("verification_method", "")],
                "dependencies": ["requirements baseline"],
                "owner_role": req.get("owner_role") or ("systems engineer" if subsystem_name == "System" else f"{subsystem_name} lead"),
                "trace_to_objective": req.get("trace_to_objective", []) or objectives,
                "trace_to_requirement": [req_id] if req_id else [],
                "evidence_artifact": ["review notes", "verification plan"],
                "exit_criteria": ["evidence identified", "owner assigned"],
                "review_gate": req.get("review_gate", phase_review_gate(domain, phase)),
                "risk_if_skipped": "high",
                "source_refs": req.get("source_refs", []) or [],
            }
            items.append(item)

    # De-duplicate by id while preserving order.
    seen = set()
    unique_items = []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        unique_items.append(item)
    return unique_items


def generate_checklists_via_llm(project_profile: Dict[str, Any], conops: Dict[str, Any], requirements: Dict[str, Any], subsystems: List[Dict[str, Any]], top_k: int = 4) -> List[Dict[str, Any]]:
    """Use the configured LLM to generate checklist items, grounded with retrieval results.

    Falls back to the deterministic generator on parse/validation failure.
    """
    prompt_path = Path(__file__).resolve().parents[2] / "build-package" / "prompts" / "checklist_generator_prompt.md"
    prompt_template = """
{instructions}

Project profile:
{profile}

Concept of Operations:
{conops}

Requirements:
{requirements}

Subsystems:
{subsystems}

Evidence (top retrieval hits per subsystem):
{evidence}

Produce a JSON array of checklist items following the required schema.
"""

    # gather retrieval evidence per subsystem
    evidence = {}
    for s in subsystems or []:
        name = s.get("name") or s.get("id") or "System"
        hits = retrieval.search_chunks(query=name, top_k=top_k)
        evidence[name] = [{"doc_id": h.get("id"), "title": h.get("title"), "snippet": h.get("content")[:400]} for h in hits]

    instructions = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "Generate checklist items as JSON array."
    prompt = prompt_template.format(instructions=instructions, profile=json.dumps(project_profile, indent=2), conops=json.dumps(conops, indent=2), requirements=json.dumps(requirements, indent=2), subsystems=json.dumps(subsystems, indent=2), evidence=json.dumps(evidence, indent=2))

    llm = get_default_llm()
    try:
        resp = llm.generate(prompt)
    except Exception:
        # If LLM call fails, fallback
        return generate_checklists(project_profile, conops, requirements, subsystems)

    # Try to parse JSON from the LLM's response
    try:
        # naive extraction: find the first '[' and last ']'
        start = resp.find('[')
        end = resp.rfind(']')
        if start != -1 and end != -1 and end > start:
            arr_text = resp[start:end+1]
            parsed = json.loads(arr_text)
            if isinstance(parsed, list):
                # post-process and validate parsed items
                def _normalize_source_refs(srcs):
                    out = []
                    for s in srcs or []:
                        if isinstance(s, dict):
                            doc_id = s.get('doc_id') or s.get('id') or ''
                            title = s.get('title') or s.get('name') or ''
                            locator = s.get('locator') or s.get('section') or ''
                            url = s.get('url') or s.get('link') or ''
                            out.append({'doc_id': doc_id, 'title': title, 'locator': locator, 'url': url})
                        else:
                            out.append({'doc_id': str(s), 'title': '', 'locator': '', 'url': ''})
                    return out

                def _postprocess_items(items):
                    repaired = []
                    seen_ids = set()
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        d = dict(it)
                        # ensure required keys exist
                        if not d.get('id'):
                            d['id'] = make_id('CHK')
                        d['phase'] = d.get('phase') or 'Phase B'
                        d['subsystem'] = d.get('subsystem') or 'System'
                        d['task'] = d.get('task') or 'TBD'
                        d['purpose'] = d.get('purpose') or ''
                        d['owner_role'] = d.get('owner_role') or 'owner'
                        d['review_gate'] = d.get('review_gate') or phase_review_gate(project_profile.get('domain','other'), d.get('phase'))
                        d['risk_if_skipped'] = d.get('risk_if_skipped') or 'medium'
                        # ensure list fields
                        for arr in ['inputs','dependencies','trace_to_objective','trace_to_requirement','evidence_artifact','exit_criteria']:
                            v = d.get(arr)
                            if v is None:
                                d[arr] = []
                            elif isinstance(v, str):
                                d[arr] = [v]
                            else:
                                d[arr] = list(v)
                        # normalize source_refs
                        d['source_refs'] = _normalize_source_refs(d.get('source_refs',[]) or [])

                        # Validate with Pydantic ChecklistItem; if invalid, attempt minimal repairs
                        try:
                            ci = ChecklistItem(**d)
                            dd = ci.model_dump() if hasattr(ci, 'model_dump') else ci.dict()
                        except Exception:
                            # attempt to coerce problematic fields into strings/lists
                            for k in ['task','purpose','owner_role']:
                                if k in d and not isinstance(d[k], str):
                                    d[k] = str(d[k])
                            for arr in ['inputs','dependencies','trace_to_objective','trace_to_requirement','evidence_artifact','exit_criteria']:
                                if arr in d and not isinstance(d[arr], list):
                                    d[arr] = [str(d[arr])]
                            try:
                                ci = ChecklistItem(**d)
                                dd = ci.model_dump() if hasattr(ci, 'model_dump') else ci.dict()
                            except Exception:
                                # give up on this item
                                continue

                        # deduplicate ids
                        if dd['id'] in seen_ids:
                            dd['id'] = make_id('CHK')
                        seen_ids.add(dd['id'])
                        repaired.append(dd)
                    return repaired

                repaired = _postprocess_items(parsed)
                # If LLM did not produce items for some phases, supplement from deterministic generator
                try:
                    domain = project_profile.get('domain','other')
                except Exception:
                    domain = 'other'
                phases_all = phase_names(domain)
                present_phases = {it.get('phase') for it in repaired}
                missing = [p for p in phases_all if p not in present_phases]
                if missing:
                    # generate deterministic items for the missing phases using templates
                    templates = _task_templates(domain)
                    full_subsystems = build_full_subsystem_set(domain, subsystems)
                    supplement = []
                    for phase in missing:
                        phase_templates = templates.get(phase, [])
                        for subsystem in full_subsystems or [{"name": "System", "drivers": [], "interfaces": [], "artifacts": []}]:
                            subsystem_name = subsystem.get("name", "System")
                            subsystem_code = _short_code(subsystem_name)
                            related_requirements = _requirement_refs(requirements or {}, subsystem_name)
                            requirement_ids = [r.get("id") for r in related_requirements if r.get("id")]
                            source_refs = _source_refs(requirements or {}, subsystem_name)
                            for template in phase_templates:
                                # Use the same compact phase abbreviation when supplementing LLM output
                                phase_abbrev = ''.join([p[0] for p in phase.split()]).upper()
                                item_id = f"{subsystem_code}-{phase_abbrev}-{template['suffix'].lstrip('-')}"
                                item = {
                                    "id": item_id,
                                    "phase": template["phase"],
                                    "subsystem": subsystem_name,
                                    "task": template["task"],
                                    "purpose": template["purpose"],
                                    "inputs": list(template["inputs"]),
                                    "dependencies": list(template["dependencies"]),
                                    "owner_role": template["owner_role"],
                                    "trace_to_objective": _objective_refs(project_profile)[:2],
                                    "trace_to_requirement": requirement_ids[:5],
                                    "evidence_artifact": list(template["evidence_artifact"]),
                                    "exit_criteria": list(template["exit_criteria"]),
                                    "review_gate": phase_review_gate(domain, phase),
                                    "risk_if_skipped": template["risk_if_skipped"],
                                    "source_refs": source_refs,
                                }
                                drivers = subsystem.get("drivers", []) or []
                                if drivers and phase in {"Phase B", "Design", "Build"}:
                                    item["task"] = f"{template['task']} for {subsystem_name} ({', '.join(drivers[:2])})"
                                supplement.append(item)
                    # postprocess supplement as well
                    supplement = _postprocess_items(supplement)
                    repaired.extend(supplement)
                if repaired:
                    # final dedupe by id preserving order
                    seen=set(); final=[]
                    for it in repaired:
                        if it['id'] in seen:
                            continue
                        seen.add(it['id']); final.append(it)
                    return final
                return parsed
    except Exception:
        pass

    # final fallback to deterministic generator
    return generate_checklists(project_profile, conops, requirements, subsystems)
