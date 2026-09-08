-- Apply once to an existing MySQL deployment upgraded from schema.mysql.sql.
-- New installations receive this table from docs/schema.mysql.sql.
USE campusguide_fastapi;

CREATE TABLE IF NOT EXISTS agent_search_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_id CHAR(36) NOT NULL,
  request_id CHAR(36) NOT NULL,
  query_hash CHAR(64) NOT NULL,
  query_length SMALLINT UNSIGNED NOT NULL,
  result_count SMALLINT UNSIGNED NOT NULL,
  top_document_id VARCHAR(128) NULL,
  retrieval_mode VARCHAR(32) NOT NULL,
  duration_ms DECIMAL(12,3) NOT NULL DEFAULT 0,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_search_event_id (event_id),
  KEY idx_search_events_created_at (created_at),
  KEY idx_search_events_top_document (top_document_id)
) ENGINE=InnoDB;
