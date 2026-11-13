# Project Job Mark1 — Requirements & System Design (v1.0 — Locked Decisions)

> **Status:** v1.0 Locked for Phase 1 implementation.
> **Core Principle:** Build and test simultaneously in thin, verifiable vertical slices—starting simple with clear UI feedback and expanding cleanly.

---

## 1. Vision & Problem Statement

Build a local-first web application (Frontend + Backend + Persistent Storage) that takes a target job posting URL (or raw JD text), analyzes what the role prioritizes (including experience level and salary range), scores your existing resume against Big Tech ATS & recruiter standards, helps you tailor a clean, truthful, human-sounding resume with live diff/score feedback, and exports `.pdf` and `.docx` (with `.tex` added in a later phase) into organized `output/` folders.

### Design Goals
1. **Big Tech Recruiter & ATS Ready:** Output adheres strictly to FAANG/MANG-grade single-column formatting, XYZ impact bullets, and zero parser-breaking tables/icons.
2. **Low-AI / High-Signal Pipeline:** Prefer deterministic NLP, structured rules, and explicit scoring over heavy opaque LLM generation. A local Dockerized LLM handles targeted reasoning (messy JD structuring, optional bullet reframing), gated by sanity checks, anti-AI-slop humanizing, and grammar validation.
3. **Human-in-the-Loop:** Immutable career facts (company names, titles, dates, degrees) stay locked. Tailoring selects/reframes work from a Master Experience Bank and clearly tags any suggested/adapted bullets for explicit user review before export.
4. **UI-First Configurability (Two-Way Sync):** Everything configurable in local config files is controllable via UI dropdowns/forms—and edits in either the UI or the local config file stay synchronized.
5. **Build-and-Test Incrementally:** Every module ships with runnable `pytest` tests and clear UI verification from Day 1.

---

## 2. End-to-End User Workflow

```text
[0. Config Check] Load config/settings.yaml
   ├─ Unset/missing defaults? ──► Surface UI setup banner + schema-driven dropdowns
   └─ Edits in UI ◄──two-way sync──► Edits in config/settings.yaml

[1. Job Input] URL or pasted JD text
       │
       ▼
[2. Scrape & Analyze] Extract company, role, YoE fit (4–8 yrs), salary range, weighted skills
       │              (using editable role keyword packs: Senior SWE, AI Engineer, FDE, ...)
       ▼
[3. Base Resume Check]
   ├─ Base resume / Master Experience Bank exists? ──► Load profile + extra context/resumes
   └─ Missing? ──► Prompt user to upload (.pdf / .docx / .tex) or build via guided web form
       │
       ▼
[4. Deterministic ATS Score & Gap Analysis]
   ├─ Score current resume against weighted JD skills & Senior Big Tech rubric
   └─ Show ranked gaps, missing keywords, salary fit, and weak/non-XYZ bullets
       │
       ▼
[5. Tailoring Studio (Live View)]
   ├─ Select/reorder from Experience Bank + optional local-LLM reframing
   ├─ Run Sanity Check + Humanizer + Grammar Check
   ├─ Live diff view (what changed/added) + Before vs. After Match Score
   └─ User approves, edits, or rejects every change
       │
       ▼
[6. Export & Persist]
   ├─ Phase 1: Generate .pdf + .docx (Phase 2/3 adds .tex + LaTeX compile)
   ├─ Run PDF text-extraction verification (ATS readability sanity check)
   └─ Save to output/<YYYY-MM-DD>_<Company>_<Role>_<short_id>/ + browser download
```

---

## 3. Functional Requirements

