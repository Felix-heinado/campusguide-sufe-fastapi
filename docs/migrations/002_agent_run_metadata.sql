USE campusguide_fastapi;

-- Existing local databases created before prompt/retrieval version tracking
-- need this one-time migration. Fresh installations already use schema.mysql.sql.
ALTER TABLE agent_runs
  ADD COLUMN metadata JSON NOT NULL AFTER error;
