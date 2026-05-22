# Execution-Assistant

Execution-Assistant now includes a starter build package for a stateful mission execution planning agent. The package turns the high-level architecture blueprint into concrete implementation artifacts that can be used by a web app, orchestration layer, and retrieval pipeline.

## Build package contents

- `build-package/prompts/system-prompt.md` — primary planner system prompt
- `build-package/prompts/sub-agent-prompts.json` — specialist prompt set for pipeline stages
- `build-package/schemas/project-plan.schema.json` — strict JSON schema for machine-usable outputs
- `build-package/schemas/retrieval-design.json` — retrieval corpus, chunking, tagging, and citation design
- `build-package/workflow/state-graph.json` — gated workflow graph with entry and exit conditions
- `build-package/db/schema.sql` — PostgreSQL/pgvector starter schema for state, retrieval, and exports
- `build-package/specs/starter-web-app-spec.md` — starter web app and API specification

## Design goals

- Orchestrated, stateful workflow instead of single-prompt chat
- NASA-aligned lifecycle phases, reviews, and traceability
- Structured outputs suitable for dashboards, exports, and task systems
- Retrieval-backed planning with source-level citations
- Product-oriented decomposition into subsystems and review gates