### 3.1 Job Scraping, Seniority & Salary Analysis
- **FR-1.1 Multi-Mode Input:** Accept a job posting URL **or** raw pasted job description text (fallback for login-gated, JS-heavy, or anti-bot sites like LinkedIn/Workday).
- **FR-1.2 Structured Extraction:** Extract job title, company, location/remote policy, YoE requirement (highlighting alignment with **4–8 years** target), responsibilities, required qualifications, and preferred qualifications.
- **FR-1.3 Compensation / Salary Extraction:** Parse listed salary / total-comp range (`salary_min`, `salary_max`, `currency`, `period`, equity/bonus notes) when available, and compare against user target salary in config.
- **FR-1.4 Weighted Skill & Keyword Extraction:**
  - Load extensible keyword packs per role track (`Senior SWE`, `AI Engineer`, `FDE`) from config files so extensive keyword lists can be added without code changes.
  - Weight signals into **Core / Must-Have**, **Important / Repeated**, and **Preferred / Bonus**, capturing both explicit tech keywords and expected engineering work patterns.
- **FR-1.5 Persistence:** Store scraped jobs, raw snapshots, compensation metadata, and weighted requirement breakdowns in SQLite.

### 3.2 Base Resume, Context Ingestion & Master Experience Bank
- **FR-2.1 Onboarding Check:** On job analysis, check if a base resume exists; if none, guide the user to upload one or create one directly in the web UI.
- **FR-2.2 Input Formats:**
  - Guided Web Resume Form backed by a canonical JSON Resume schema.
  - File upload for base `.pdf` / `.docx` (and `.tex` parsing) plus extra reference resumes or project notes as **Additional Context**.
- **FR-2.3 Master Experience Bank:** Store a superset of the candidate's real background:
  - **Locked Anchors:** Company names, titles, locations, employment dates, education.
  - **Bullet & Project Pool:** All real projects, systems built, metrics, and tech stacks done across roles (even details omitted from a 1-page base resume).

### 3.3 Big Tech Senior Recruiter & ATS Ruleset (4–8 YoE Focus)
Versioned in config (`config/rules/big_tech_rules.yaml`):
- **Layout & ATS Parseability:** Single-column only (no sidebars, tables, skill bars, or icon fonts), standard headings (`Education`, `Experience`, `Projects`, `Technical Skills`), selectable/searchable PDF text layer, clean 1-page default (with configurable 1–2 page option for 6–8 YoE scope).
- **Senior Signal (4–8 YoE):** Prioritize system design/architecture ownership, cross-team impact, production scale/SLAs, ambiguity resolution, and mentorship over junior task descriptions.
- **Google XYZ Formula:** Prefer *"Accomplished [X] as measured by [Y], by doing [Z]"* with strong action verbs and quantified impact.
- **Role Track Emphasis:**
  - **Senior SWE:** Distributed systems, scalability, reliability/SLOs, API/data modeling, CI/CD, architecture tradeoffs.
  - **AI Engineer:** LLM applications, RAG, agents, evals/guardrails, inference/serving latency & cost, fine-tuning, Python/PyTorch pipelines.
  - **Forward Deployed Engineer (FDE):** Client/stakeholder technical discovery, rapid production prototyping, messy real-world integrations, end-to-end delivery under ambiguity.

### 3.4 ATS Scoring, Gap Ranking & Live Tailoring View
- **FR-4.1 Transparent Score Breakdown (0–100):** Weighted keyword coverage, expected work/seniority alignment, XYZ/quantification quality, and ATS format/page-budget compliance.
- **FR-4.2 Ranked Gap List:** Missing or underrepresented skills sorted by JD weight, distinguishing true gaps from skills already present in your Experience Bank.
- **FR-4.3 Live Diff & Score Delta View:** Show inline changes (`Added / Reordered / Rephrased / Removed`), live **Before → After Score**, and bullet provenance tags (`VERIFIED_BASE`, `BANK_PULLED`, `REFRAMED`, `SUGGESTED_DRAFT`).

