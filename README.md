# Project Job Mark1

Senior Big Tech (4–8 YoE) ATS Analyzer, Resume Tailoring Studio, and Multi-Format Exporter (`.pdf` & `.docx` in Phase 1; `.tex` in Phase 3).

## Quick Start

### 1. Run Backend Tests (`pytest`)
```powershell
.venv\Scripts\pytest.exe -v backend\tests
```

### 2. Run Backend API + Built Frontend (`http://127.0.0.1:8000`)
```powershell
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Run Frontend Dev Server (`http://localhost:5173`, optional HMR)
```powershell
npm --prefix frontend run dev
```

### 4. Configuration (`config/settings.yaml` <-> UI Two-Way Sync)
- Edit `config/settings.yaml` or `config/role_tracks/*.yaml` directly on disk **or** via the UI configuration bar; changes stay synchronized.
- Any `null` required fields automatically surface dropdown options in the UI.

### 5. Optional Local LLM (`Ollama` on RTX 5070 Ti)
```powershell
docker compose up -d ollama
docker exec -it job_mark1_ollama ollama pull qwen3:14b
```
