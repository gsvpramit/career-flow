# CareerFlow (Project Job Mark 1) — System Design, Architecture & Version Changelog

**Document Version:** 4.3  
**Last Updated:** November 2026  
**System Status:** Production Ready & Locally Serving on `http://127.0.0.1:8000`  
**Core Technologies:** Python 3.13, FastAPI, SQLite (WAL mode), SQLAlchemy 2.0, React 18, TypeScript, Vite, Tailwind-grade Dark Glass UI, Local Ollama LLM, Claude / Anthropic API, OpenPyXL, WeasyPrint, python-docx.

---

## 1. Executive System Overview & Architecture

CareerFlow is an end-to-end autonomous job intelligence and resume calibration platform designed for high-caliber engineers. It bridges the gap between active job postings (scraped from Greenhouse, Ashby, Lever, LinkedIn, and corporate ATS portals) and resume preparation.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 CAREERFLOW UI (React + Vite)                           │
│  Sessions & Jobs  │  Reports & Analytics  │  Skills Graph (Full-Width) │  Activity & Logs   │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ REST / JSON (HTTP)
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                               FASTAPI APPLICATION SERVER                               │
│  /api/sessions   │  /api/jobs/scrape   │  /api/tailor/preview   │  /api/reports/excel  │
└───────┬───────────────────┬─────────────────────────┬──────────────────────┬───────────┘
        │                   │                         │                      │