### 3.5 Lightweight Local AI, Sanity Check, Humanizer & Grammar Gate
- **FR-5.1 Local Dockerized LLM (`Ollama` on RTX 5070 Ti 16GB VRAM):**
  - Run an isolated `ollama/ollama` Docker container with `--gpus=all` exposing `http://localhost:11434`.
  - Best-fit open-source models for **16GB VRAM** (`Q4_K_M` leaving headroom for display + 8K context KV cache):
    - **Primary pick:** `qwen3:14b` (or `qwen2.5:14b`) — ~9 GB weights (~11–13 GB total VRAM), strong structured JSON adherence and technical reasoning without overflowing into system RAM.
    - **Alternative pick:** `gemma3:12b` — ~8.1–8.5 GB weights (~10–12 GB total VRAM), crisp, natural English phrasing.
  - **Deterministic Fallback:** `llm_mode: off` keeps scoring, ATS checks, and Experience Bank matching 100% runnable without GPU/API dependencies for fast unit testing.
- **FR-5.2 Integrity / Sanity Checks:** Block/flag any edit changing locked anchors (company, title, dates, degrees) or introducing ungrounded metrics/technologies without explicit approval.
- **FR-5.3 Humanizer & Grammar Gate:** Flag/strip AI clichés (*spearheaded, leveraged, cutting-edge, seamlessly, orchestrated*), verify consistent tense, and run automated grammar/punctuation checks before export.

### 3.6 Two-Way Synced Configuration System (`UI ◄──► Backend ◄──► Local File`)
- **FR-6.1 Canonical Config File:** Store runtime configuration in a human-readable local file (`config/settings.yaml`) and role keyword packs in `config/role_tracks/*.yaml`.
- **FR-6.2 Two-Way Synchronization:**
  - **File → Backend/UI:** Backend tracks file `mtime` (and reloads automatically on read/request or via reload endpoint) so editing `config/settings.yaml` on disk immediately reflects in backend behavior and the UI.
  - **UI → Backend → File:** Saving any setting in the UI sends `PUT /api/config`, validates types/enums via Pydantic, and atomically writes the updated `config/settings.yaml` back to disk.
- **FR-6.3 Schema-Driven Dropdowns for Missing Defaults:**
  - `GET /api/config` returns `{ values, schema_options, missing_defaults }`.
  - If a required setting is unset (`null` / omitted) in `config/settings.yaml` (e.g., `role_tracks`, `tailoring_policy`, `llm_mode`, `llm_model`, `export_formats`, `target_salary_min`), the UI automatically prompts the user with **dropdown selectors** populated by the backend schema so everything can be resolved directly from the UI.

### 3.7 Multi-Format Export & Output Storage
- **FR-7.1 Single Source of Truth Rendering:** Render outputs from the canonical JSON Resume model:
  - **Phase 1:** Clean single-column **`.pdf`** (pure-Python `ReportLab` or Playwright Chromium HTML-to-PDF) + **`.docx`** (`python-docx`), both ATS-verified.
  - **Phase 2/3:** Clean **`.tex`** (Jinja2 template) + local LaTeX compilation (e.g., Tectonic) replacing or complementing Phase 1 PDF generation.
- **FR-7.2 Folder Persistence:** Save every finalized run into:
  ```text
  output/
    <YYYY-MM-DD>_<company>_<role>_<short_id>/
      resume.pdf
      resume.docx
      # resume.tex (added in Phase 2/3)
      job_posting.json
      ats_report.json
      tailoring_diff.json
  ```
- **FR-7.3 Browser Downloads:** One-click download of individual files or bundled `.zip` from the UI, plus history browser for past generated folders.

---

## 4. Technical Architecture & Tradeoffs

### 4.1 Verified Local Environment
- **Available now:** `Python 3.13.15`, `git 2.55.0`, `Docker 29.8.1`, `NVIDIA GeForce RTX 5070 Ti (16303 MiB VRAM)`.
- **Not currently on `PATH`:** `node`, `pdflatex`, `xelatex`, `tectonic`, `pandoc`.

