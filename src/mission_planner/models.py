from __future__ import annotations
from typing import List, Optional, Any
from pydantic import BaseModel, Field
from uuid import uuid4


class SourceRef(BaseModel):
    doc_id: str
    title: str
    locator: str
    url: str


class Stakeholder(BaseModel):
    name: str
    role: str
    needs: Optional[List[str]] = []


class Assumption(BaseModel):
    id: str
    statement: str
    status: str = "open"
    source_refs: Optional[List[SourceRef]] = []


class Unknown(BaseModel):
    id: str
    question: str
    impact: str
    owner_role: Optional[str] = None


class ProjectProfile(BaseModel):
    title: str
    domain: str
    summary: str
    objectives: List[str]
    stakeholders: List[Stakeholder]
    constraints: dict
    assumptions: List[Assumption]
    unknowns: List[Unknown]


class OperationalMode(BaseModel):
    name: str
    description: str
    entry_conditions: List[str]
    exit_conditions: List[str]


class ConceptOfOperations(BaseModel):
    mission_scenario: str
    operational_modes: List[OperationalMode]
    environment: str
    success_criteria: List[str]
    failure_conditions: List[str]


class Architecture(BaseModel):
    id: str
    description: str
    pros: List[str]
    cons: List[str]
    drivers: List[str]
    trade_scores: Optional[List[dict]] = []
    selected: bool = False
    rationale: Optional[str] = None
    source_refs: Optional[List[SourceRef]] = []


class Requirement(BaseModel):
    id: str
    statement: str
    phase: str
    subsystem: str
    trace_to_objective: List[str]
    verification_method: str
    review_gate: str
    source_refs: Optional[List[SourceRef]] = []


class ChecklistItem(BaseModel):
    id: str
    phase: str
    subsystem: str
    task: str
    purpose: str
    inputs: List[str]
    dependencies: List[str]
    owner_role: str
    trace_to_objective: Optional[List[str]] = []
    trace_to_requirement: Optional[List[str]] = []
    evidence_artifact: List[str]
    exit_criteria: List[str]
    review_gate: str
    risk_if_skipped: str
    source_refs: Optional[List[SourceRef]] = []


class FullPlan(BaseModel):
    project_profile: ProjectProfile
    concept_of_operations: ConceptOfOperations
    architectures: List[Architecture]
    requirements: dict
    wbs: List[Any]
    phases: List[Any]
    reviews: List[Any]
    subsystems: List[Any]
    risks: List[Any]
    policy_and_compliance: List[Any]
    cost_drivers: List[Any]
    checklists: List[ChecklistItem]
    citations: List[SourceRef]


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"
