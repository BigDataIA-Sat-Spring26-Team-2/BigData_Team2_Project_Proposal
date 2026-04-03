-- ============================================================
-- TABLE 1: faers_reports
-- Raw normalised FAERS records after Spark processing.
-- One row per adverse event case, joined from 5 source files.
-- ============================================================
CREATE TABLE faers_reports (
    report_id       BIGINT PRIMARY KEY,
    drug_name       TEXT NOT NULL,
    rxcui           TEXT,                    -- canonical RxNorm ID after normalization
    meddra_reaction TEXT NOT NULL,           -- MedDRA preferred term
    meddra_code     TEXT,                    -- MedDRA PT code
    serious         BOOLEAN DEFAULT FALSE,
    death           BOOLEAN DEFAULT FALSE,
    patient_age     INT,
    patient_sex     CHAR(1),                 -- M / F / U
    country         CHAR(2),                 -- ISO 3166 alpha-2
    receive_date    DATE,
    quarter_label   TEXT NOT NULL            -- e.g. '2023Q1'
);

CREATE INDEX idx_faers_drug     ON faers_reports (rxcui);
CREATE INDEX idx_faers_reaction ON faers_reports (meddra_code);
CREATE INDEX idx_faers_quarter  ON faers_reports (quarter_label);
CREATE INDEX idx_faers_drug_trgm ON faers_reports USING gin (drug_name gin_trgm_ops);


