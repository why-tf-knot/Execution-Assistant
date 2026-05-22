CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE projects (
  id UUID PRIMARY KEY,
  title TEXT NOT NULL,
  domain TEXT NOT NULL CHECK (domain IN ('space_mission', 'deeptech_business', 'robotics', 'other')),
  summary TEXT NOT NULL,
  mission_class TEXT,
  current_state TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE project_versions (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft', 'review', 'baselined', 'superseded')),
  plan_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (project_id, version_number)
);

CREATE TABLE workflow_runs (
  id UUID PRIMARY KEY,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  state_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'blocked', 'completed', 'failed')),
  entry_check JSONB NOT NULL DEFAULT '{}'::jsonb,
  exit_check JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE source_documents (
  id UUID PRIMARY KEY,
  external_id TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  doc_type TEXT NOT NULL,
  authority TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_version TEXT,
  publication_date DATE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE source_chunks (
  id UUID PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  heading_path TEXT,
  content TEXT NOT NULL,
  embedding VECTOR(1536),
  metadata JSONB NOT NULL,
  UNIQUE (document_id, chunk_index)
);

CREATE INDEX source_chunks_embedding_idx ON source_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX source_chunks_metadata_idx ON source_chunks USING gin (metadata);

CREATE TABLE citations (
  id UUID PRIMARY KEY,
  project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
  source_document_id UUID NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
  source_chunk_id UUID REFERENCES source_chunks(id) ON DELETE SET NULL,
  locator TEXT NOT NULL,
  citation_context TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE checklist_items (
  id UUID PRIMARY KEY,
  project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
  checklist_code TEXT NOT NULL,
  phase TEXT NOT NULL,
  subsystem TEXT NOT NULL,
  task TEXT NOT NULL,
  purpose TEXT NOT NULL,
  inputs JSONB NOT NULL DEFAULT '[]'::jsonb,
  dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
  owner_role TEXT NOT NULL,
  evidence_artifact JSONB NOT NULL DEFAULT '[]'::jsonb,
  exit_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
  review_gate TEXT NOT NULL,
  risk_if_skipped TEXT NOT NULL CHECK (risk_if_skipped IN ('low', 'medium', 'high')),
  trace_to_objective JSONB NOT NULL DEFAULT '[]'::jsonb,
  trace_to_requirement JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE review_gates (
  id UUID PRIMARY KEY,
  project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
  gate_name TEXT NOT NULL,
  phase TEXT NOT NULL,
  objective TEXT NOT NULL,
  required_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'ready', 'complete'))
);

CREATE TABLE exports (
  id UUID PRIMARY KEY,
  project_version_id UUID NOT NULL REFERENCES project_versions(id) ON DELETE CASCADE,
  export_type TEXT NOT NULL CHECK (export_type IN ('json', 'markdown', 'docx', 'spreadsheet', 'task_bundle', 'dashboard')),
  storage_uri TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
