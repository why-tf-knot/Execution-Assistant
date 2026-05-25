from __future__ import annotations

import math
import re
from typing import Any, Dict, List


SPACE_MISSION_SUBSYSTEMS: List[Dict[str, Any]] = [
    {"name": "Systems engineering and mission design", "drivers": ["requirements traceability", "mission trades"], "artifacts": ["ConOps", "requirements baseline", "trade matrix"], "owner_role": "systems engineer"},
    {"name": "Payload", "drivers": ["science/data product", "instrument accommodation"], "artifacts": ["payload specification", "payload ICD"], "owner_role": "payload lead"},
    {"name": "Structures and mechanisms", "drivers": ["launch loads", "deployment mechanisms"], "artifacts": ["structural analysis", "mechanism drawings"], "owner_role": "structures lead"},
    {"name": "Thermal", "drivers": ["survival margins", "operational temperature"], "artifacts": ["thermal model", "heater plan"], "owner_role": "thermal engineer"},
    {"name": "Electrical Power System", "drivers": ["power budget", "battery sizing"], "artifacts": ["power budget", "EPS analysis"], "owner_role": "EPS lead"},
    {"name": "C&DH and avionics", "drivers": ["data handling", "bus interfaces"], "artifacts": ["avionics architecture", "data budget"], "owner_role": "avionics lead"},
    {"name": "Communications and RF", "drivers": ["link budget", "ground network"], "artifacts": ["link budget", "RF ICD"], "owner_role": "communications lead"},
    {"name": "GNC / AOCS", "drivers": ["pointing accuracy", "navigation performance"], "artifacts": ["GN&C analysis", "attitude budget"], "owner_role": "GNC lead"},
    {"name": "Flight software and autonomy", "drivers": ["mode logic", "fault management"], "artifacts": ["software architecture", "state machine"], "owner_role": "software lead"},
    {"name": "Radiation and EEE parts assurance", "drivers": ["environment", "part criticality"], "artifacts": ["parts list", "radiation evidence matrix"], "owner_role": "parts and radiation engineer"},
    {"name": "Propulsion", "drivers": ["delta-v", "propellant margin"], "artifacts": ["propulsion sizing", "thruster ICD"], "owner_role": "propulsion lead"},
    {"name": "Ground segment", "drivers": ["operations tooling", "data receipt"], "artifacts": ["ground architecture", "ops tools list"], "owner_role": "ground systems lead"},
    {"name": "Mission operations", "drivers": ["procedures", "anomaly response"], "artifacts": ["ops concept", "flight rules"], "owner_role": "operations lead"},
    {"name": "Integration, assembly, and test", "drivers": ["test coverage", "verification flow"], "artifacts": ["AIT flow", "test procedures"], "owner_role": "AIT lead"},
    {"name": "Safety, quality, reliability, and configuration management", "drivers": ["hazard control", "change control"], "artifacts": ["safety plan", "CM plan"], "owner_role": "safety/quality lead"},
    {"name": "Legal, licensing, policy, and registration", "drivers": ["regulatory compliance", "mission approvals"], "artifacts": ["compliance register", "license tracker"], "owner_role": "legal/policy lead"},
    {"name": "Debris, disposal, and sustainability", "drivers": ["end-of-life plan", "debris mitigation"], "artifacts": ["disposal plan", "debris mitigation report"], "owner_role": "sustainability lead"},
]


GENERIC_BUSINESS_SUBSYSTEMS: List[Dict[str, Any]] = [
    {"name": "Product strategy", "drivers": ["market fit", "scope discipline"], "artifacts": ["strategy brief"], "owner_role": "product lead"},
    {"name": "Customer and user research", "drivers": ["needs discovery", "persona validation"], "artifacts": ["research notes"], "owner_role": "research lead"},
    {"name": "Solution architecture", "drivers": ["capability fit", "implementation risk"], "artifacts": ["architecture brief"], "owner_role": "architect"},
    {"name": "Engineering delivery", "drivers": ["build throughput", "quality"], "artifacts": ["delivery plan"], "owner_role": "engineering lead"},
    {"name": "Go-to-market and growth", "drivers": ["launch readiness", "adoption"], "artifacts": ["GTM plan"], "owner_role": "growth lead"},
    {"name": "Operations and support", "drivers": ["service reliability", "response times"], "artifacts": ["ops playbook"], "owner_role": "operations lead"},
    {"name": "Finance and planning", "drivers": ["budget control", "runway"], "artifacts": ["budget model"], "owner_role": "finance lead"},
    {"name": "Legal and compliance", "drivers": ["contracts", "regulatory obligations"], "artifacts": ["compliance checklist"], "owner_role": "legal lead"},
]


