CREATE DATABASE IF NOT EXISTS campusguide_fastapi
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE campusguide_fastapi;

CREATE TABLE IF NOT EXISTS feedback (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  feedback_id CHAR(36) NOT NULL,
  question_hash CHAR(64) NOT NULL,
  helpful TINYINT(1) NOT NULL,
  reasons JSON NULL,
  created_at DATETIME(3) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_feedback_id (feedback_id),
  KEY idx_feedback_question_hash (question_hash),
  KEY idx_feedback_created_at (created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ingestion_tasks (
  task_id CHAR(36) NOT NULL,
  source VARCHAR(255) NOT NULL,
  idempotency_key VARCHAR(128) NULL,
  kind VARCHAR(64) NOT NULL,
  status ENUM('queued', 'running', 'succeeded', 'failed') NOT NULL,
  attempts INT UNSIGNED NOT NULL DEFAULT 0,
  retry_count INT UNSIGNED NOT NULL DEFAULT 0,
  max_attempts INT UNSIGNED NOT NULL DEFAULT 2,
  recovered_after_restart TINYINT(1) NOT NULL DEFAULT 0,
  result JSON NULL,
  error JSON NULL,
  worker_id VARCHAR(96) NULL,
  lease_expires_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (task_id),
  UNIQUE KEY uq_ingestion_idempotency_key (idempotency_key),
  KEY idx_ingestion_status_updated (status, updated_at),
  KEY idx_ingestion_lease (status, lease_expires_at)
) ENGINE=InnoDB;

