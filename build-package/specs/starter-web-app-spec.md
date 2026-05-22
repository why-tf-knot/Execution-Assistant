# Starter web app specification

## Goal
Build a workspace-first application that turns a user idea into a traceable, cited execution plan with lifecycle phases, subsystem tasks, review gates, and exports.

## Recommended stack
- Front end: Next.js with TypeScript
- API/orchestration: FastAPI or Node service
- Workflow engine: LangGraph or Temporal
- Database: Postgres with pgvector
- Object storage: S3-compatible bucket for source documents and exports

## Primary screens
1. Intake form with free-text idea box
2. Clarification panel for high-impact questions
3. Mission architecture comparison view
4. Phase timeline view
5. Subsystem explorer
6. Review gate dashboard
7. Checklist board with filters by phase, subsystem, and review gate
8. Risk and compliance register
9. Export center

## Core user flow
1. User creates a project and submits an idea.
2. Intake and assumption extraction run.
3. Clarification agent asks only blocking questions.
4. ConOps and architecture options are generated.
5. User selects or confirms a baseline.
6. Requirements, WBS, phases, reviews, and checklists are generated.
7. User edits assumptions or constraints.
8. Downstream states are selectively regenerated.
9. User exports JSON, markdown, spreadsheet, or task bundle.

## Suggested routes
- `/projects`
- `/projects/[projectId]/intake`
- `/projects/[projectId]/clarify`
- `/projects/[projectId]/architectures`
- `/projects/[projectId]/phases`
- `/projects/[projectId]/subsystems`
- `/projects/[projectId]/reviews`
- `/projects/[projectId]/checklists`
- `/projects/[projectId]/risks`
- `/projects/[projectId]/exports`

## API surface
- `POST /api/projects`
- `GET /api/projects/:id`
- `POST /api/projects/:id/intake`
- `POST /api/projects/:id/clarifications`
- `POST /api/projects/:id/workflow/:state/run`
- `POST /api/projects/:id/baseline/select`
- `GET /api/projects/:id/plan`
- `GET /api/projects/:id/checklists?phase=Phase%20B&subsystem=Thermal&review_gate=PDR`
- `POST /api/projects/:id/exports`

## Regeneration rules
- Editing objectives invalidates requirements, WBS, phases, reviews, risks, and checklists.
- Editing ConOps invalidates architectures, requirements, and downstream planning outputs.
- Editing selected architecture invalidates requirements and downstream outputs.
- Editing policy posture invalidates policy checks, risks, and affected checklist items.

## Dashboard widgets
- Dashboard must use simple text boxes only (no charts, graphs, or visual widgets).
- Workflow status text box (current state and blocked reasons)
- Architecture summary text box (selected baseline and top trade drivers)
- Phase status text box (current phase and next gate)
- Review readiness text box (gate status and missing evidence)
- Checklist status text box (open, in-progress, and done counts by subsystem)
- Risk summary text box (top open risks and severity)
- Compliance summary text box (current obligations and due phase)

## Non-functional requirements
- Every persisted plan must conform to the JSON schema.
- Every generated decision or checklist item must preserve source references.
- Workflow states must be resumable and auditable.
- Filters must support queries such as “show only Phase B thermal tasks blocking PDR.”