### 4.2 Locked Stack Decisions
- **Frontend:** **React + Vite + TypeScript** (requires Node.js LTS) — chosen to build clean stateful UI workflows (live diff, schema-driven config dropdowns, real-time ATS score gauge) without rewriting later.
- **Backend API:** **Python 3.13 + FastAPI + SQLite** — strict JSON REST API (`GET/PUT /api/config`, `/api/jobs`, `/api/resumes`, `/api/tailor`, `/api/export`) testable via `pytest`.
- **Phase 1 Export Engine:** **ReportLab** (lightweight, pure-Python, deterministic single-column selectable-text `.pdf`) + **`python-docx`** (`.docx`), keeping the canonical Resume JSON schema `.tex`-ready for Phase 2/3.
- **Role Keyword Packs:** Starter YAML keyword packs (`senior_swe.yaml`, `ai_engineer.yaml`, `fde.yaml`) editable in place or from the UI, ready for extensive custom keyword lists.

### 4.3 Proposed Repository Structure
```text
Project_Job_Mark1/
├── REQUIREMENTS.md
├── docker-compose.yml             # Optional local Ollama GPU service
├── config/
│   ├── settings.yaml              # Two-way synced user/runtime settings
│   ├── rules/
│   │   └── big_tech_rules.yaml    # Senior SWE/AI/FDE rubric & ATS checks
│   └── role_tracks/               # Editable keyword packs (senior_swe.yaml, ai_engineer.yaml, fde.yaml)
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI entrypoint
│   │   ├── services/
│   │   │   ├── config_manager.py  # Two-way YAML <-> Pydantic sync & schema options
│   │   │   ├── scraper.py         # URL scraper + salary/YoE parser + paste fallback
│   │   │   ├── jd_analyzer.py     # Weighted skill & work-expectation extractor
│   │   │   ├── resume_parser.py   # .pdf/.docx/form ingestion -> Canonical JSON & Bank
│   │   │   ├── ats_scorer.py      # Deterministic scorer & ranked gap analyzer
│   │   │   ├── llm_client.py      # Ollama Docker adapter + deterministic off-mode
│   │   │   ├── tailor.py          # Bullet selection/reframing + live diff + score delta
│   │   │   ├── humanizer.py       # Sanity check, anti-AI-slop, grammar check
│   │   │   └── exporter.py        # .pdf + .docx generator + output/ folder persistence
│   └── tests/                     # pytest unit & API tests built alongside every module
├── frontend/                      # React + Vite + TypeScript UI (Slice 3)
├── data/                          # SQLite DB + uploaded base resumes/context
└── output/                        # Per-job tailored output folders
```

---

## 5. Phased Build-and-Test Plan

- **Phase 1 — Vertical MVP (Build & Test Simultaneously):**
  - **Slice 1 (Now):** `config/` files (`settings.yaml`, `big_tech_rules.yaml`, `role_tracks/*.yaml`) + FastAPI `ConfigManager` two-way sync + SQLite schema + `pytest` verification.
  - **Slice 2:** Job URL/Paste scraper + salary/YoE (`4–8 yrs`) & weighted keyword analyzer + Base Resume CRUD/upload + Deterministic ATS Scorer + ReportLab `.pdf` & `python-docx` `.docx` exporter into `output/<folder>/` + `pytest` suite.
  - **Slice 3:** Node.js LTS setup + React/Vite/TS UI wired to all Phase 1 endpoints (schema-driven Config dropdowns, Job analyzer, Base Resume editor/upload, ATS score/gap view, `.pdf`/`.docx` download).
- **Phase 2 — Local Docker LLM + Tailoring Studio + Humanizer:**
  - `docker-compose.yml` for `ollama/ollama` (`qwen3:14b` / `gemma3:12b`) on RTX 5070 Ti.
  - Master Experience Bank (multiple resumes/context ingestion).
  - Live Diff View + Before/After Score + Humanizer/Grammar/Sanity checks + provenance approval toggles.
- **Phase 3 — `.tex` Generation & Advanced Polish:**
  - Jinja2 `.tex` renderer (Jake's Resume style + custom `.tex` template support) & LaTeX PDF compile.
  - Playwright JS-rendered job scraping + job application history dashboard.
