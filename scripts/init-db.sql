-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create database if not exists (already created by POSTGRES_DB env var)
-- This script runs inside the career_planning database on first startup