SPACE_PHASE_WEIGHTS = [2, 4, 6, 8, 8, 6, 2]
GENERIC_PHASE_WEIGHTS = [2, 3, 5, 6, 3, 3, 1]


def parse_schedule_months(schedule_text: str | None, default_months: int = 18) -> int:
    if not schedule_text:
        return default_months
    text = schedule_text.lower()
    if "year" in text:
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if match:
            return max(1, int(round(float(match.group(1)) * 12)))
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        return max(1, int(round(float(match.group(1)))))
    return default_months


def subsystem_library(domain: str) -> List[Dict[str, Any]]:
    return SPACE_MISSION_SUBSYSTEMS if domain == "space_mission" else GENERIC_BUSINESS_SUBSYSTEMS


def phase_names(domain: str) -> List[str]:
    if domain == "space_mission":
        return ["Pre-Phase A", "Phase A", "Phase B", "Phase C", "Phase D", "Phase E", "Disposal/closeout"]
    return ["Discover", "Define", "Design", "Build", "Launch", "Operate", "Closeout"]


def phase_weights(domain: str) -> List[int]:
    return SPACE_PHASE_WEIGHTS if domain == "space_mission" else GENERIC_PHASE_WEIGHTS


def phase_review_gate(domain: str, phase: str) -> str:
    mapping = {
        "Pre-Phase A": "MCR",
        "Phase A": "SRR",
        "Phase B": "PDR",
        "Phase C": "CDR",
        "Phase D": "TRR",
        "Phase E": "ORR",
        "Disposal/closeout": "FRR",
        "Discover": "MCR",
        "Define": "SRR",
        "Design": "PDR",
        "Build": "CDR",
        "Launch": "FRR",
        "Operate": "ORR",
        "Closeout": "LRR",
    }
    return mapping.get(phase, "PDR")


def _phase_duration_allocation(total_months: int, weights: List[int]) -> List[int]:
    total_weight = sum(weights) or 1
    raw = [total_months * (w / total_weight) for w in weights]
    durations = [max(1, int(math.floor(v))) for v in raw]
    remainder = total_months - sum(durations)
    fractions = sorted(((raw[i] - math.floor(raw[i]), i) for i in range(len(raw))), reverse=True)
    idx = 0
    while remainder > 0 and idx < len(fractions):
        durations[fractions[idx][1]] += 1
        remainder -= 1
        idx += 1
    # If rounding pushed us over, trim from the longest phases, never below 1.
    while remainder < 0:
        target = max(range(len(durations)), key=lambda i: durations[i])
        if durations[target] > 1:
            durations[target] -= 1
            remainder += 1
        else:
            break
    return durations


def build_timeline(project_profile: Dict[str, Any], domain: str, months_total: int) -> List[Dict[str, Any]]:
    names = phase_names(domain)
    weights = phase_weights(domain)
    durations = _phase_duration_allocation(months_total, weights)
    phases: List[Dict[str, Any]] = []
    cursor = 1
    for idx, name in enumerate(names):
        duration = durations[idx]
        start = cursor
        end = cursor + duration - 1
        cursor = end + 1
        if name == names[-1] and end < months_total:
            end = months_total
            duration = end - start + 1
        phases.append(
            {
                "name": name,
                "start_month": start,
                "end_month": end,
                "duration_months": duration,
                "entry_conditions": [],
                "exit_conditions": [],
                "deliverables": [],
                "review_gates": [phase_review_gate(domain, name)],
                "focus": "mission execution" if domain == "space_mission" else "venture execution",
            }
        )
    return phases


