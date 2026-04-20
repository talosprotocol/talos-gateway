-- Talos Audit Store Schema (PostgreSQL)

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Events Table
CREATE TABLE IF NOT EXISTS events (
    event_id UUID PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT '1',
    timestamp BIGINT NOT NULL, -- Unix timestamp in seconds
    cursor TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    outcome TEXT NOT NULL,
    
    -- Identity
    session_id UUID NOT NULL,
    correlation_id UUID,
    agent_id TEXT NOT NULL,
    peer_id TEXT,
    
    -- Operation
    tool TEXT NOT NULL,
    method TEXT NOT NULL,
    resource TEXT,
    
    -- Optimized Monitoring (Surfaced from metadata for performance)
    denial_reason TEXT,
    latency_ms DOUBLE PRECISION,
    
    -- Payloads (JSONB for flexibility)
    metadata JSONB NOT NULL DEFAULT '{}',
    metrics JSONB NOT NULL DEFAULT '{}',
    hashes JSONB NOT NULL DEFAULT '{}',
    integrity JSONB NOT NULL DEFAULT '{}',
    
    integrity_hash TEXT NOT NULL,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for Query Patterns
CREATE INDEX IF NOT EXISTS idx_events_cursor ON events(cursor);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_denial ON events(denial_reason) WHERE denial_reason IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_latency ON events(latency_ms) WHERE latency_ms IS NOT NULL;

-- 2. Jobs Table (for Export/Batch Operations)
CREATE TABLE IF NOT EXISTS jobs (
    job_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type TEXT NOT NULL, -- 'export', 'reindex', etc.
    status TEXT NOT NULL, -- 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'
    
    -- Job Parameters
    request_params JSONB NOT NULL,
    
    -- Job Result/Manifest
    result JSONB,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

-- 3. Selections Table (for snapshotting filter sets)
CREATE TABLE IF NOT EXISTS selections (
    selection_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    snapshot_cursor TEXT NOT NULL, -- The upper bound cursor at creation
    filter_criteria JSONB NOT NULL,
    
    metrics JSONB, -- e.g. {"count": 1234, "size_bytes": 100000}
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE
);

-- 4. RBAC Roles Table
CREATE TABLE IF NOT EXISTS rbac_roles (
    role_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    permissions JSONB NOT NULL DEFAULT '[]',
    built_in BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. RBAC Bindings Table
CREATE TABLE IF NOT EXISTS rbac_bindings (
    principal_id TEXT PRIMARY KEY,
    bindings JSONB NOT NULL DEFAULT '[]', -- List of {role_id, scope}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Custom Secrets Table (API-managed)
CREATE TABLE IF NOT EXISTS custom_secrets (
    name TEXT PRIMARY KEY,
    kek_id TEXT NOT NULL,
    ciphertext TEXT NOT NULL,
    iv TEXT NOT NULL,
    tag TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Platform Config Table (Snapshot store)
CREATE TABLE IF NOT EXISTS platform_config (
    config_key TEXT PRIMARY KEY, -- e.g. 'current'
    data JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