┌───────▼────────┐  ┌───────▼────────┐       ┌────────▼────────┐    ┌────────▼─────────┐
│ SQLite (WAL)   │  │ Batch Scraper  │       │ LLM Tailor &    │    │ Export Engine    │
│ job_mark1.db   │  │ ATS Parsers    │       │ Sanity Checker  │    │ PDF (WeasyPrint) │
│ Jobs, Resumes, │  │ Deduplication  │       │ Ollama + Claude │    │ DOCX & XLSX      │
│ Runs, Logs     │  │ Carry-Forward  │       │ 80-85% ATS Band │    │ OpenPyXL Styled  │
└────────────────┘  └────────────────┘       └─────────────────┘    └──────────────────┘
```

### Core Architecture Highlights
1. **Multi-Session Carry-Forward & Deduplication:** When new scraping sessions run, any job previously applied to, marked in progress, or actively engaged is carried forward with its complete progress history and tagged with `[Carried from Session X]`.
2. **Deterministic 80–85% ATS Calibration:** Avoids both under-qualification (<80%) and keyword stuffing (>85% penalty threshold) using weighted keyword scoring (`core_must_have` 3.0x, `important_systems` 2.0x, `bonus` 1.0x).
3. **Strict 100% Anti-Hallucination Guardrails:**
   - Company names, dates, titles, and locations are hard-locked.
   - Degrees, institutions, and GPAs are hard-locked.
   - Project titles are protected by regex filters preventing LLM from naming personal projects after the company applied to or target job title.
4. **Offline Resilient Multi-Engine Tailoring:** Dual selectable engines: `Local Ollama` (with model selection) and `Claude / Cloud AI` (high-caliber reasoning pipeline).

---

## 2. Version Evolution & Prompt History Changelog

| Version | Iteration / Prompt Focus | Key Enhancements Delivered | Code Modules Modified |
| :--- | :--- | :--- | :--- |
| **v1.0** | Initial Scraper & ATS Pipeline | Job ingestion, basic ATS scoring, keyword extraction, and session creation. | `batch_scraper.py`, `ats_scorer.py`, `models.py` |
| **v2.0** | Resume Studio & Sizing Controls | Markdown resume parser, WeasyPrint PDF export, seniority sizing, custom instructions. | `routes_resumes.py`, `tailor.py`, `ResumePanel.tsx` |
| **v2.5** | Real-World Sanity Verifier | 9-point sanity verification suite (employer lock, timeline plausibility, realistic metrics). | `sanity_checker.py`, `routes_jobs.py` |
| **v3.0** | Skills Graph & Excel Reports | D3-inspired SVG graph, domain clustering, multi-sheet openpyxl Excel reports with apply hyperlinks. | `skills_graph.py`, `excel_report.py`, `SkillsGraphPanel.tsx` |
| **v3.5** | Multi-Session Deduplication & Carry Forward | Carry-forward of applied and in-progress jobs across new sessions, unapplied filter chip. | `batch_scraper.py`, `SessionJobsWorkspace.tsx` |
| **v4.0** | Candidate Bullet Bank & Section Targeting | Intuit & Amazon candidate bullet bank, section targeting (`summary`, `experience`, `projects`, `skills`), anti-slop humanizer. | `CandidateBulletBankModal.tsx`, `llm_tailor.py` |
| **v4.1** | Activity & Diagnostics Logger | Dedicated top-level `Activity & Logs` tab, error toast capturing, JSON export, unread badges. | `activityLogger.ts`, `ActivityLogsPanel.tsx`, `App.tsx` |
| **v4.2** | UI Polish, Pinned Collapse & Claude Integration | 1) Pinned top-right collapse buttons on all cards. 2) Two strict tailoring options (`Local Ollama` vs `Claude / Cloud AI`). 3) Full-width skills graph with top inspector. 4) Auto-resizing textareas in Config without manual drag grips. 5) LocalStorage draft persistence on reload. 6) Flooded Technical Skills list with 35-45 authentic candidate skills. | `SessionJobsWorkspace.tsx`, `ConfigPanel.tsx`, `index.css`, `types.ts`, `llm_tailor.py`, `SkillsGraphPanel.tsx` |
| **v4.3** (Current) | Studio Single-Line Toolbar, Project Bullets & Responsive Polish | 1) Single-line horizontal Tailoring Studio controls. 2) Explicit `bullets_per_project` controls and dynamic bullet editor (+ Bullet, Remove). 3) AutoGrowTextarea border-buffer + ResizeObserver preventing scrollbars. 4) Responsive flex-wrapping card headers preventing title squishing. 5) Shortened card headings across all views. 6) Symmetrical Config grid with full-width Reset Workspace. 7) Collapsible and dismissible model benchmarks. 8) Master Excel export centralization. | `SessionJobsWorkspace.tsx`, `ConfigPanel.tsx`, `AutoGrowTextarea.tsx`, `tailor.py`, `routes_jobs.py`, `types.ts` |

---

## 3. Exhaustive UI Button & Control Dictionary

### A. Sessions Tab (`SessionJobsWorkspace.tsx`)

| Control Name | Type | Location | Functional Description |
| :--- | :--- | :--- | :--- |
| **⚡ Run Scrape Session** | Action Button | Top Header Bar | Executes batch scraper across selected job sources (Greenhouse, Ashby, Lever, LinkedIn) within selected freshness window. |
| **Session Dropdown** | Select Dropdown | Top Header Bar | Switches active viewing scope between historical scraping sessions. |
| **▸ Open Batch Generator** | Toggle Button | Top Header Bar | Expands the bulk resume generation drawer to tailor and export resumes for all saved jobs in batch. |
| **All / Ready / In Progress / Applied** | Filter Chips | Jobs Sidebar | Quick-filters the list of saved postings by recruitment stage. |
| **⚡ Skip Applied** | Filter Chip | Jobs Sidebar | Filters out any posting that has already been applied to or is in interview stages, focusing strictly on fresh opportunities. |
| **Sort By (Match %, Recency, etc.)** | Select Dropdown | Jobs Sidebar | Sorts posting cards by ATS Match Score, Published Date, YoE match, or Salary. |
| **Discard Job** | Action Button | Job Sidebar Card | Moves posting to Discarded bucket without deleting record; exempts it from future scrapers. |
| **Suitability Check Collapse** | Toggle Button | Job Header Alert | Collapses or expands the suitability audit alert. Pinned to the top-right corner. |
| **Align Skills in Studio →** | Action Button | Suitability Card | Directly merges all flagged missing technical skills into the Technical Skills section of the resume in Studio, turning green (`✓ Skills Aligned in Studio`). |
| **Tailoring Studio Collapse** | Toggle Button | Studio Header | Pinned top-right button to collapse or expand the entire Tailoring Studio card. |
| **Engine Dropdown** | Select Dropdown | Studio Action Bar | Selects active AI engine: strictly `Local Ollama` or `Claude / Cloud AI`. |
| **Model Dropdown** | Select Dropdown | Studio Action Bar | When `Local Ollama` is active, chooses among installed local models (`mistral-nemo`, `llama3.1`, etc.). |
| **Before / After Audit** | Toggle Button | Studio Action Bar | Opens an audit drawer showing exact before-and-after text diffs for every modified bullet and summary. |
| **Tailor, Humanize & Verify Resume** | Primary Action Button | Studio Action Bar | Triggers single-pass tailoring, humanization, sanity verification, and ATS calibration to 80–85%. |
| **⚡ Auto Seniority (6/6/5)** | Segmented Block | Length Controls | Automatically calculates page budget and bullets per role based on company YoE expectations. |
| **1.0 Page / 1.5 Pages / 2.0 Pages / 3.0 Pages** | Segmented Blocks | Length Controls | Manually sets the page budget; automatically re-calibrates bullet counts (`[4,3,2]`, `[5,4,3]`, `[6,6,5]`, `[8,7,6,5]`) and project counts. |
| **Sections to Tailor Checkboxes** | Checkboxes | Length Controls | Toggles which sections (`Summary`, `Experience`, `Projects`, `Technical Skills`) the AI is allowed to modify. Locked sections (`Education`, `Company Names & Dates`) remain immutable. |
| **Avoided AI Words** | Multi-Select Dropdown | Length Controls | Configures blocked vocabulary (e.g. *slashed*, *spearheaded*, *synergized*). |
| **Match City** | Checkbox | Length Controls | Automatically adapts resume contact header location to match target job city/state. |
| **+ Custom Prompt** | Toggle Button | Length Controls | Opens high-priority user instruction field to guide the AI for this specific job. |
| **Candidate Bullet Bank (+ From Bank)** | Modal Button | Experience / Projects | Opens modal containing verified authentic bullets from candidate's Intuit and Amazon background for 1-click insertion. |
| **Live Resume Sheet Collapse** | Toggle Button | Resume Sheet Header | Pinned top-right button to collapse the rendered paper resume preview. |
| **Download PDF / DOCX** | Action Buttons | Resume Sheet Header | Compiles and downloads formatted ATS-compliant PDF or DOCX file. |

---

### B. Skills Graph Tab (`SkillsGraphPanel.tsx`)

| Control Name | Type | Functional Description |
| :--- | :--- | :--- |
| **Scope Dropdown** | Select Dropdown | Filters the skills graph by specific scrape session or across all sessions. |
| **Refresh Graph** | Action Button | Rebuilds the graph topology, recalculating domain clusters and coverage numbers. |
| **All Domains Filter** | Select Dropdown | Isolates postings and skills within a single engineering domain (e.g., *Distributed Systems & Backend*). |
| **Coverage Filter** | Select Dropdown | Filters skills by *Missing From Base Resume* vs *Covered By Base Resume*. |
| **Search Box** | Text Input | Real-time filtering across company names, roles, domains, and skill keywords. |
| **Node Inspector & Config Sync** | Top Full-Width Banner | Displays selected node metrics; provides 1-click buttons (`+ Sync to Senior Software Engineer`) to add missing market skills directly into role track config. |
| **Full-Width Network Canvas** | SVG Diagram | Interactive 3-column network map spanning across the full page width: Role & Company &rarr; Domain Cluster &rarr; Demanded Skills. |

---

### C. Reports Tab (`ReportsPanel.tsx`)

| Control Name | Type | Functional Description |
| :--- | :--- | :--- |
| **Download Excel (.xlsx)** | Action Button | Generates and downloads a multi-sheet styled Excel report containing 5 sheets (*Overview & Sessions*, *Saved & Tracked Jobs*, *Applied Standing*, *Filtered & Seen Log*, *Skills Demand*) with clickable hyperlinks. |
| **Export HTML Report** | Action Button | Downloads self-contained standalone HTML analytics report with interactive charts. |
| **Application Pipeline Table** | Data Table | Real-time tracker for all jobs in `applied`, `screening`, `interviewing`, and `offer` states. |
| **Market Skill Gaps Table** | Data Table | Ranks missing competencies by market demand percentage, estimated ATS match lift, and priority tier. |

---

### D. Config Tab (`ConfigPanel.tsx`)

| Control Name | Type | Functional Description |
| :--- | :--- | :--- |
| **Save Settings** | Primary Action Button | Persists all global settings (filters, sources, LLM configuration) to disk. |
| **Role Track Selector** | Select Dropdown | Switches between role profiles (*Senior SWE*, *AI Engineer*, *Data Engineer*, etc.). |
| **Title Aliases** | Auto-Growing Textarea | Comma-separated list of equivalent job titles for scraping and matching. Dynamically resizes to content without manual resize handles. |
| **Core Must-Have Keywords (3.0x)** | Auto-Growing Textarea | Highest weighted skills for the role track; automatically expands without scrollbars. |
| **Important Systems Keywords (2.0x)** | Auto-Growing Textarea | Secondary systems skills weighted at 2.0x in ATS score calculations. |
| **Save Role Track** | Action Button | Persists role track YAML configurations immediately. |

---

### E. Activity & Logs Tab (`ActivityLogsPanel.tsx`)

| Control Name | Type | Functional Description |
| :--- | :--- | :--- |
| **Level Filters (All, Error, Warning, etc.)** | Filter Buttons | Filters event stream by severity level. |
| **Search Logs** | Text Input | Search events by message, context, or HTTP status codes. |
| **Export JSON** | Action Button | Downloads complete timestamped activity logs for diagnostic review. |
| **Clear Logs** | Action Button | Clears the in-memory and persisted event log. |

---

## 4. Model Comparison Matrix (Tailoring & Reasoning)

| Model Name | Type | Strengths | Trade-Offs / Limitations | Recommended Use Case |
| :--- | :--- | :--- | :--- | :--- |
| **`mistral-nemo:latest`** (12B) | Local Ollama | Exceptional JSON adherence, crisp active-voice verbs, strict metric realism, low latency (~1.8s). | Requires 8GB+ VRAM/RAM for optimal streaming. | **Primary Default** for fast, high-quality local resume tailoring. |
| **`llama3.1:latest`** (8B) | Local Ollama | Rich vocabulary, excellent domain understanding, strong multi-step reasoning. | Occasionally tends toward longer bullet lengths; requires strict character caps. | Ideal for Staff+ and architecture-heavy roles. |
| **`deepseek-coder-v2:latest`** | Local Ollama | Deep technical familiarity with frameworks, libraries, and precise system code semantics. | Slower generation speed on CPU; best on GPU. | Ideal for low-level systems, compiler, or infra roles. |
| **`gemma2:latest`** (9B) | Local Ollama | Very concise summaries, high factual grounding, zero cliché phrases. | Stricter prompt following; less expansive on project bullets. | Ideal for 1.0-page tight senior resumes. |
| **`phi3:medium`** (14B) | Local Ollama | Compact memory footprint, great logical structuring. | Slightly lower throughput compared to Mistral-Nemo. | Great fallback for resource-constrained local machines. |
| **`Claude 3.5 Sonnet`** | Cloud / API | World-class engineering voice, nuanced domain synthesis, optimal 80–85% ATS score calibration. | Requires active Internet / API Key (auto-fails over to high-caliber reasoning pipeline). | **Gold Standard** for executive, staff, and high-stakes job applications. |

---

## 5. Maintenance & Verification Playbook

### Running Locally (Without Docker)
```powershell
# 1. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 2. Run backend test suite (all 38 tests must pass)
pytest backend/tests/

# 3. Build frontend assets
npm --prefix frontend run build

# 4. Start local development server
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```
Application is immediately accessible at `http://127.0.0.1:8000`.