def build_business_plan(project_profile: Dict[str, Any], conops: Dict[str, Any], architectures: List[Dict[str, Any]], requirements: Dict[str, Any], subsystems: List[Dict[str, Any]], months_total: int) -> Dict[str, Any]:
    objective_summary = list(project_profile.get("objectives", []) or [])
    selected_arch = next((a for a in architectures if a.get("selected")), architectures[0] if architectures else None)
    risk_refs = [
        req.get("statement")
        for bucket in ["mission", "system", "subsystem", "interfaces"]
        for req in (requirements.get(bucket, []) or [])[:2]
        if req.get("statement")
    ]
    if not risk_refs:
        risk_refs = [s.get("name") for s in subsystems[:3] if s.get("name")]
    cost_buckets = [
        {"name": "mission design and systems engineering", "share": 12, "drivers": ["traceability", "reviews"]},
        {"name": "product/payload development", "share": 18, "drivers": ["payload complexity", "test burden"]},
        {"name": "platform/bus and core infrastructure", "share": 20, "drivers": ["architecture selection", "redundancy"]},
        {"name": "integration, assembly, and test", "share": 15, "drivers": ["AIT flow", "facility availability"]},
        {"name": "operations and support", "share": 10, "drivers": ["duration", "team size"]},
        {"name": "compliance, legal, and policy", "share": 8, "drivers": ["jurisdiction", "mission class"]},
        {"name": "contingency and reserves", "share": 17, "drivers": ["risk posture", "unknowns"]},
    ]

    return {
        "vision": project_profile.get("summary", ""),
        "mission_statement": conops.get("mission_scenario", project_profile.get("summary", "")),
        "objectives": objective_summary,
        "value_proposition": "Deliver a traceable execution plan with phase-by-phase accountability and subsystem ownership.",
        "target_users": [s.get("role") for s in project_profile.get("stakeholders", []) if s.get("role")],
        "selected_architecture": selected_arch,
        "delivery_model": "milestone-driven, review-gated execution with traceability to requirements and evidence",
        "workstreams": [
            {"name": s["name"], "owner_role": s["owner_role"], "drivers": s["drivers"], "artifacts": s["artifacts"]}
            for s in subsystems
        ],
        "budget_buckets": cost_buckets,
        "top_risks": risk_refs,
        "success_metrics": [
            "every objective traces to requirements",
            "every requirement traces to checklist items and evidence",
            "every subsystem has an owner and a review gate",
            "timeline fits the declared project duration",
        ],
        "execution_style": "deterministic, review-gated, evidence-driven",
        "time_horizon_months": months_total,
        "assumptions": list(project_profile.get("assumptions", []) or []),
    }


def build_wbs(project_profile: Dict[str, Any], domain: str, requirements: Dict[str, Any], subsystems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    wbs: List[Dict[str, Any]] = []
    objectives = project_profile.get("objectives", []) or []
    requirement_index = {req.get("subsystem", "System"): req for bucket in ["mission", "system", "subsystem", "interfaces"] for req in (requirements.get(bucket, []) or [])}

    wbs.append({"id": "1.0", "name": "Program management and governance", "phase": "Cross-cutting", "subsystem": "System", "parent_id": None, "owner_role": "project manager", "deliverables": ["plan baseline", "status cadence"]})
    wbs.append({"id": "2.0", "name": "Systems engineering and mission integration", "phase": "Cross-cutting", "subsystem": "Systems engineering and mission design" if domain == "space_mission" else "Solution architecture", "parent_id": None, "owner_role": "systems engineer", "deliverables": ["architecture baseline", "requirements baseline"]})

    top_id = 3
    for subsystem in subsystems:
        sid = f"{top_id}.0"
        top_id += 1
        subsystem_name = subsystem.get("name", "Subsystem")
        phase_focus = "Phase B" if domain == "space_mission" else "Design"
        wbs.append(
            {
                "id": sid,
                "name": subsystem_name,
                "phase": phase_focus,
                "subsystem": subsystem_name,
                "parent_id": None,
                "owner_role": subsystem.get("owner_role", "lead"),
                "deliverables": list(subsystem.get("artifacts", []) or []),
            }
        )

        child_num = 1
        for phase in phase_names(domain):
            child_id = f"{sid}.{child_num}"
            child_num += 1
            req = requirement_index.get(subsystem_name) or requirement_index.get("System")
            wbs.append(
                {
                    "id": child_id,
                    "name": f"{phase} work package for {subsystem_name}",
                    "phase": phase,
                    "subsystem": subsystem_name,
                    "parent_id": sid,
                    "owner_role": subsystem.get("owner_role", "lead"),
                    "deliverables": [
                        *list(subsystem.get("artifacts", []) or []),
                        *(req.get("source_refs", [])[:1] if req else []),
                    ],
                }
            )

    if objectives:
        wbs.append({"id": f"{top_id}.0", "name": "Objective traceability management", "phase": "Cross-cutting", "subsystem": "System", "parent_id": None, "owner_role": "requirements lead", "deliverables": objectives})

    return wbs


def build_full_subsystem_set(domain: str, selected: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    base = subsystem_library(domain)
    if not selected:
        return base
    seen = {s.get("name") for s in base}
    merged = list(base)
    for subsystem in selected:
        if subsystem.get("name") not in seen:
            merged.append(subsystem)
            seen.add(subsystem.get("name"))
    return merged
