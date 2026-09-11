-- Oregon water law RAG prototype: single-table schema.
-- Safe to run repeatedly.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sections (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    section_number text    NOT NULL UNIQUE,          -- e.g. "537.130"
    chapter        integer NOT NULL,                 -- e.g. 537
    heading        text    NOT NULL,
    text           text    NOT NULL,
    source_url     text    NOT NULL,
    edition        text,                             -- read from the chapter page, e.g. "2025 EDITION"
    allowed_groups text[]  NOT NULL DEFAULT '{}',    -- empty = public; otherwise must overlap the user's groups
    embedding      vector(384),                      -- BAAI/bge-small-en-v1.5, cosine
    fts            tsvector GENERATED ALWAYS AS (
                       to_tsvector('english', coalesce(heading, '') || ' ' || coalesce(text, ''))
                   ) STORED
);

-- Approximate nearest-neighbour over the embeddings (cosine).
CREATE INDEX IF NOT EXISTS sections_embedding_hnsw
    ON sections USING hnsw (embedding vector_cosine_ops);

-- Full-text search over heading + body.
CREATE INDEX IF NOT EXISTS sections_fts_gin
    ON sections USING gin (fts);
