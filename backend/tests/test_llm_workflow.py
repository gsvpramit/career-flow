"""Tests for single-model Ollama status, 5-year XYZ bootstrapper, tailoring, and humanizer gate."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
import yaml
from fastapi.testclient import TestClient

from backend.app.config import ROLE_TRACKS_DIR, RULES_PATH
from backend.app.main import create_app
from backend.app.services.config_manager import ConfigManager

SAMPLE_AI_JOB_TEXT = """
Senior AI Engineer
Company: VectorScale Systems
Location: New York, NY (Hybrid)
Compensation: $195,000 - $250,000 base

Requirements:
- 5+ years of backend and AI engineering experience in Python and FastAPI.
- Production experience designing RAG pipelines, evals, embeddings, and Kubernetes serving.
- Experience optimizing LLM latency, structured output, and distributed caching with Redis.
"""


def _build_llm_test_app(
    tmp_path: Path,
    handler,
    llm_mode: str = "ollama_local",
    llm_model: str = "mistral-nemo:latest",
) -> tuple[TestClient, Path]:
    cfg_dir = tmp_path / "config"
    tracks_dir = cfg_dir / "role_tracks"
    rules_dir = cfg_dir / "rules"
    output_dir = tmp_path / "output"
    tracks_dir.mkdir(parents=True)
    rules_dir.mkdir(parents=True)

    for yaml_file in ROLE_TRACKS_DIR.glob("*.yaml"):
        shutil.copy(yaml_file, tracks_dir / yaml_file.name)
    shutil.copy(RULES_PATH, rules_dir / "big_tech_rules.yaml")

    settings_file = cfg_dir / "settings.yaml"
    settings_file.write_text(
        yaml.safe_dump(
            {
                "target_role_tracks": ["ai_engineer", "senior_swe"],
                "target_locations": ["New York, NY", "Remote"],
                "llm_mode": llm_mode,
                "llm_model": llm_model,
                "ollama_base_url": "http://localhost:11434",
                "export_formats": ["pdf", "docx"],
                "page_budget": 1,
                "strict_humanizer_gate": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    manager = ConfigManager(
        settings_path=settings_file,
        role_tracks_dir=tracks_dir,
        rules_path=rules_dir / "big_tech_rules.yaml",
    )
    app = create_app(
        config_manager=manager,
        db_path=tmp_path / "llm_test.db",
        output_dir_override=output_dir,
    )
    app.state.ollama_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return TestClient(app), settings_file


def test_llm_status_test_and_config_sync(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "mistral-nemo:latest"},
                        {"name": "llama3.1:latest"},
                    ]
                },
            )
        if request.url.path == "/api/generate":
            body = json.loads(request.content.decode("utf-8"))
            assert body["model"] == "mistral-nemo:latest"
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "status": "ready",
                            "formula": "Accomplished X as measured by Y, by doing Z",
                        }
                    )
                },
            )
        return httpx.Response(404)

    client, settings_file = _build_llm_test_app(tmp_path, handler)
    with client:
        status_resp = client.get("/api/config/llm/status")
        assert status_resp.status_code == 200
        st = status_resp.json()
        assert st["reachable"] is True
        assert st["model_installed"] is True
        assert st["recommended_model"] == "mistral-nemo:latest"
        assert "llama3.1:latest" in st["available_models"]

        test_resp = client.post("/api/config/llm/test", json={})
        assert test_resp.status_code == 200
        tr = test_resp.json()
        assert tr["ok"] is True
        assert tr["model"] == "mistral-nemo:latest"
        assert "Accomplished X" in tr["sample_output"]

        upd = client.put(
            "/api/config",
            json={
                "updates": {
                    "llm_mode": "ollama_local",
                    "llm_model": "llama3.1:latest",
                }
            },
        )
        assert upd.status_code == 200
        assert upd.json()["values"]["llm_mode"] == "ollama_local"
        disk = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
        assert disk["llm_model"] == "llama3.1:latest"


def test_bootstrap_generic_5yr_resume_with_llm_and_humanizer(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "mistral-nemo:latest"}]})
        if request.url.path == "/api/generate":
            # Deliberately emit banned AI-slop phrases to prove Stage 2 humanizer scrubs them
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "bullets": {
                                "boot_e1_b1": "Spearheaded a cutting-edge RAG service reducing latency by 45% (from 420ms to 230ms) across 1.1M daily requests by leveraging Python and Redis.",
                                "boot_e1_b2": "Revolutionized evaluation pipelines raising structured output accuracy from 74% to 96% by building automated FastAPI evals on Kubernetes.",
                            }
                        }
                    )
                },
            )
        return httpx.Response(500)

    client, _ = _build_llm_test_app(tmp_path, handler)
    with client:
        resp = client.post(
            "/api/resumes/bootstrap",
            json={
                "full_name": "Jordan Patel",
                "email": "jordan.patel@example.com",
                "location": "New York, NY",
                "role_track": "ai_engineer",
                "years_experience": 5,
                "focus_skills": ["Python", "RAG", "FastAPI"],
                "use_llm": True,
                "save_as_base": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["generation_mode"] == "ollama_llm"
        assert data["model_used"] == "mistral-nemo:latest"
        assert data["humanized_count"] >= 2

        resume = data["resume"]
        assert resume["is_base"] is True
        assert resume["role_track"] == "ai_engineer"
        first_bullet = resume["content"]["experience"][0]["bullets"][0]["text"]
        second_bullet = resume["content"]["experience"][0]["bullets"][1]["text"]

        # Banned AI slop words must be replaced cleanly while preserving XYZ numbers
        assert "spearheaded" not in first_bullet.lower()
        assert "cutting-edge" not in first_bullet.lower()
        assert "leveraging" not in first_bullet.lower()
        assert "45%" in first_bullet
        assert "revolutionized" not in second_bullet.lower()
        assert "96%" in second_bullet


def test_bootstrap_deterministic_fallback_when_ollama_unreachable(tmp_path: Path) -> None:
    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    client, _ = _build_llm_test_app(tmp_path, failing_handler)
    with client:
        status_resp = client.get("/api/config/llm/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["reachable"] is False

        resp = client.post(
            "/api/resumes/bootstrap",
            json={
                "full_name": "Taylor Kim",
                "role_track": "senior_swe",
                "years_experience": 5,
                "use_llm": True,
                "save_as_base": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["generation_mode"] == "deterministic_template"
        assert data["model_used"] is None
        exp = data["resume"]["content"]["experience"]
        assert len(exp) == 2
        assert any("%" in b["text"] for b in exp[0]["bullets"])


def test_tailor_preview_llm_humanize_score_draft_and_preservation(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "mistral-nemo:latest"}]})
        if request.url.path == "/api/generate":
            body = json.loads(request.content.decode("utf-8"))
            prompt_data = json.loads(body["prompt"])
            b1_id = prompt_data["existing_experiences"][0]["bullets"][0]["bullet_id"]
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "summary": None,
                            "rewrites": [
                                {
                                    "bullet_id": b1_id,
                                    "tailored_text": "Cut P99 inference latency by 41% across 2M daily RAG queries by building FastAPI workers, Redis caching, and automated evals on Kubernetes.",
                                }
                            ],
                            "humanizer_notes": [
                                "Sharpened P99 metric with RAG, FastAPI, evals, and Redis."
                            ],
                        }
                    )
                },
            )
        return httpx.Response(404)

    client, _ = _build_llm_test_app(tmp_path, handler)
    with client:
        ingest = client.post(
            "/api/jobs/ingest",
            json={
                "raw_text": SAMPLE_AI_JOB_TEXT,
                "role_track": "ai_engineer",
            },
        )
        assert ingest.status_code == 201
        job_id = ingest.json()["id"]

        res_create = client.post(
            "/api/resumes",
            json={
                "name": "Morgan Base",
                "role_track": "ai_engineer",
                "is_base": True,
                "content": {
                    "contact": {
                        "full_name": "Morgan Lee",
                        "email": "morgan@example.com",
                        "location": "Austin, TX",
                    },
                    "experience": [
                        {
                            "id": "exp_real",
                            "company": "Real Employer Inc.",
                            "title": "Software Engineer",
                            "location": "Austin, TX",
                            "start_date": "Jan 2021",
                            "end_date": "Present",
                            "bullets": [
                                {
                                    "id": "b_real_1",
                                    "text": "Spearheaded backend Python services to reduce latency by 40% across daily traffic.",
                                    "provenance": "VERIFIED_BASE",
                                    "approved": True,
                                    "tags": ["Python"],
                                }
                            ],
                        }
                    ],
                    "projects": [],
                    "education": [
                        {
                            "institution": "UT Austin",
                            "degree": "B.S. Computer Science",
                            "location": "Austin, TX",
                            "graduation_date": "May 2020",
                        }
                    ],
                    "skills": [{"category": "Core", "items": ["Python", "Docker"]}],
                },
            },
        )
        assert res_create.status_code == 201
        resume_id = res_create.json()["id"]

        prev = client.post(
            "/api/tailor/preview",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "adapt_location": True,
                "use_llm": True,
                "rehumanize": True,
            },
        )
        assert prev.status_code == 200
        body = prev.json()
        assert body["tailor_mode"] == "ollama_llm"
        assert body["model_used"] == "mistral-nemo:latest"
        assert body["tailored_score"] >= body["base_score"]

        # Strict preservation of employer, title, dates, and education
        tailored_exp = body["tailored_resume"]["experience"][0]
        assert tailored_exp["company"] == "Real Employer Inc."
        assert tailored_exp["title"] == "Software Engineer"
        assert tailored_exp["start_date"] == "Jan 2021"
        assert body["tailored_resume"]["contact"]["location"] == "New York, NY"

        # Standalone humanizer cleans multiple AI clichés and rotates >2 repeated leading verbs
        slop_resume = body["tailored_resume"]
        slop_resume["experience"][0]["bullets"] = [
            {
                "id": "h1",
                "text": "Built microservice APIs by leveraging cutting-edge holistic tooling.",
                "provenance": "REFRAMED",
                "approved": True,
                "tags": [],
            },
            {
                "id": "h2",
                "text": "Built payment workers for enterprise customers.",
                "provenance": "REFRAMED",
                "approved": True,
                "tags": [],
            },
            {
                "id": "h3",
                "text": "Built CI pipelines in order to speed up builds by 30%.",
                "provenance": "REFRAMED",
                "approved": True,
                "tags": [],
            },
        ]
        hum = client.post(
            "/api/tailor/humanize",
            json={"resume": slop_resume, "job_id": job_id, "use_llm": False},
        )
        assert hum.status_code == 200
        hum_data = hum.json()
        assert hum_data["changes_count"] >= 2
        bullets_out = [b["text"] for b in hum_data["resume"]["experience"][0]["bullets"]]
        assert "cutting-edge" not in bullets_out[0].lower()
        assert "holistic" not in bullets_out[0].lower()
        assert "in order to" not in bullets_out[2].lower()
        # 3rd "Built" opener should be rotated
        assert not bullets_out[2].startswith("Built ")

        score_draft = client.post(
            "/api/tailor/score-draft",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "draft_resume": body["tailored_resume"],
            },
        )
        assert score_draft.status_code == 200
        assert score_draft.json()["overall_score"] >= 0


def test_bootstrap_realistic_companies_ms_bs_projects_summary_and_bullets_count(tmp_path: Path) -> None:
    def offline_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Offline", request=request)

    client, _ = _build_llm_test_app(tmp_path, offline_handler)
    with client:
        resp = client.post(
            "/api/resumes/bootstrap",
            json={
                "full_name": "Pramit Ray",
                "location": "Seattle, WA",
                "role_track": "senior_swe",
                "years_experience": 5,
                "focus_skills": ["Java", "Spring Boot", "React", "AWS", "Kafka"],
                "bullets_per_experience": 6,
                "page_budget": 1.5,
                "use_llm": False,
                "save_as_base": True,
            },
        )
        assert resp.status_code == 201
        c = resp.json()["resume"]["content"]
        assert c["summary"] and len(c["summary"]) > 40
        assert c["experience"][0]["company"] == "Amazon"
        assert c["experience"][1]["company"] == "Quest Global"
        assert len(c["experience"][0]["bullets"]) == 6
        assert len(c["experience"][1]["bullets"]) == 6
        assert len(c["projects"]) >= 2
        assert len(c["education"]) == 2
        degrees = " | ".join(e["degree"] for e in c["education"])
        assert "Master" in degrees and "Bachelor" in degrees
        full_blob = json.dumps(c).lower()
        assert "slashed" not in full_blob


def test_avoided_words_config_and_deselect_permission(tmp_path: Path) -> None:
    def offline_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Offline", request=request)

    client, settings_file = _build_llm_test_app(tmp_path, offline_handler)
    with client:
        # 1. Config supports 1.5 page_budget, default_bullets_per_role, avoided_ai_words, and custom instructions
        cfg = client.put(
            "/api/config",
            json={
                "updates": {
                    "page_budget": 1.5,
                    "default_bullets_per_role": 6,
                    "avoided_ai_words": ["slashed", "utilized"],
                    "custom_tailor_instructions": "Focus on AWS and distributed systems.",
                }
            },
        )
        assert cfg.status_code == 200
        vals = cfg.json()["values"]
        assert vals["page_budget"] == 1.5
        assert vals["default_bullets_per_role"] == 6
        assert vals["avoided_ai_words"] == ["slashed", "utilized"]
        disk = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
        assert disk["page_budget"] == 1.5

        sample_resume = {
            "contact": {"full_name": "Case Test", "email": "case@example.com"},
            "summary": "Backend engineer using oauth2 and restful apis.",
            "experience": [
                {
                    "id": "e1",
                    "company": "Intuit",
                    "title": "Software Engineer 2",
                    "bullets": [
                        {
                            "id": "b1",
                            "text": "Slashed query latency by 30% using postgresql and spearheaded oauth2 migration.",
                            "provenance": "VERIFIED_BASE",
                            "approved": True,
                            "tags": [],
                        }
                    ],
                }
            ],
            "projects": [],
            "education": [],
            "skills": [{"category": "Core", "items": ["fastapi", "pytorch"]}],
        }

        # When user deselects 'spearheaded' from avoided_words (keeping only ['slashed']),
        # 'slashed' MUST still be cleaned while 'spearheaded' stays permitted.
        hum = client.post(
            "/api/tailor/humanize",
            json={
                "resume": sample_resume,
                "use_llm": False,
                "avoided_words": ["slashed"],
            },
        )
        assert hum.status_code == 200
        out_resume = hum.json()["resume"]
        out_bullet = out_resume["experience"][0]["bullets"][0]["text"]
        assert "slashed" not in out_bullet.lower()
        assert "spearheaded" in out_bullet.lower()
        assert "PostgreSQL" in out_bullet
        assert "OAuth2" in out_bullet
        assert out_resume["skills"][0]["items"] == ["FastAPI", "PyTorch"]


def test_full_jd_tailoring_hits_80_plus_preserves_locks_and_exports_section_flow(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "mistral-nemo:latest"}]})
        if request.url.path == "/api/generate":
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "summary": "Senior AI Engineer with 5+ years delivering Python, FastAPI, RAG, and Redis microservices on Kubernetes for VectorScale Systems.",
                            "experiences": [
                                {
                                    "experience_index": 0,
                                    "bullets": [
                                        "Engineered Python and FastAPI RAG retrieval pipelines backed by Redis caching on Kubernetes, cutting P99 latency across 1.2M daily requests.",
                                        "Built automated LLM evaluation harnesses and structured output validators integrating embeddings for production reliability.",
                                        "Owned AWS S3 and PostgreSQL data pipelines with Docker and GitHub Actions CI/CD across high-throughput distributed services.",
                                        "Collaborated with applied science teams to tune LLM inference latency and monitoring alerts across production clusters.",
                                    ],
                                }
                            ],
                            "projects": [
                                {
                                    "name": "VectorScale RAG & Evals Workbench",
                                    "tech_stack": ["Python", "FastAPI", "RAG", "Redis", "Kubernetes"],
                                    "link": "github.com/dev/rag-evals",
                                    "bullets": [
                                        "Built hybrid embeddings search and automated eval pipelines using Python, FastAPI, and Redis deployed on Kubernetes."
                                    ],
                                },
                                {
                                    "name": "Structured LLM Gateway",
                                    "tech_stack": ["Python", "LLM", "Embeddings", "Docker"],
                                    "link": "github.com/dev/llm-gateway",
                                    "bullets": [
                                        "Implemented deterministic JSON schema guardrails and distributed request batching for low-latency LLM serving."
                                    ],
                                },
                            ],
                            "skills": [
                                {"category": "Languages & APIs", "items": ["Python", "FastAPI", "SQL"]},
                                {"category": "AI & Infra", "items": ["RAG", "LLM", "Embeddings", "Redis", "Kubernetes", "Docker"]},
                            ],
                            "humanizer_notes": ["Tailored Summary, Experience, Projects, and Skills for VectorScale Systems."],
                        }
                    )
                },
            )
        return httpx.Response(404)

    client, _ = _build_llm_test_app(tmp_path, handler)
    with client:
        ingest = client.post(
            "/api/jobs/ingest",
            json={"raw_text": SAMPLE_AI_JOB_TEXT, "role_track": "ai_engineer"},
        )
        assert ingest.status_code == 201
        job_id = ingest.json()["id"]

        res_create = client.post(
            "/api/resumes",
            json={
                "name": "Locked Anchor Base",
                "role_track": "ai_engineer",
                "is_base": True,
                "content": {
                    "contact": {"full_name": "Jordan Rivera", "email": "jordan@example.com", "location": "Austin, TX"},
                    "summary": "Backend engineer.",
                    "experience": [
                        {
                            "id": "exp_1",
                            "company": "Locked Amazon Corp",
                            "title": "Software Development Engineer",
                            "location": "Seattle, WA",
                            "start_date": "Sep 2022",
                            "end_date": "Present",
                            "bullets": [
                                {
                                    "id": "b1",
                                    "text": "Maintained Java backend web services for internal teams.",
                                    "provenance": "VERIFIED_BASE",
                                    "approved": True,
                                    "tags": ["Java"],
                                }
                            ],
                        }
                    ],
                    "projects": [],
                    "education": [
                        {
                            "institution": "University at Buffalo, SUNY",
                            "degree": "Master of Science in Data Science",
                            "location": "Buffalo, NY",
                            "graduation_date": "Aug 2022",
                            "coursework": ["Machine Learning", "Distributed Systems"],
                        },
                        {
                            "institution": "State University of New York",
                            "degree": "B.S. in Computer Science",
                            "location": "Albany, NY",
                            "graduation_date": "May 2019",
                            "coursework": ["Algorithms", "Databases"],
                        },
                    ],
                    "skills": [{"category": "Languages", "items": ["Java"]}],
                },
            },
        )
        assert res_create.status_code == 201
        resume_id = res_create.json()["id"]

        prev = client.post(
            "/api/tailor/preview",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "adapt_location": True,
                "use_llm": True,
                "bullets_per_experience": 4,
                "page_budget": 1.5,
                "target_score": 80,
            },
        )
        assert prev.status_code == 200
        body = prev.json()
        assert body["tailored_score"] >= 80.0
        assert body["target_score_met"] is True
        assert body["page_budget"] == 1.5
        assert len(body["added_jd_skills"]) >= 3

        tr = body["tailored_resume"]
        assert len(tr["experience"][0]["bullets"]) == 4
        assert tr["experience"][0]["company"] == "Locked Amazon Corp"
        assert tr["experience"][0]["title"] == "Software Development Engineer"
        assert len(tr["education"]) == 2
        assert tr["education"][0]["institution"] == "University at Buffalo, SUNY"
        assert len(tr["projects"]) >= 2

        # Export to PDF & DOCX and verify exact section order:
        # Summary -> Experience -> Projects -> Technical Skills -> Education
        exp = client.post(
            "/api/export",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "tailored_resume": tr,
                "formats": ["pdf", "docx"],
                "page_budget": 1.5,
            },
        )
        assert exp.status_code == 201
        exp_data = exp.json()
        assert exp_data["pdf_text_verified"] is True

        docx_name = next(f for f in exp_data["generated_files"] if f.endswith(".docx"))
        from docx import Document

        doc = Document(str(Path(exp_data["output_folder"]) / docx_name))
        doc_text = "\n".join(p.text for p in doc.paragraphs).upper()
        idx_sum = doc_text.index("SUMMARY")
        idx_exp = doc_text.index("EXPERIENCE")
        idx_proj = doc_text.index("PROJECTS")
        idx_skills = doc_text.index("TECHNICAL SKILLS")
        idx_edu = doc_text.index("EDUCATION")
        assert idx_sum < idx_exp < idx_proj < idx_skills < idx_edu


def test_ollama_json_repair_compact_retry_and_ownership_80_plus(tmp_path: Path) -> None:
    """Verify malformed/truncated Ollama JSON is repaired, retries compactly, and hits >=80% even when only seniority signals miss."""
    from backend.app.services.llm_tailor import _repair_and_parse_json

    truncated = (
        '{"summary": "Forward Deployed AI Engineer with 5+ years delivering Python and TypeScript automations.",\n'
        '"experiences": [{"experience_index": 0, "bullets": ["Engineered Python workflows.",]}],\n'
        '"skills": [{"category": "Data", "items": ["spark", "azure"]}'
    )
    repaired = _repair_and_parse_json(truncated)
    assert repaired is not None
    assert "experiences" in repaired
    assert repaired["skills"][0]["items"] == ["spark", "azure"]

    calls = {"count": 0}

    def retry_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "mistral-nemo:latest"}]})
        if request.url.path == "/api/generate":
            calls["count"] += 1
            body = json.loads(request.content.decode("utf-8"))
            assert isinstance(body["format"], dict)  # Strict JSON schema sent
            assert body["options"]["num_ctx"] == 8192
            if calls["count"] == 1:
                # Simulate severely corrupted unparseable first response -> triggers compact retry
                return httpx.Response(200, json={"response": "not-json-at-all"})
            return httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {
                            "summary": "Forward Deployed AI Engineer with extreme ownership building Python and TypeScript customer workflows.",
                            "experiences": [
                                {
                                    "experience_index": 0,
                                    "bullets": [
                                        "Engineered Python and TypeScript customer integrations serving 1M+ workflows with end-to-end ownership.",
                                        "Fine-tuned LLM extraction pipelines reducing document processing errors by 38% across enterprise accounts.",
                                    ],
                                }
                            ],
                            "skills": [
                                {"category": "Languages", "items": ["Python", "TypeScript", "SQL"]},
                                {"category": "Data & Cloud", "items": ["spark", "azure", "Docker"]},
                            ],
                        }
                    )
                },
            )
        return httpx.Response(404)

    client, _ = _build_llm_test_app(tmp_path, retry_handler)
    with client:
        ingest = client.post(
            "/api/jobs/ingest",
            json={
                "raw_text": (
                    "Forward Deployed AI Engineer\nCompany: Fulcrum\nLocation: San Francisco, CA\n"
                    "Extreme ownership building customer AI automations in Python and TypeScript.\n"
                ),
                "role_track": "fde",
            },
        )
        assert ingest.status_code == 201
        job_id = ingest.json()["id"]

        boot = client.post(
            "/api/resumes/bootstrap",
            json={
                "full_name": "Alex Rivera",
                "role_track": "fde",
                "years_experience": 5,
                "use_llm": False,
                "save_as_base": True,
            },
        )
        assert boot.status_code == 201
        resume_id = boot.json()["resume"]["id"]

        prev = client.post(
            "/api/tailor/preview",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "use_llm": True,
                "bullets_per_experience": 5,
                "target_score": 80,
            },
        )
        assert prev.status_code == 200
        data = prev.json()
        assert data["tailor_mode"] == "ollama_llm"
        assert data["model_used"] == "mistral-nemo:latest"
        assert data["tailored_score"] >= 80.0
        assert data["target_score_met"] is True
        skills_flat = [s for cat in data["tailored_resume"]["skills"] for s in cat["items"]]
        assert "Spark" in skills_flat and "spark" not in skills_flat
        assert "Azure" in skills_flat and "azure" not in skills_flat


def test_multi_employer_bootstrap_with_variable_bullets_and_degrees(tmp_path: Path) -> None:
    """Verify multi-employer bootstrap supports custom timelines, variable bullets, 2+ projects, and Grad/Undergrad."""
    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    client, _ = _build_llm_test_app(tmp_path, failing_handler)
    with client:
        resp = client.post(
            "/api/resumes/bootstrap",
            json={
                "full_name": "Priya Nair",
                "email": "priya.nair@example.com",
                "location": "Seattle, WA",
                "role_track": "senior_swe",
                "years_experience": 7,
                "focus_skills": ["Python", "Kafka", "Kubernetes"],
                "employers": [
                    {
                        "company": "Stripe",
                        "title": "Senior Software Engineer",
                        "location": "Seattle, WA",
                        "start_date": "Feb 2023",
                        "end_date": "Present",
                        "bullets_count": 6,
                    },
                    {
                        "company": "Datadog",
                        "title": "Software Engineer II",
                        "location": "New York, NY",
                        "start_date": "Jan 2021",
                        "end_date": "Jan 2023",
                        "bullets_count": 5,
                    },
                    {
                        "company": "Oracle",
                        "title": "Software Engineer",
                        "location": "Austin, TX",
                        "start_date": "Jul 2019",
                        "end_date": "Dec 2020",
                        "bullets_count": 4,
                    },
                ],
                "graduate_degree": "Master of Science in Computer Science",
                "undergrad_degree": "Bachelor of Science in Software Engineering",
                "projects_count": 3,
                "page_budget": 2,
                "use_llm": False,
                "save_as_base": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["generation_mode"] == "deterministic_template"
        content = data["resume"]["content"]
        assert [e["company"] for e in content["experience"]] == ["Stripe", "Datadog", "Oracle"]
        assert [len(e["bullets"]) for e in content["experience"]] == [6, 5, 4]
        assert len(content["projects"]) == 3
        assert len(content["education"]) == 2
        degrees = {e["degree"] for e in content["education"]}
        assert "Master of Science in Computer Science" in degrees
        assert "Bachelor of Science in Software Engineering" in degrees


def test_fallback_reasoning_script_80_85_band_and_sanity_checks(tmp_path: Path) -> None:
    """Verify fallback_script tailors Summary/Experience/Projects/Skills into 80-85% band with reasoning steps and sanity checks."""
    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    client, _ = _build_llm_test_app(tmp_path, failing_handler)
    with client:
        ingest = client.post(
            "/api/jobs/ingest",
            json={
                "raw_text": (
                    "Senior Backend & AI Engineer\n"
                    "Company: Stripe\n"
                    "Location: Seattle, WA (Hybrid)\n"
                    "Requirements:\n"
                    "- 6-8 years experience building distributed APIs with Python, Go, Kafka, and PostgreSQL.\n"
                    "- Experience with FastAPI, Docker, Kubernetes, Redis, OpenTelemetry, and CI/CD.\n"
                    "- Own high-throughput payment webhooks, observability, and RAG evaluation pipelines.\n"
                ),
                "role_track": "senior_swe",
            },
        )
        assert ingest.status_code == 201
        job_id = ingest.json()["id"]

        boot = client.post(
            "/api/resumes/bootstrap",
            json={
                "full_name": "Alex Rivera",
                "role_track": "senior_swe",
                "years_experience": 7,
                "employers": [
                    {
                        "company": "Amazon",
                        "title": "Senior Software Engineer",
                        "location": "Seattle, WA",
                        "start_date": "Jan 2022",
                        "end_date": "Present",
                        "bullets_count": 5,
                    },
                    {
                        "company": "Intuit",
                        "title": "Software Engineer II",
                        "location": "San Diego, CA",
                        "start_date": "Jan 2020",
                        "end_date": "Dec 2021",
                        "bullets_count": 5,
                    },
                ],
                "use_llm": False,
                "save_as_base": True,
            },
        )
        assert boot.status_code == 201
        resume_id = boot.json()["resume"]["id"]

        score_resp = client.post("/api/jobs/score", json={"job_id": job_id, "resume_id": resume_id})
        assert score_resp.status_code == 200
        score_data = score_resp.json()
        assert len(score_data["resume_skills"]) >= 4
        assert len(score_data["missing_requirements"]) >= 1

        prev_resp = client.post(
            "/api/tailor/preview",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "tailor_strategy": "fallback_script",
                "auto_size": True,
                "rehumanize": True,
                "target_score_min": 80,
                "target_score_max": 85,
            },
        )
        assert prev_resp.status_code == 200
        prev = prev_resp.json()
        assert prev["tailor_mode"] == "fallback_script"
        assert prev["page_budget"] == 2.0  # 6-8 YoE senior role auto-selects 2 pages
        assert len(prev["bullets_per_role_counts"]) == 2
        assert prev["bullets_per_role_counts"][0] >= 6
        assert 80.0 <= prev["tailored_score"] <= 85.0
        assert prev["in_target_band"] is True
        assert prev["sanity_passed"] is True
        assert len(prev["reasoning_steps"]) >= 3
        assert len(prev["sanity_checks"]) >= 4
        assert [e["company"] for e in prev["tailored_resume"]["experience"]] == ["Amazon", "Intuit"]
        assert len(prev["tailored_resume"]["projects"]) >= 2


def test_sanity_checker_flags_anachronistic_tech_and_repairs_metrics() -> None:
    """Verify sanity_checker auto-repairs anachronistic pre-release tech + inflated percentages and flags blocked words."""
    from backend.app.schemas.job import ATSReport, JobAnalysis
    from backend.app.schemas.resume import (
        CanonicalResume,
        ContactInfo,
        EducationItem,
        ExperienceBullet,
        ExperienceItem,
        ProjectItem,
        SkillCategory,
    )
    from backend.app.services.sanity_checker import run_resume_sanity_check

    base = CanonicalResume(
        contact=ContactInfo(full_name="Test User", email="t@example.com", location="Austin, TX"),
        summary="Experienced backend engineer delivering distributed systems.",
        experience=[
            ExperienceItem(
                id="e1",
                company="Acme Corp",
                title="Software Engineer",
                location="Austin, TX",
                start_date="Jan 2011",
                end_date="Dec 2012",
                bullets=[
                    ExperienceBullet(
                        id="b1",
                        text="Slashed deployment overhead with 999% reduction by deploying Kubernetes clusters across production services.",
                        provenance="SUGGESTED_DRAFT",
                    )
                ],
            )
        ],
        projects=[
            ProjectItem(id="p1", name="API Engine", tech_stack=["Python"], bullets=[]),
            ProjectItem(id="p2", name="Queue Worker", tech_stack=["Redis"], bullets=[]),
        ],
        skills=[SkillCategory(category="Languages", items=["Python", "SQL"])],
        education=[
            EducationItem(
                institution="UT Austin",
                degree="B.S. Computer Science",
                location="Austin, TX",
                graduation_date="May 2010",
            )
        ],
    )
    cleaned, checks, passed, summary = run_resume_sanity_check(
        base_resume=base,
        tailored_resume=base,
        job=JobAnalysis(title="Software Engineer", company="Acme Corp"),
        tailored_report=ATSReport(
            job_id=0,
            resume_id=0,
            overall_score=82.5,
            sub_scores={"skills": 82.5},
            estimated_pages=1,
        ),
        avoided_words=["slashed"],
        target_score_min=80,
        target_score_max=85,
    )
    bullet_text = cleaned.experience[0].bullets[0].text
    assert "kubernetes" not in bullet_text.lower()
    assert "999%" not in bullet_text
    era_check = next(c for c in checks if c.check_id == "timeline_era")
    assert era_check.status == "repaired"
    slop_check = next(c for c in checks if c.check_id == "avoided_words")
    assert slop_check.status == "warning"
    assert passed is False
    assert "auto-repaired" in summary.lower()


def test_sparse_two_skill_jd_calibrates_within_80_85_and_skips_logistics_summary(tmp_path: Path) -> None:
    """Verify sparse 2-skill JDs land cleanly inside 80-85% and summary/expected_work never include logistics prose."""
    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    client, _ = _build_llm_test_app(tmp_path, failing_handler)
    with client:
        res_resp = client.post(
            "/api/resumes/bootstrap",
            json={
                "role_track": "fde",
                "years_experience": 5,
                "use_llm": False,
                "save_as_base": True,
                "employers": [
                    {"company": "Amazon", "title": "Forward Deployed Engineer", "location": "San Francisco, CA", "start_date": "Sep 2023", "end_date": "Present", "bullets_count": 5},
                    {"company": "Intuit", "title": "Solutions Engineer", "location": "San Diego, CA", "start_date": "Jan 2021", "end_date": "Aug 2023", "bullets_count": 4},
                ],
            },
        )
        assert res_resp.status_code == 201
        resume_id = res_resp.json()["resume"]["id"]

        jd_text = (
            "Forward Deployed Engineer - Life Sciences\n"
            "Acme AI\n"
            "San Francisco, CA\n"
            "About the role\n"
            "This role is based in San Francisco. We use a hybrid work model of 3 days in the office per week. We offer relocation assistance. Travel up to 50% is required.\n"
            "Design and ship production software systems with strong reliability, system design, architecture, and ownership.\n"
            "Requirements\n"
            "- 5+ years of experience delivering enterprise software with security and system design.\n"
        )
        job_resp = client.post("/api/jobs/ingest", json={"raw_text": jd_text})
        assert job_resp.status_code == 201
        job_data = job_resp.json()
        job_id = job_data["id"]
        assert all(
            "hybrid work model" not in w.lower() and "relocation assistance" not in w.lower()
            for w in job_data["analysis"]["expected_work"]
        )

        prev_resp = client.post(
            "/api/tailor/preview",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "tailor_strategy": "fallback_script",
                "target_score_min": 80,
                "target_score_max": 85,
            },
        )
        assert prev_resp.status_code == 200
        prev = prev_resp.json()
        assert 80.0 <= prev["tailored_score"] <= 85.0
        assert prev["in_target_band"] is True
        summary = (prev["tailored_resume"].get("summary") or "").lower()
        assert "hybrid work model" not in summary
        assert "relocation assistance" not in summary
        assert "travel up to" not in summary





