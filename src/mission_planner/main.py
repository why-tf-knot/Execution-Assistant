from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
from pathlib import Path
import json
from typing import Optional, List
import csv
import io

from mission_planner.models import (
    ProjectProfile,
    ConceptOfOperations,
    Architecture,
    Requirement,
    ChecklistItem,
    FullPlan,
    Stakeholder,
    Assumption,
    Unknown,
    OperationalMode,
    make_id,
    SourceRef,
)
from mission_planner import retrieval
from mission_planner import requirements_agent
from mission_planner import checklist_generator
from mission_planner import planning_artifacts
from mission_planner.llm import MockLLM, get_default_llm
from mission_planner.vector_store import VectorStore
from mission_planner.vector_store_pg import PGVectorStore
from pathlib import Path
import os
from mission_planner.middleware import (
    SimpleRateLimiterMiddleware,
    APIKeyAuthMiddleware,
    RequestLoggingMiddleware,
    init_sentry_if_configured,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "build-package" / "db" / "projects"
EXPORT_DIR = ROOT / "build-package" / "exports"
DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Mission Planning Engine - Sprint 1")

# Add basic CORS for the front-end
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Basic structured logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# initialize sentry if configured
_sentry = init_sentry_if_configured()

# Attach middlewares: logging first so we capture timing, then auth, then rate limit
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(APIKeyAuthMiddleware)
app.add_middleware(SimpleRateLimiterMiddleware, rate_limit_rps=int(os.environ.get("RATE_LIMIT_RPS", "5")))


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception during request: %s %s", request.method, request.url.path)
    # send to sentry if available
    try:
        if _sentry:
            _sentry.capture_exception(exc)
    except Exception:
        logger.exception("Failed to report exception to Sentry")
    return JSONResponse({"detail": "internal server error"}, status_code=500)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SQL = ROOT / "build-package" / "db" / "migrations" / "001_create_vector_table.sql"


def _save_project(project_id: str, payload: dict, version: int = 1):
    file = DATA_DIR / f"project_{project_id}_v{version}.json"
    with file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return str(file)


def _load_latest(project_id: str):
    candidates = sorted(DATA_DIR.glob(f"project_{project_id}_v*.json"))
    if not candidates:
        return None
    def version_number(path: Path) -> int:
        stem = path.stem
        try:
            return int(stem.rsplit("_v", 1)[-1])
        except (ValueError, IndexError):
            return -1

    latest = max(candidates, key=version_number)
    with latest.open("r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/projects")
def create_project(payload: dict):
    idea = payload.get("idea")
    if not idea:
        raise HTTPException(status_code=400, detail="Missing 'idea' field")
    domain = payload.get("domain", "space_mission")
    constraints = payload.get("constraints", {})

    project_id = uuid4().hex

    # Minimal intake: create project_profile with light parsing and mark inferred bits as assumptions
    title = payload.get("title") or (" ".join(idea.split()[:6]) + "...")
    stakeholders = [Stakeholder(name="Requester", role="owner").dict()]
    assumptions = [
        Assumption(id=make_id("ASM"), statement=f"Inferred domain: {domain}", status="open").dict()
    ]
    unknowns = []

    project_profile = {
        "title": title,
        "domain": domain,
        "summary": idea,
        "objectives": ["Define mission scope and success criteria"],
        "stakeholders": stakeholders,
        "constraints": constraints,
        "assumptions": assumptions,
        "unknowns": unknowns,
    }

    record = {
        "id": project_id,
        "version": 1,
        "project_profile": project_profile,
        "status": "ingested",
    }

    path = _save_project(project_id, record, version=1)
    return {"project_id": project_id, "path": path}


@app.post("/api/projects/{project_id}/generate-plan")
def generate_plan(project_id: str, payload: dict):
    state = _load_latest(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found")

    clarification = payload.get("clarification_answers", {})
    profile = state["project_profile"]
    domain = profile.get("domain", "other")
    schedule_text = profile.get("constraints", {}).get("schedule")
    months_total = planning_artifacts.parse_schedule_months(schedule_text, default_months=18)

    # Build a deterministic ConOps and two architectures
    modes = [
        OperationalMode(
            name="Nominal",
            description="Normal mission operations",
            entry_conditions=["Launched", "Commissioned"],
            exit_conditions=["End of mission"],
        ).dict()
    ]

    conops = ConceptOfOperations(
        mission_scenario=f"{state['project_profile']['summary']}",
        operational_modes=modes,
        environment="space / target body",
        success_criteria=["Collect required data", "Safe disposal or parking"],
        failure_conditions=["Loss of communications", "Critical subsystem failure"],
    ).dict()

    arch1 = Architecture(
        id=make_id("ARCH"),
        description="Simple smallsat bus with hosted payload",
        pros=["Lower cost", "Faster schedule"],
        cons=["Limited payload capability"],
        drivers=["budget", "schedule"],
        selected=False,
        rationale="",
        source_refs=[SourceRef(doc_id="nasa_seh", title="NASA SEH", locator="4.0", url="https://www.nasa.gov/").dict()],
    ).dict()

    arch2 = Architecture(
        id=make_id("ARCH"),
        description="Dedicated medium-class spacecraft with robust avionics",
        pros=["Higher capability", "better redundancy"],
        cons=["Higher cost", "longer schedule"],
        drivers=["capability", "reliability"],
        selected=True,
        rationale="Selected for capability and margin",
        source_refs=[SourceRef(doc_id="nasa_seh", title="NASA SEH", locator="4.0", url="https://www.nasa.gov/").dict()],
    ).dict()

    architectures = [arch1, arch2]

    # Minimal requirements example
    req = Requirement(
        id=make_id("REQ"),
        statement="Spacecraft shall provide telemetry to ground at required data rates",
        phase="Phase B",
        subsystem="Communications",
        trace_to_objective=[state['project_profile']['objectives'][0]],
        verification_method="test",
        review_gate="PDR",
        source_refs=[SourceRef(doc_id="nasa_seh", title="NASA SEH", locator="2.0", url="https://www.nasa.gov/").dict()],
    ).dict()

    # Subsystems: use default library
    subsystems = planning_artifacts.build_full_subsystem_set(domain, [
        {"name": "Electrical Power", "drivers": ["power budget"], "interfaces": [], "artifacts": [], "owner_role": "EPS lead"},
        {"name": "Communications", "drivers": ["link budget"], "interfaces": [], "artifacts": [], "owner_role": "communications lead"},
        {"name": "Flight Software", "drivers": ["autonomy"], "interfaces": [], "artifacts": [], "owner_role": "software lead"},
    ])

    # Checklist examples
    checklist = ChecklistItem(
        id=make_id("CHK"),
        phase="Phase B",
        subsystem="Electrical Power",
        task="Close preliminary power budget for all mission modes",
        purpose="Support preliminary design maturity and interface allocation",
        inputs=["ConOps", "mode table", "load list", "orbit assumptions"],
        dependencies=["system mode definition complete"],
        owner_role="EPS lead",
        evidence_artifact=["power budget sheet", "mode-based EPS analysis"],
        exit_criteria=["design margin applied", "peak loads allocated"],
        review_gate="PDR",
        risk_if_skipped="high",
        source_refs=[SourceRef(doc_id="nasa_seh", title="NASA SEH", locator="4.0", url="https://www.nasa.gov/").dict()],
    ).dict()

    plan: dict = {
        "project_profile": profile,
        "concept_of_operations": conops,
        "architectures": architectures,
        "requirements": {"mission": [], "system": [req], "subsystem": [], "interfaces": [], "verification_map": []},
        "business_plan": planning_artifacts.build_business_plan(profile, conops, architectures, {"mission": [], "system": [req], "subsystem": [], "interfaces": []}, subsystems, months_total),
        "timeline": planning_artifacts.build_timeline(profile, domain, months_total),
        "wbs": planning_artifacts.build_wbs(profile, domain, {"mission": [], "system": [req], "subsystem": [], "interfaces": []}, subsystems),
        "phases": planning_artifacts.build_timeline(profile, domain, months_total),
        "reviews": [],
        "subsystems": subsystems,
        "risks": [],
        "policy_and_compliance": [],
        "cost_drivers": [],
        "checklists": [checklist],
        "citations": [SourceRef(doc_id="nasa_seh", title="NASA SEH", locator="top", url="https://www.nasa.gov/").dict()],
    }

    # persist new version
    version = state.get("version", 1) + 1
    record = {"id": project_id, "version": version, "project_profile": plan["project_profile"], "plan": plan, "status": "plan_generated"}
    _save_project(project_id, record, version=version)
    return JSONResponse(plan)


@app.get("/api/projects/{project_id}/checklists")
def get_checklists(project_id: str, phase: Optional[str] = None, subsystem: Optional[str] = None):
    state = _load_latest(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found")
    plan = state.get("plan") or {}
    items = plan.get("checklists", [])
    def matches(it):
        if phase and it.get("phase") != phase:
            return False
        if subsystem and it.get("subsystem") != subsystem:
            return False
        return True
    filtered = [it for it in items if matches(it)]
    return {"checklists": filtered}


@app.get("/api/projects/{project_id}/plan")
def get_project_plan(project_id: str):
    state = _load_latest(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return state.get("plan") or state


@app.post("/api/projects/{project_id}/generate-checklists")
def generate_checklists(project_id: str):
    state = _load_latest(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found")
    plan = state.get("plan") or {}
    profile = plan.get("project_profile") or state.get("project_profile") or {}
    conops = plan.get("concept_of_operations") or {}
    requirements = plan.get("requirements") or {}
    subsystems = plan.get("subsystems", []) or []

    # If an LLM provider is configured, prefer an LLM-assisted checklist synthesis
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        try:
            items = checklist_generator.generate_checklists_via_llm(profile, conops, requirements, subsystems)
        except Exception:
            items = checklist_generator.generate_checklists(profile, conops, requirements, subsystems)
    else:
        items = checklist_generator.generate_checklists(profile, conops, requirements, subsystems)
    plan["checklists"] = items

    version = state.get("version", 1) + 1
    record = {"id": project_id, "version": version, "project_profile": plan.get("project_profile"), "plan": plan, "status": "checklists_generated"}
    _save_project(project_id, record, version=version)
    return {"checklists": items}


@app.get("/api/retrieve")
def retrieve(query: Optional[str] = None, phase: Optional[str] = None, subsystem: Optional[str] = None, top_k: int = 5):
    """Search the seed document chunks using simple keyword and tag filters.

    Use `phase` and `subsystem` to filter by metadata tags (matching values in `phase_tags` and `subsystem_tags`).
    """
    phase_tags = [phase] if phase else None
    subsystem_tags = [subsystem] if subsystem else None
    results = retrieval.search_chunks(query=query, phase_tags=phase_tags, subsystem_tags=subsystem_tags, top_k=top_k)
    return {"results": results}


@app.post("/api/projects/{project_id}/export")
def export_project(project_id: str, payload: dict):
    fmt: List[str] = payload.get("format", ["json"])
    state = _load_latest(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found")
    plan = state.get("plan") or {"project_profile": state.get("project_profile")}

    outputs = {}
    if "json" in fmt:
        out_file = EXPORT_DIR / f"project_{project_id}.json"
        with out_file.open("w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
        outputs["json"] = str(out_file)

    if "markdown" in fmt:
        md = [f"# {plan['project_profile'].get('title','Project')}\n"]
        md.append("## Summary\n")
        md.append(plan["project_profile"].get("summary","") + "\n")
        md.append("## Objectives\n")
        for o in plan["project_profile"].get("objectives",[]):
            md.append(f"- {o}\n")
        md_text = "\n".join(md)
        md_file = EXPORT_DIR / f"project_{project_id}.md"
        md_file.write_text(md_text, encoding="utf-8")
        outputs["markdown"] = str(md_file)

    # Checklist CSV export
    if "csv" in fmt or "excel" in fmt:
        checklists = plan.get("checklists", []) or []
        csv_file = EXPORT_DIR / f"project_{project_id}_checklists.csv"
        with csv_file.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            # header
            writer.writerow(["id","phase","subsystem","task","purpose","inputs","dependencies","owner_role","trace_to_objective","trace_to_requirement","evidence_artifact","exit_criteria","review_gate","risk_if_skipped","source_refs"])
            for it in checklists:
                writer.writerow([
                    it.get("id",""),
                    it.get("phase",""),
                    it.get("subsystem",""),
                    it.get("task",""),
                    it.get("purpose",""),
                    "; ".join(it.get("inputs",[]) or []),
                    "; ".join(it.get("dependencies",[]) or []),
                    it.get("owner_role",""),
                    "; ".join(it.get("trace_to_objective",[]) or []),
                    "; ".join(it.get("trace_to_requirement",[]) or []),
                    "; ".join(it.get("evidence_artifact",[]) or []),
                    "; ".join(it.get("exit_criteria",[]) or []),
                    it.get("review_gate",""),
                    it.get("risk_if_skipped",""),
                    json.dumps(it.get("source_refs",[]) or []),
                ])
        outputs["csv"] = str(csv_file)

        # Excel export (optional): try openpyxl, else skip. Supports multi-sheet export by phase and/or subsystem.
        if "excel" in fmt:
            try:
                from openpyxl import Workbook
                from openpyxl.styles import Alignment, Font

                wb = Workbook()
                headers = ["id","phase","subsystem","task","purpose","inputs","dependencies","owner_role","trace_to_objective","trace_to_requirement","evidence_artifact","exit_criteria","review_gate","risk_if_skipped","source_refs"]

                def add_sheet(name, rows):
                    ws = wb.create_sheet(title=name)
                    ws.append(headers)
                    header_font = Font(bold=True)
                    for col_idx, _ in enumerate(headers, start=1):
                        cell = ws.cell(row=1, column=col_idx)
                        cell.font = header_font
                        cell.alignment = Alignment(wrap_text=True, vertical='center')
                    for it in rows:
                        row = [
                            it.get("id",""),
                            it.get("phase",""),
                            it.get("subsystem",""),
                            it.get("task",""),
                            it.get("purpose",""),
                            "; ".join(it.get("inputs",[]) or []),
                            "; ".join(it.get("dependencies",[]) or []),
                            it.get("owner_role",""),
                            "; ".join(it.get("trace_to_objective",[]) or []),
                            "; ".join(it.get("trace_to_requirement",[]) or []),
                            "; ".join(it.get("evidence_artifact",[]) or []),
                            "; ".join(it.get("exit_criteria",[]) or []),
                            it.get("review_gate",""),
                            it.get("risk_if_skipped",""),
                            json.dumps(it.get("source_refs",[]) or []),
                        ]
                        # truncation guard (keep values safe for Excel cells)
                        row = [str(v)[:10000] if v is not None else "" for v in row]
                        ws.append(row)
                    # compute and set column widths (bounded)
                    col_widths = [len(h) for h in headers]
                    for row in ws.iter_rows(min_row=2, values_only=True):
                        for i, v in enumerate(row):
                            l = len(str(v)) if v is not None else 0
                            if l > col_widths[i]:
                                col_widths[i] = l
                    for i, w in enumerate(col_widths, start=1):
                        letter = ws.cell(row=1, column=i).column_letter
                        ws.column_dimensions[letter].width = min(max((w or 10) + 2, 15), 120)
                    for row in ws.iter_rows(min_row=2):
                        for cell in row:
                            cell.alignment = Alignment(wrap_text=True, vertical='top')
                    ws.freeze_panes = ws['A2']

                # Main sheet
                main_ws = wb.active
                main_ws.title = "All Checklists"
                main_ws.append(headers)
                header_font = Font(bold=True)
                for col_idx, _ in enumerate(headers, start=1):
                    cell = main_ws.cell(row=1, column=col_idx)
                    cell.font = header_font
                    cell.alignment = Alignment(wrap_text=True, vertical='center')
                for it in checklists:
                    row = [
                        it.get("id",""),
                        it.get("phase",""),
                        it.get("subsystem",""),
                        it.get("task",""),
                        it.get("purpose",""),
                        "; ".join(it.get("inputs",[]) or []),
                        "; ".join(it.get("dependencies",[]) or []),
                        it.get("owner_role",""),
                        "; ".join(it.get("trace_to_objective",[]) or []),
                        "; ".join(it.get("trace_to_requirement",[]) or []),
                        "; ".join(it.get("evidence_artifact",[]) or []),
                        "; ".join(it.get("exit_criteria",[]) or []),
                        it.get("review_gate",""),
                        it.get("risk_if_skipped",""),
                        json.dumps(it.get("source_refs",[]) or []),
                    ]
                    row = [str(v)[:10000] if v is not None else "" for v in row]
                    main_ws.append(row)

                # compute widths for main sheet
                col_widths = [len(h) for h in headers]
                for row in main_ws.iter_rows(min_row=2, values_only=True):
                    for i, v in enumerate(row):
                        l = len(str(v)) if v is not None else 0
                        if l > col_widths[i]:
                            col_widths[i] = l
                for i, w in enumerate(col_widths, start=1):
                    letter = main_ws.cell(row=1, column=i).column_letter
                    main_ws.column_dimensions[letter].width = min(max((w or 10) + 2, 15), 120)
                for row in main_ws.iter_rows(min_row=2):
                    for cell in row:
                        cell.alignment = Alignment(wrap_text=True, vertical='top')
                main_ws.freeze_panes = main_ws['A2']

                # optional additional sheets
                def _sanitize_sheet_name(name: str) -> str:
                    # Excel sheet title rules: max 31 chars and cannot contain: : \\ / ? * [ ]
                    if not name:
                        return "Sheet"
                    for ch in [":","\\","/","?","*","[","]"]:
                        name = name.replace(ch, "-")
                    name = name.strip()
                    if len(name) > 31:
                        name = name[:31]
                    return name or "Sheet"

                if (sheets_mode := payload.get("sheets", "one")):
                    if sheets_mode in ("by_phase", "both"):
                        phases = {}
                        for it in checklists:
                            phases.setdefault(it.get('phase','Unknown'), []).append(it)
                        for phase_name, rows in phases.items():
                            add_sheet(_sanitize_sheet_name(str(phase_name)), rows)
                    if sheets_mode in ("by_subsystem", "both"):
                        subs = {}
                        for it in checklists:
                            subs.setdefault(it.get('subsystem','Unknown'), []).append(it)
                        for sub_name, rows in subs.items():
                            add_sheet(_sanitize_sheet_name(str(sub_name)), rows)

                xlsx_file = EXPORT_DIR / f"project_{project_id}_checklists.xlsx"
                wb.save(str(xlsx_file))
                outputs["excel"] = str(xlsx_file)
            except Exception:
                outputs.setdefault("excel", None)

    return outputs


@app.get("/api/projects/{project_id}/export_stream.csv")
def stream_checklists_csv(project_id: str, phase: Optional[str] = None, subsystem: Optional[str] = None):
    """Stream the project's checklists as a CSV attachment."""
    state = _load_latest(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found")
    plan = state.get("plan") or {"project_profile": state.get("project_profile")}
    checklists = plan.get("checklists", []) or []
    # apply optional filters
    if phase:
        checklists = [it for it in checklists if str(it.get("phase","")).lower() == str(phase).lower()]
    if subsystem:
        checklists = [it for it in checklists if str(it.get("subsystem","")).lower() == str(subsystem).lower()]

    buf = io.StringIO()
    writer = csv.writer(buf)
    headers = ["id","phase","subsystem","task","purpose","inputs","dependencies","owner_role","trace_to_objective","trace_to_requirement","evidence_artifact","exit_criteria","review_gate","risk_if_skipped","source_refs"]
    writer.writerow(headers)
    for it in checklists:
        writer.writerow([
            it.get("id",""),
            it.get("phase",""),
            it.get("subsystem",""),
            it.get("task",""),
            it.get("purpose",""),
            "; ".join(it.get("inputs",[]) or []),
            "; ".join(it.get("dependencies",[]) or []),
            it.get("owner_role",""),
            "; ".join(it.get("trace_to_objective",[]) or []),
            "; ".join(it.get("trace_to_requirement",[]) or []),
            "; ".join(it.get("evidence_artifact",[]) or []),
            "; ".join(it.get("exit_criteria",[]) or []),
            it.get("review_gate",""),
            it.get("risk_if_skipped",""),
            json.dumps(it.get("source_refs",[]) or []),
        ])
    data = buf.getvalue().encode("utf-8")
    return StreamingResponse(io.BytesIO(data), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=project_{project_id}_checklists.csv"})


@app.get("/api/projects/{project_id}/export_stream.xlsx")
def stream_checklists_xlsx(project_id: str, sheets: Optional[str] = "one", phase: Optional[str] = None, subsystem: Optional[str] = None):
    """Stream the project's checklists as an Excel attachment.

    Query `sheets` can be: `one` (single sheet), `by_phase`, `by_subsystem`, `both`.
    """
    state = _load_latest(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found")
    plan = state.get("plan") or {"project_profile": state.get("project_profile")}
    checklists = plan.get("checklists", []) or []
    # apply optional filters
    if phase:
        checklists = [it for it in checklists if str(it.get("phase","")).lower() == str(phase).lower()]
    if subsystem:
        checklists = [it for it in checklists if str(it.get("subsystem","")).lower() == str(subsystem).lower()]

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except Exception:
        raise HTTPException(status_code=500, detail="openpyxl is not available on the server")

    wb = Workbook()
    headers = ["id","phase","subsystem","task","purpose","inputs","dependencies","owner_role","trace_to_objective","trace_to_requirement","evidence_artifact","exit_criteria","review_gate","risk_if_skipped","source_refs"]

    def add_sheet(ws_name: str, rows):
        ws = wb.create_sheet(title=ws_name)
        ws.append(headers)
        header_font = Font(bold=True)
        for col_idx, _ in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.alignment = Alignment(wrap_text=True, vertical='center')
        for it in rows:
            row = [
                it.get("id",""),
                it.get("phase",""),
                it.get("subsystem",""),
                it.get("task",""),
                it.get("purpose",""),
                "; ".join(it.get("inputs",[]) or []),
                "; ".join(it.get("dependencies",[]) or []),
                it.get("owner_role",""),
                "; ".join(it.get("trace_to_objective",[]) or []),
                "; ".join(it.get("trace_to_requirement",[]) or []),
                "; ".join(it.get("evidence_artifact",[]) or []),
                "; ".join(it.get("exit_criteria",[]) or []),
                it.get("review_gate",""),
                it.get("risk_if_skipped",""),
                json.dumps(it.get("source_refs",[]) or []),
            ]
            row = [str(v)[:10000] if v is not None else "" for v in row]
            ws.append(row)
        # set widths and wrapping
        col_widths = [len(h) for h in headers]
        for row in ws.iter_rows(min_row=2, values_only=True):
            for i, v in enumerate(row):
                l = len(str(v)) if v is not None else 0
                if l > col_widths[i]:
                    col_widths[i] = l
        for i, w in enumerate(col_widths, start=1):
            letter = ws.cell(row=1, column=i).column_letter
            ws.column_dimensions[letter].width = min(max((w or 10) + 2, 15), 120)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
        ws.freeze_panes = ws['A2']

    # main sheet
    main_ws = wb.active
    main_ws.title = "All Checklists"
    main_ws.append(headers)
    header_font = Font(bold=True)
    for col_idx, _ in enumerate(headers, start=1):
        cell = main_ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical='center')
    for it in checklists:
        row = [
            it.get("id",""),
            it.get("phase",""),
            it.get("subsystem",""),
            it.get("task",""),
            it.get("purpose",""),
            "; ".join(it.get("inputs",[]) or []),
            "; ".join(it.get("dependencies",[]) or []),
            it.get("owner_role",""),
            "; ".join(it.get("trace_to_objective",[]) or []),
            "; ".join(it.get("trace_to_requirement",[]) or []),
            "; ".join(it.get("evidence_artifact",[]) or []),
            "; ".join(it.get("exit_criteria",[]) or []),
            it.get("review_gate",""),
            it.get("risk_if_skipped",""),
            json.dumps(it.get("source_refs",[]) or []),
        ]
        row = [str(v)[:10000] if v is not None else "" for v in row]
        main_ws.append(row)
    # widths/wrap for main
    col_widths = [len(h) for h in headers]
    for row in main_ws.iter_rows(min_row=2, values_only=True):
        for i, v in enumerate(row):
            l = len(str(v)) if v is not None else 0
            if l > col_widths[i]:
                col_widths[i] = l
    for i, w in enumerate(col_widths, start=1):
        letter = main_ws.cell(row=1, column=i).column_letter
        main_ws.column_dimensions[letter].width = min(max((w or 10) + 2, 15), 120)
    for row in main_ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical='top')
    main_ws.freeze_panes = main_ws['A2']

    # optional sheets
    def _sanitize_sheet_name(name: str) -> str:
        if not name:
            return "Sheet"
        for ch in [":","\\","/","?","*","[","]"]:
            name = name.replace(ch, "-")
        name = name.strip()
        if len(name) > 31:
            name = name[:31]
        return name or "Sheet"

    if sheets in ("by_phase", "both"):
        phases = {}
        for it in checklists:
            phases.setdefault(it.get('phase','Unknown'), []).append(it)
        for phase_name, rows in phases.items():
            add_sheet(_sanitize_sheet_name(str(phase_name)), rows)
    if sheets in ("by_subsystem", "both"):
        subs = {}
        for it in checklists:
            subs.setdefault(it.get('subsystem','Unknown'), []).append(it)
        for sub_name, rows in subs.items():
            add_sheet(_sanitize_sheet_name(str(sub_name)), rows)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=project_{project_id}_checklists.xlsx"})


@app.post("/api/projects/{project_id}/derive-requirements")
def derive_requirements(project_id: str):
    state = _load_latest(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found")
    plan = state.get("plan") or {}
    profile = plan.get("project_profile") or state.get("project_profile")
    conops = plan.get("concept_of_operations")
    subsystems = plan.get("subsystems", [])

    reqs = requirements_agent.derive_requirements(profile, conops, subsystems)

    # attach into plan and persist new version
    plan["requirements"] = reqs
    plan["checklists"] = checklist_generator.generate_checklists(profile, plan.get("concept_of_operations") or {}, reqs, plan.get("subsystems", []))
    version = state.get("version", 1) + 1
    record = {"id": project_id, "version": version, "project_profile": plan.get("project_profile"), "plan": plan, "status": "requirements_derived"}
    _save_project(project_id, record, version=version)
    return reqs


@app.post("/api/projects/{project_id}/derive-requirements-llm")
def derive_requirements_llm(project_id: str):
    state = _load_latest(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found")
    plan = state.get("plan") or {}
    profile = plan.get("project_profile") or state.get("project_profile")
    conops = plan.get("concept_of_operations")
    subsystems = plan.get("subsystems", [])

    llm = get_default_llm()
    reqs = requirements_agent.derive_requirements_via_llm(profile, conops, subsystems, llm=llm)

    # attach into plan and persist new version
    plan["requirements"] = reqs
    plan["checklists"] = checklist_generator.generate_checklists(profile, plan.get("concept_of_operations") or {}, reqs, plan.get("subsystems", []))
    version = state.get("version", 1) + 1
    record = {"id": project_id, "version": version, "project_profile": plan.get("project_profile"), "plan": plan, "status": "requirements_derived_llm"}
    _save_project(project_id, record, version=version)
    return reqs


@app.post("/api/ingest-chunk")
def ingest_chunk(payload: dict):
    """Ingest a document chunk into the vector store. Expects fields: id, doc_id, title, section, content, metadata"""
    required = ["id", "doc_id", "title", "content"]
    for k in required:
        if k not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field: {k}")
    vs = VectorStore()
    vs.upsert_chunk(payload)
    return {"status": "ok", "id": payload.get("id")}


@app.post("/api/pg/init")
def init_pgvector():
    """Initialize pgvector schema in the configured Postgres database.

    Requires DATABASE_URL and psycopg/pgvector available in the environment.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=400, detail="DATABASE_URL is not set")
    try:
        pg = PGVectorStore(db_url)
        pg.init_db()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"pgvector init failed: {exc}")
    return {"status": "ok", "migration": str(MIGRATION_SQL)}
