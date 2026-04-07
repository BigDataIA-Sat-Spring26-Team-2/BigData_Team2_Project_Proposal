# MedSignal — Drug Safety Signal Detection Platform

> **DAMG 7245 — Big Data and Intelligent Analytics | Northeastern University | Spring 2026**

MedSignal is a pharmacovigilance platform that detects drug safety signals from FDA FAERS adverse event data, retrieves supporting clinical literature from PubMed, and generates citation-grounded safety briefs using a three-agent LLM pipeline — compressing a process that takes human analysts hours into minutes.

**Artifacts:**
- Recording: [Watch on SharePoint](https://northeastern-my.sharepoint.com/:v:/g/personal/gupta_samik_northeastern_edu/IQCgJ-_kAEFMRrDcp7b7CD24AaBCUyK3Yo1PMsXTKgMQ9rc?nav=eyJyZWZlcnJhbEluZm8iOnsicmVmZXJyYWxBcHAiOiJTdHJlYW1XZWJBcHAiLCJyZWZlcnJhbFZpZXciOiJTaGFyZURpYWxvZy1MaW5rIiwicmVmZXJyYWxBcHBQbGF0Zm9ybSI6IldlYiIsInJlZmVycmFsTW9kZSI6InZpZXcifX0%3D&e=2pqdmB)
- Codelab: https://codelabs-preview.appspot.com/?file_id=1N3Qlxqajmn2oE1vrZrOXWtvcYoXdNeL78wEkplkGJoY#5

Artifacts:
Recording Link: [Watch on SharePoint](https://northeastern-my.sharepoint.com/:v:/g/personal/gupta_samik_northeastern_edu/IQCgJ-_kAEFMRrDcp7b7CD24AaBCUyK3Yo1PMsXTKgMQ9rc?nav=eyJyZWZlcnJhbEluZm8iOnsicmVmZXJyYWxBcHAiOiJTdHJlYW1XZWJBcHAiLCJyZWZlcnJhbFZpZXciOiJTaGFyZURpYWxvZy1MaW5rIiwicmVmZXJyYWxBcHBQbGF0Zm9ybSI6IldlYiIsInJlZmVycmFsTW9kZSI6InZpZXcifX0%3D&e=2pqdmB)

Codelab link: https://codelabs-preview.appspot.com/?file_id=1N3Qlxqajmn2oE1vrZrOXWtvcYoXdNeL78wEkplkGJoY#5
## The Problem

The FDA receives over 2 million adverse event reports annually through FAERS. The average time from when a signal first appears in that data to when the FDA officially communicates a safety warning can span months. During that window, patients continue to be exposed to preventable harm.

The Vioxx crisis (2004) is the canonical example: cardiovascular risk evidence existed in FAERS for years before the drug was withdrawn. More recently, 2023 saw FDA safety communications for gabapentin, pregabalin, GLP-1 receptor agonists, SGLT2 inhibitors, and dupilumab — signals that had been accumulating in reported data for months before formal communication.

The problem is not a lack of data. It is a lack of infrastructure to process it intelligently and route it to reviewers fast enough to matter.

---

## What It Does

```
FDA FAERS 2023 (4 quarters) ──► Kafka ──► Spark PRR Engine ──► Flagged Signals
                                                                       │
PubMed (1,800–1,930 abstracts) ──► ChromaDB ◄── Agent 2 (RAG) ◄───────┤
                                                                       │
                                                Agent 1 (StatScore) ◄──┘
                                                       │
                                                Agent 3 (SafetyBrief)
                                                       │
                                           Pydantic Validation
                                                       │
                                           HITL Review Queue (Streamlit)
```

1. **Spark ingests and processes** four quarters of 2023 FAERS data — 4-file join on `primaryid`, RxNorm drug normalisation, caseversion deduplication, PRR computation across all drug-reaction pairs
2. **Pairs above threshold** (PRR ≥ 2.0, A ≥ 50, C ≥ 200, drug_total ≥ 1,000) enter the LangGraph agent pipeline
3. **Agent 1** computes a StatScore from PRR magnitude, case volume, and FAERS outcome severity flags, then generates targeted PubMed search queries using GPT-4o
4. **Agent 2** performs semantic retrieval over ChromaDB (cosine similarity ≥ 0.60) and computes a LitScore
5. **Agent 3** synthesises all evidence into a structured SafetyBrief, assigns a priority tier, and validates output via Pydantic v2
6. **All flagged signals** are routed to the Streamlit HITL queue — no signal is approved, rejected, or escalated without a human reviewer decision

---

## Signal Severity Score

MedSignal combines two independent evidence streams into a priority tier for each signal:

```
StatScore = (prr_score × 0.50) + (volume_score × 0.30) + (severity_score × 0.20)

LitScore  = (relevance × 0.70) + (volume × 0.30)
```

StatScore and LitScore are presented independently to the reviewer. Weights for combining them into a single score are not applied — doing so requires pharmacovigilance domain expertise the team does not claim. The reviewer sees both scores transparently alongside the full SafetyBrief.

**Priority Tiers:**

| Tier | Condition | Reviewer Action |
|------|-----------|----------------|
| P1 | StatScore ≥ 0.7 AND LitScore ≥ 0.5 | Review first |
| P2 | StatScore ≥ 0.7 AND LitScore < 0.5 | Review second |
| P3 | StatScore < 0.7 AND LitScore ≥ 0.5 | Review third |
| P4 | StatScore < 0.7 AND LitScore < 0.5 | Review last |

---

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Message broker | Apache Kafka | Decouples FAERS file ingestion from Spark; enables future live-feed extension |
| Batch processing | Apache Spark (batch mode) | Parallel 4-file join, RxNorm normalisation, PRR aggregation across 5M+ rows |
| Relational storage | PostgreSQL | Drug-reaction pairs, flagged signals, safety briefs, HITL decisions |
| Vector store | ChromaDB | Local persistent store for 1,800–1,930 PubMed embeddings |
| Embeddings | all-MiniLM-L6-v2 (HuggingFace) | 384-dim embeddings, runs locally, zero API cost |
| Drug normalisation | NIH RxNorm API | Resolves drug name variants to canonical RxCUI — called once, cached in PostgreSQL |
| Agent framework | LangGraph | Typed Pydantic state machine across three agents |
| LLM | GPT-4o mini / GPT-4o (OpenAI) | Search query generation (Agent 1) and SafetyBrief synthesis (Agent 3) |
| Output validation | Pydantic v2 | Enforces SafetyBrief schema before any output reaches PostgreSQL |
| Frontend | Streamlit | Four-page analyst interface — signal feed, detail, HITL queue, evaluation dashboard |
| Containerisation | Docker Compose | Consistent environment across all team members; single-command startup |
| Observability | Prometheus | Pipeline metrics — messages processed, Spark job duration, HITL queue depth |

---

## Architecture

MedSignal is organised into five layers. Data moves top to bottom; no layer reaches back up to a layer above it.

![MedSignal System Architecture](./architecture.png)

> **GPT-4o** is called only in Agent 1 (query generation) and Agent 3 (SafetyBrief synthesis).
> **Agent 2** is fully deterministic — ChromaDB cosine similarity only, no LLM.

### Spark Processing Details

**Branch 1 — Join, Dedup, Normalise**
1. Deduplicate DEMO — keep highest `caseversion` per `caseid`
2. Filter DRUG to `role_cod = PS` only (22.74% of raw DRUG rows)
3. Normalise drug names via RxNorm cache broadcast join (fallback: `prod_ai` → `drugname`)
4. Aggregate OUTC flags per `primaryid` (death, hospitalisation, life-threatening)
5. Inner join DEMO + DRUG + REAC on `primaryid`; left join OUTC
6. Write `drug_reaction_pairs` to PostgreSQL (~5M rows for 2023)

**Branch 2 — PRR Computation**

```
PRR = (A / (A + B)) / (C / (C + D))

A = cases reporting drug X with reaction Y
B = cases reporting drug X without reaction Y
C = cases reporting any other drug with reaction Y
D = cases reporting any other drug without reaction Y
```

Thresholds: A ≥ 50, C ≥ 200, drug_total ≥ 1,000, PRR ≥ 2.0

Three quality filters applied after thresholding: junk MedDRA term filter, single-quarter spike filter (>70% of cases in one quarter), late-surge filter (>85% of cases in Q3–Q4).

---

## Data Sources

| Source | Volume | Role |
|--------|--------|------|
| FDA FAERS 2023 (Q1–Q4) | ~1.67M DEMO rows, ~7.47M DRUG rows (~2–3GB uncompressed) | Primary signal detection corpus |
| PubMed via NCBI Entrez API | ~1,800–1,930 abstracts across 10 golden drugs | RAG knowledge base for Agent 2 |
| NIH RxNorm API | One-time cache build | Drug name normalisation |

**FAERS files used:** DEMO, DRUG, REAC, OUTC. THER, INDI, and RPSR are excluded due to missingness or irrelevance to PRR computation.

---

## Golden Signal Validation Set

MedSignal is evaluated against ten drug-reaction pairs for which the FDA issued verified public safety communications during 2023.

| Drug | Reaction | FDA Communication |
|------|----------|------------------|
| Dupixent (dupilumab) | Skin fissures / eye inflammation | Label Update — January 2024 |
| Gabapentin | Cardiorespiratory arrest | Drug Safety Communication — December 2023 |
| Pregabalin | Coma | Drug Safety Communication — December 2023 |
| Keppra (levetiracetam) | Tonic-clonic seizure | Safety Communication — November 2023 |
| Mounjaro (tirzepatide) | Hunger / injection site | Drug Safety Communication — September 2023 |
| Ozempic (semaglutide) | Increased appetite | Drug Safety Communication — September 2023 |
| Jardiance (empagliflozin) | HbA1c increased | Drug Safety Communication — August 2023 |
| Bupropion | Seizure | Drug Safety Communication — May 2023 |
| Farxiga (dapagliflozin) | GFR decreased | Label Update — May 2023 |
| Metformin | Diabetic ketoacidosis | Drug Safety Communication — April 2023 |

Preliminary POC analysis identified detection lead times ranging from 13 days (metformin) to 291 days (dupilumab), with a median of approximately 175 days. The full pipeline will confirm or refine these estimates.

---

## Guardrails and HITL

**Input guards**
- Statistical threshold gate: signal must pass all four PRR thresholds and three quality filters before reaching the agent pipeline
- PRR validation checkpoint: `gabapentin × cardiorespiratory arrest` must appear in `signals_flagged` before any agents run; pipeline halts if it does not
- Agent 3 prompt constraint: model instructed not to introduce claims beyond provided abstract evidence

**Output guards**
- Pydantic v2 schema enforcement on every SafetyBrief before PostgreSQL write; retry once with stricter prompt on failure
- PMID citation validator: every PMID cited in `brief_text` must appear in the abstract set returned by Agent 2; unmatched PMIDs are removed before storage

**HITL Gate**

All flagged signals are routed to the HITL review queue without exception. There is no automated approval path. The reviewer sees the full SafetyBrief, StatScore, LitScore, PRR, case count, outcome counts, and retrieved PubMed abstracts before choosing:

| Decision | Meaning |
|----------|---------|
| Approve | Signal confirmed as valid, logged for reporting |
| Reject | Signal dismissed; reason recorded |
| Escalate | Signal requires further expert review |

Every decision is written as an immutable new row in `hitl_decisions` with a timestamp, providing a complete audit trail.

**What is never automated:** whether a signal represents genuine causation, whether it warrants regulatory action, whether a SafetyBrief is clinically accurate, or whether a signal should be reported to the FDA.

---

## Evaluation

### Pipeline Correctness Checkpoint

```sql
SELECT drug_name, meddra_reaction, prr_score, case_count_a
FROM   drug_symptom_pairs
WHERE  drug_name = 'finasteride'
AND    meddra_reaction ILIKE '%depress%'
ORDER  BY prr_score DESC
LIMIT  5;
-- Expected: prr_score ≈ 3.14
```

This query validates the 4-file join, caseversion deduplication, PS filter, RxNorm normalisation, and PRR formula in a single check. No agent pipeline work begins until it passes.

### KPIs

| KPI | Target |
|-----|--------|
| Golden signals correctly flagged above PRR threshold | ≥ 8 of 10 |
| Detection lead time | Positive (earlier than FDA communication) for each confirmed signal |
| Spark batch runtime (all four 2023 quarters) | < 3 hours on development machine |
| ChromaDB retrieval quality | ≥ 3 of 5 abstracts above cosine threshold 0.60 per golden drug |
| Citation fabrication rate | 0 hallucinated PMIDs in any published SafetyBrief |
| SafetyBrief quality rubric pass rate | Reported across all 10 golden signals |

### SafetyBrief Quality Rubric

| Criterion | Pass Condition |
|-----------|---------------|
| Signal identification | Brief correctly names the drug and reaction |
| Literature grounding | Every claim traceable to a provided abstract |
| Citation accuracy | All cited PMIDs present in the retrieved abstract set |
| Tier consistency | Recommended action consistent with assigned priority tier |

---

## Getting Started

### Prerequisites

- Docker Desktop (16 GB RAM recommended)
- Python 3.10+
- OpenAI API key

### Quick Start

```bash
# Clone the repository
git clone https://github.com/your-org/medsignal.git
cd medsignal

# Copy environment template
cp .env.example .env
# Add your OPENAI_API_KEY and NCBI_API_KEY to .env

# Start the full stack (Kafka, Spark, PostgreSQL, ChromaDB)
docker compose up -d

# Verify all services are healthy
docker compose ps

# Build RxNorm cache (one-time, ~5 min)
python scripts/build_rxnorm_cache.py

# Load PubMed abstracts into ChromaDB (one-time, ~10 min on CPU)
python scripts/load_pubmed.py

# Publish FAERS 2023 data to Kafka topics
python scripts/faers_prep.py --quarters 2023Q1 2023Q2 2023Q3 2023Q4

# Run Spark batch pipeline (Branch 1 + Branch 2)
spark-submit pipeline/spark/faers_pipeline.py

# Run agent pipeline on flagged signals
python agents/orchestrator.py

# Launch Streamlit interface
streamlit run app/main.py
```

### Environment Variables

```env
OPENAI_API_KEY=sk-...
POSTGRES_URL=postgresql://medsignal:medsignal@localhost:5432/medsignal
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
CHROMADB_PATH=./chroma_store
NCBI_API_KEY=...    # Optional — raises PubMed rate limit from 3 to 10 req/sec
```

---

## Project Structure

```mermaid
graph TD
    ROOT["📁 medsignal/"]

    ROOT --> PIPELINE["📁 pipeline/"]
    ROOT --> AGENTS["📁 agents/"]
    ROOT --> SCRIPTS["📁 scripts/"]
    ROOT --> APP["📁 app/"]
    ROOT --> MODELS["📁 models/"]
    ROOT --> TESTS["📁 tests/"]
    ROOT --> DOCKER["🐳 docker-compose.yml"]
    ROOT --> ENV["⚙️ .env.example"]
    ROOT --> README["📄 README.md"]

    PIPELINE --> KAFKA["📁 kafka/"]
    PIPELINE --> SPARK["📁 spark/"]
    KAFKA --> FAERS_PREP["📄 faers_prep.py\nRaw ASCII → four Kafka topics"]
    SPARK --> BRANCH1["📄 branch1_join.py\n4-file join · dedup · PS filter · RxNorm"]
    SPARK --> BRANCH2["📄 branch2_prr.py\nPRR computation · quality filters · checkpoint"]

    AGENTS --> A1["📄 agent1_detector.py\nStatScore + GPT-4o search queries"]
    AGENTS --> A2["📄 agent2_retriever.py\nChromaDB cosine retrieval + LitScore"]
    AGENTS --> A3["📄 agent3_assessor.py\nPriority tier + SafetyBrief + Pydantic"]
    AGENTS --> ORCH["📄 orchestrator.py\nLangGraph state machine"]

    SCRIPTS --> RX["📄 build_rxnorm_cache.py\nNIH RxNorm API → PostgreSQL cache"]
    SCRIPTS --> PUBMED["📄 load_pubmed.py\nNCBI Entrez → all-MiniLM-L6-v2 → ChromaDB"]

    APP --> MAIN["📄 main.py\nStreamlit entrypoint"]
    APP --> PAGES["📁 pages/"]
    PAGES --> P1["📄 signal_feed.py\nAll flagged signals ranked by tier"]
    PAGES --> P2["📄 signal_detail.py\nSafetyBrief · scores · PMIDs"]
    PAGES --> P3["📄 hitl_queue.py\nApprove · Reject · Escalate"]
    PAGES --> P4["📄 evaluation.py\nDetection lead time · precision-recall"]

    MODELS --> SCHEMA["📄 schemas.py\nPydantic SafetyBrief schema"]

    TESTS --> UNIT["📁 unit/\nPRR formula · dedup · PS filter\nStatScore · LitScore · priority tier\nPydantic retry logic"]
    TESTS --> INTEG["📁 integration/\nPipeline · ChromaDB · agents · HITL"]
    TESTS --> E2E["📁 e2e/\nFull pipeline on gabapentin sample\n→ PRR checkpoint"]

    style ROOT fill:#1e293b,color:#f8fafc,stroke:#334155
    style PIPELINE fill:#0f172a,color:#94a3b8,stroke:#1e3a5f
    style AGENTS fill:#0f172a,color:#94a3b8,stroke:#1e3a5f
    style SCRIPTS fill:#0f172a,color:#94a3b8,stroke:#1e3a5f
    style APP fill:#0f172a,color:#94a3b8,stroke:#1e3a5f
    style MODELS fill:#0f172a,color:#94a3b8,stroke:#1e3a5f
    style TESTS fill:#0f172a,color:#94a3b8,stroke:#1e3a5f
    style KAFKA fill:#172554,color:#93c5fd,stroke:#1d4ed8
    style SPARK fill:#172554,color:#93c5fd,stroke:#1d4ed8
    style PAGES fill:#172554,color:#93c5fd,stroke:#1d4ed8
    style UNIT fill:#14532d,color:#86efac,stroke:#16a34a
    style INTEG fill:#14532d,color:#86efac,stroke:#16a34a
    style E2E fill:#14532d,color:#86efac,stroke:#16a34a
    style A1 fill:#3b0764,color:#e9d5ff,stroke:#7c3aed
    style A2 fill:#3b0764,color:#e9d5ff,stroke:#7c3aed
    style A3 fill:#3b0764,color:#e9d5ff,stroke:#7c3aed
    style ORCH fill:#3b0764,color:#e9d5ff,stroke:#7c3aed
    style P1 fill:#431407,color:#fed7aa,stroke:#ea580c
    style P2 fill:#431407,color:#fed7aa,stroke:#ea580c
    style P3 fill:#431407,color:#fed7aa,stroke:#ea580c
    style P4 fill:#431407,color:#fed7aa,stroke:#ea580c
```

---

## Cost

| Activity | Model | Estimated Cost |
|----------|-------|---------------|
| Development runs (~20 runs, GPT-4o mini) | GPT-4o mini | ~$0.09 |
| Final evaluation run | GPT-4o | ~$0.16 |
| **Total estimated** | | **~$0.25** |

A hard spend limit of $10 is set on the OpenAI account before any pipeline run. All development runs use GPT-4o mini (~30× cheaper). GPT-4o is used only for the final evaluation run and demo. Token usage per call is logged to PostgreSQL via the OpenAI API `usage` field.

---

## Team

| Member | Role |
|--------|------|
| Samiksha Rajesh Gupta | Data Engineering Lead — FAERS pipeline, Kafka, Spark Branch 1, Agent 1, signal feed + evaluation dashboard |
| Prachi Ganpatrao Pradhan | LLM / Data Processing Lead — PostgreSQL schema, RxNorm cache, Spark Branch 2, Agent 2, signal detail page, SafetyBrief evaluation |
| Siddharth Rakesh Shukla | Infrastructure & Quality Lead — Kafka setup, ChromaDB + PubMed pipeline, Agent 3, HITL queue, unit tests, Prometheus |

---

## Limitations

- FAERS is a spontaneous reporting system — reports are not comprehensive, drug names are highly fragmented, and 38% of DEMO records are missing the event date field.
- MedSignal uses Kafka to replay historical FAERS quarterly files. This simulates a streaming architecture but is not true real-time ingestion from live feeds.
- PRR statistical significance is not causation. MedSignal is a detection and triage tool that accelerates human review — it does not replace clinical judgment.
- The HITL gate is not optional. No signal is published or acted upon without a qualified human decision.
- Non-English adverse event reports are out of scope.

---

## References

1. U.S. Food and Drug Administration. FDA Adverse Event Reporting System (FAERS). https://fis.fda.gov/extensions/FPD-QDE-FAERS/FPD-QDE-FAERS.html
2. Evans S.J.W. et al. (2001). Use of proportional reporting ratios (PRRs) for signal generation from spontaneous adverse drug reaction reports. *Pharmacoepidemiology and Drug Safety*, 10(6), 483–486.
3. Bate A. & Evans S.J.W. (2009). Quantitative signal detection using spontaneous ADR reporting. *Pharmacoepidemiology and Drug Safety*, 18(6), 427–436.
4. LangGraph Documentation — https://github.com/langchain-ai/langgraph
5. ChromaDB Documentation — https://www.trychroma.com
6. NCBI E-utilities API — https://www.ncbi.nlm.nih.gov/books/NBK25497/
7. NIH RxNorm API — https://rxnav.nlm.nih.gov/