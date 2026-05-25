from typing import List, Dict, Any
from .models import make_id
from . import retrieval
from .llm import MockLLM, LLMClient, get_default_llm
import json
import jsonschema
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "build-package" / "schemas" / "project-plan.schema.json"
_SCHEMA = None
try:
    _SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    REQ_SCHEMA = _SCHEMA.get("$defs", {}).get("requirement")
except Exception:
    REQ_SCHEMA = None
from pathlib import Path


PROMPT_PATH = Path(__file__).resolve().parents[2] / "build-package" / "prompts" / "requirements_agent_prompt.md"


def _load_prompt_template() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return "Convert objectives and ConOps into requirements."


def derive_requirements(project_profile: Dict[str, Any], conops: Dict[str, Any], subsystems: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministically derive a small set of requirements from the project profile and ConOps.

    This is a skeleton implementation for Sprint 1. It creates:
    - one mission requirement per objective
    - one system requirement per ConOps success criterion
    - one subsystem requirement per named subsystem driver
    - a simple verification map that pairs requirements with generic methods
    """
    mission_reqs = []
    system_reqs = []
    subsystem_reqs = []
    verification_map = []

    objectives = project_profile.get("objectives", [])
    for obj in objectives:
        rid = make_id("REQ")
        stmt = f"Mission shall: {obj}"
        req = {
            "id": rid,
            "statement": stmt,
            "phase": "Phase A",
            "subsystem": "System",
            "trace_to_objective": [obj],
            "verification_method": "review",
            "review_gate": "SRR",
            "source_refs": [],
        }
        mission_reqs.append(req)
        verification_map.append({"requirement_id": rid, "verification_method": "review", "evidence_artifact": ["mission statement, ConOps"], "review_gate": "SRR"})

    success_criteria = conops.get("success_criteria", []) if conops else []
    for sc in success_criteria:
        rid = make_id("REQ")
        stmt = f"System shall ensure: {sc}"
        req = {
            "id": rid,
            "statement": stmt,
            "phase": "Phase B",
            "subsystem": "System",
            "trace_to_objective": [objectives[0]] if objectives else [],
            "verification_method": "test",
            "review_gate": "PDR",
            "source_refs": [],
        }
        system_reqs.append(req)
        verification_map.append({"requirement_id": rid, "verification_method": "test", "evidence_artifact": ["system test report"], "review_gate": "PDR"})

    # subsystem level: one requirement per driver
    for ss in subsystems or []:
        name = ss.get("name", "Unnamed")
        drivers = ss.get("drivers", [])
        for d in drivers:
            rid = make_id("REQ")
            stmt = f"{name} shall address driver: {d}"
            req = {
                "id": rid,
                "statement": stmt,
                "phase": "Phase B",
                "subsystem": name,
                "trace_to_objective": [objectives[0]] if objectives else [],
                "verification_method": "analysis",
                "review_gate": "PDR",
                "source_refs": [],
            }
            subsystem_reqs.append(req)
            verification_map.append({"requirement_id": rid, "verification_method": "analysis", "evidence_artifact": [f"{name} analysis"], "review_gate": "PDR"})

    return {
        "mission": mission_reqs,
        "system": system_reqs,
        "subsystem": subsystem_reqs,
        "interfaces": [],
        "verification_map": verification_map,
    }


def derive_requirements_via_llm(project_profile: Dict[str, Any], conops: Dict[str, Any], subsystems: List[Dict[str, Any]], llm: LLMClient = None) -> Dict[str, Any]:
    """Derive requirements using the retrieval pipeline and an LLM.

    This function builds a prompt from the template, retrieves supporting chunks
    for each objective and success criterion, calls the LLM, and attaches
    `source_refs` and a simple `rationale` to each derived requirement.
    """
    if llm is None:
        llm = get_default_llm()

    base = derive_requirements(project_profile, conops, subsystems)

    prompt_template = _load_prompt_template()

    # Enrich mission requirements with retrieval results and LLM rationale
    for req in base.get("mission", []) + base.get("system", []) + base.get("subsystem", []):
        query = req.get("statement")
        chunks = retrieval.search_chunks(query=query, top_k=3)
        # attach source refs derived from chunks
        srcs = []
        for c in chunks:
            meta = c.get("metadata", {})
            srcs.append({
                "doc_id": c.get("doc_id"),
                "title": c.get("title"),
                "locator": c.get("section", ""),
                "url": meta.get("source_url", "")
            })
        req["source_refs"] = srcs

        # Build a small prompt including the requirement and doc ids
        doc_ids = " ".join([f"doc_id:{s['doc_id']}" for s in srcs if s.get("doc_id")])
        prompt = f"{prompt_template}\nRequirement: {req.get('statement')}\nSources: {doc_ids}\n"
        resp = llm.generate(prompt)
        # Try to parse JSON from the LLM response
        try:
            parsed = json.loads(resp)
        except Exception:
            # attempt to extract JSON substring
            start = resp.find('{')
            end = resp.rfind('}')
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(resp[start:end+1])
                except Exception:
                    parsed = {"rationale": resp}
            else:
                parsed = {"rationale": resp}

        rationale = parsed.get("rationale") if isinstance(parsed, dict) else str(parsed)
        req["rationale"] = rationale

        # If the LLM provided structured requirements, optionally validate them
        if isinstance(parsed, dict) and parsed.get("requirements"):
            # user-provided structured output; not used here, but could replace reqs
            pass

        # Validate the single requirement against local schema if available
        if REQ_SCHEMA:
            try:
                jsonschema.validate(instance={k: req.get(k) for k in ["id","statement","phase","subsystem","trace_to_objective","verification_method","review_gate","source_refs"]}, schema=REQ_SCHEMA)
            except Exception:
                # If validation fails, annotate rationale with a warning
                req["rationale"] = (req.get("rationale", "") + " (validation_failed)")

    return base