-- ============================================================
-- TABLE 2: drug_symptom_pairs
-- PRR and ROR computed by Spark over rolling 90-day windows.
-- Refreshed every 30 minutes by Spark Structured Streaming.
-- Central analytical output of the big data pipeline.
-- ============================================================
CREATE TABLE drug_symptom_pairs (
    pair_id         BIGSERIAL PRIMARY KEY,
    drug_name       TEXT NOT NULL,
    rxcui           TEXT,
    meddra_code     TEXT NOT NULL,
    meddra_reaction TEXT NOT NULL,
    count_a         INT NOT NULL,            -- drug X WITH symptom Y
    count_b         INT NOT NULL,            -- drug X WITHOUT symptom Y
    count_c         INT NOT NULL,            -- other drugs WITH symptom Y
    count_d         INT NOT NULL,            -- other drugs WITHOUT symptom Y
    prr_score       FLOAT NOT NULL,
    ror_score       FLOAT NOT NULL,
    ror_ci_lower    FLOAT NOT NULL,          -- 95% CI lower bound
    above_threshold BOOLEAN GENERATED ALWAYS AS (
                        prr_score >= 2.0 AND count_a >= 3
                    ) STORED,
    window_start    TIMESTAMP NOT NULL,
    window_end      TIMESTAMP NOT NULL,
    computed_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_pairs_drug ON drug_symptom_pairs (rxcui);
CREATE INDEX idx_pairs_above ON drug_symptom_pairs (above_threshold) WHERE above_threshold = TRUE;
CREATE INDEX idx_pairs_prr ON drug_symptom_pairs (prr_score DESC);
CREATE UNIQUE INDEX idx_pairs_unique ON drug_symptom_pairs (rxcui, meddra_code, window_start);


-- ============================================================
-- TABLE 3: signals
-- SSS composite score per detected signal.
-- Core analytical output — what agents and dashboard query.
-- ============================================================
CREATE TYPE severity_level AS ENUM ('WEAK', 'MODERATE', 'HIGH', 'CRITICAL');
CREATE TYPE hitl_status    AS ENUM ('AUTO_PUBLISHED', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'MODIFIED');

CREATE TABLE signals (
    signal_id       BIGSERIAL PRIMARY KEY,
    pair_id         BIGINT NOT NULL REFERENCES drug_symptom_pairs (pair_id),
    stat_score      NUMERIC(4,3) NOT NULL CHECK (stat_score BETWEEN 0 AND 1),
    lit_score       NUMERIC(4,3) NOT NULL CHECK (lit_score BETWEEN 0 AND 1),
    patient_score   NUMERIC(4,3) NOT NULL CHECK (patient_score BETWEEN 0 AND 1),
    trial_score     NUMERIC(4,3) NOT NULL CHECK (trial_score BETWEEN 0 AND 1),
    sss_composite   NUMERIC(4,3) NOT NULL CHECK (sss_composite BETWEEN 0 AND 1),
    severity_level  severity_level NOT NULL,
    safety_brief    JSONB,                   -- SafetyBrief JSON from Agent 3
    hitl_status     hitl_status DEFAULT 'PENDING_REVIEW',
    detected_at     TIMESTAMP DEFAULT NOW(),
    published_at    TIMESTAMP
);

CREATE INDEX idx_signals_pair       ON signals (pair_id);
CREATE INDEX idx_signals_severity   ON signals (severity_level);
CREATE INDEX idx_signals_hitl       ON signals (hitl_status);
CREATE INDEX idx_signals_detected   ON signals (detected_at DESC);
CREATE INDEX idx_signals_brief      ON signals USING gin (safety_brief);


-- ============================================================
-- TABLE 4: pubmed_abstracts
-- Raw PubMed text — source of truth for RAG corpus.
-- Embeddings stored in ChromaDB; PMID links the two stores.
-- ============================================================
CREATE TABLE pubmed_abstracts (
    pmid                TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    abstract_text       TEXT NOT NULL,
    journal             TEXT,
    pub_date            DATE,
    drug_name           TEXT,                -- drug this abstract was fetched for
    mesh_terms          TEXT[],              -- MeSH headings array
    indexed_in_chromadb BOOLEAN DEFAULT FALSE,
    indexed_at          TIMESTAMP
);

CREATE INDEX idx_pubmed_drug    ON pubmed_abstracts (drug_name);
CREATE INDEX idx_pubmed_date    ON pubmed_abstracts (pub_date DESC);
CREATE INDEX idx_pubmed_indexed ON pubmed_abstracts (indexed_in_chromadb) WHERE indexed_in_chromadb = FALSE;


-- ============================================================
-- TABLE 5: trial_adverse_events
-- Structured AE data from completed ClinicalTrials.gov studies.
-- Feeds trial_score component of SSS formula (weight 0.10).
-- ============================================================
CREATE TABLE trial_adverse_events (
    trial_ae_id     BIGSERIAL PRIMARY KEY,
    nct_id          TEXT NOT NULL,           -- ClinicalTrials.gov identifier
    drug_name       TEXT NOT NULL,
    ae_term         TEXT NOT NULL,
    ae_type         TEXT NOT NULL CHECK (ae_type IN ('SERIOUS', 'OTHER')),
    num_affected    INT NOT NULL,
    num_at_risk     INT NOT NULL,
    incidence_rate  FLOAT GENERATED ALWAYS AS (
                        CASE WHEN num_at_risk > 0
                        THEN num_affected::FLOAT / num_at_risk
                        ELSE 0 END
                    ) STORED
);

CREATE INDEX idx_trial_drug ON trial_adverse_events (drug_name);
CREATE INDEX idx_trial_nct  ON trial_adverse_events (nct_id);


-- ============================================================
-- TABLE 6: reddit_posts
-- Raw Reddit posts ingested via PRAW live stream.
-- Simple staging table — no scoring or aggregation.
-- Feeds patient_score component of SSS (weight 0.20).
-- PatientScore = 0 if this table is empty (graceful fallback).
-- ============================================================
CREATE TABLE reddit_posts (
    post_id         TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    body            TEXT,
    subreddit       TEXT NOT NULL,
    created_utc     TIMESTAMP NOT NULL,
    ingested_at     TIMESTAMP DEFAULT NOW(),
    matched_drugs   TEXT[]                   -- drug keywords matched in post text
);

CREATE INDEX idx_reddit_drug ON reddit_posts USING gin (matched_drugs);
CREATE INDEX idx_reddit_date ON reddit_posts (created_utc DESC);


-- ============================================================
-- TABLE 7: hitl_decisions
-- Immutable human reviewer decisions — full audit trail.
-- HIGH and CRITICAL signals blocked until row exists here.
-- ============================================================
CREATE TYPE hitl_decision AS ENUM ('APPROVE', 'REJECT', 'MODIFY');

CREATE TABLE hitl_decisions (
    decision_id       BIGSERIAL PRIMARY KEY,
    signal_id         BIGINT NOT NULL REFERENCES signals (signal_id),
    reviewer_id       TEXT NOT NULL,
    decision          hitl_decision NOT NULL,
    reviewer_notes    TEXT,
    modified_severity severity_level,        -- populated only when decision = MODIFY
    decided_at        TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_hitl_signal   ON hitl_decisions (signal_id);
CREATE INDEX idx_hitl_reviewer ON hitl_decisions (reviewer_id);
CREATE INDEX idx_hitl_decided  ON hitl_decisions (decided_at DESC);


-- ============================================================
-- TABLE 8: agent_traces
-- Every LLM agent call logged with tokens, cost, latency.
-- Powers /analytics/token-cost endpoint and Redis cost reports.
-- ============================================================
CREATE TABLE agent_traces (
    trace_id    BIGSERIAL PRIMARY KEY,
    signal_id   BIGINT NOT NULL REFERENCES signals (signal_id),
    agent_name  TEXT NOT NULL CHECK (agent_name IN ('agent1_detector', 'agent2_retriever', 'agent3_assessor')),
    model_used  TEXT NOT NULL DEFAULT 'claude-sonnet-4-5',
    total_tokens INT NOT NULL,
    cost_usd    NUMERIC(8,5) NOT NULL,
    latency_ms  INT NOT NULL,
    cache_hit   BOOLEAN DEFAULT FALSE,
    retry_count INT DEFAULT 0,               -- number of confidence retry loops
    called_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_traces_signal  ON agent_traces (signal_id);
CREATE INDEX idx_traces_agent   ON agent_traces (agent_name);
CREATE INDEX idx_traces_date    ON agent_traces (called_at DESC);
CREATE INDEX idx_traces_cost    ON agent_traces (cost_usd DESC);


-- ============================================================
-- TABLE 9: golden_signals
-- 10 historical known signals for evaluation.
-- Manually populated. Primary evaluation ground truth.
-- ============================================================
CREATE TABLE golden_signals (
    golden_id              BIGSERIAL PRIMARY KEY,
    drug_name              TEXT NOT NULL,
    symptom_name           TEXT NOT NULL,
    fda_communication_date DATE NOT NULL,    -- publicly documented FDA warning date
    medsignal_first_flag   DATE,             -- populated after evaluation run
    detection_lag_days     INT GENERATED ALWAYS AS (
                               CASE WHEN medsignal_first_flag IS NOT NULL
                               THEN fda_communication_date - medsignal_first_flag
                               ELSE NULL END
                           ) STORED,
    notes                  TEXT
);