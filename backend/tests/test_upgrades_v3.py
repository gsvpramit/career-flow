"""Tests for per-section prompt tailoring, heavy 5y curation, Ollama benchmark, standing reports, Excel export, and Skills Graph."""

from __future__ import annotations

import io
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx
import openpyxl
import yaml
from fastapi.testclient import TestClient

from backend.app.config import ROLE_TRACKS_DIR, RULES_PATH
from backend.app.main import create_app
from backend.app.schemas.job import JobAnalysis, WeightedSkill
from backend.app.schemas.resume import (
    CanonicalResume,
    ContactInfo,
    EducationItem,
    ExperienceBullet,
    ExperienceItem,
    ProjectItem,
    SkillCategory,
)
from backend.app.services.config_manager import ConfigManager
from backend.app.services.llm_tailor import (
    _TAILOR_COMPACT_SCHEMA,
    _dedupe_skill_categories,
    _repair_and_parse_json,
    normalize_tech_capitalization,
)
from backend.app.services.reasoning_tailor import curate_heavy_resume_sections


def _build_v3_app(
    tmp_path: Path,
    handler=None,
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
                "target_locations": ["New York, NY", "San Francisco, CA"],
                "llm_mode": "ollama_local",
                "llm_model": llm_model,
                "ollama_base_url": "http://localhost:11434",
                "export_formats": ["pdf", "docx"],
                "page_budget": 1.5,
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
        db_path=tmp_path / "v3_test.db",
        output_dir_override=output_dir,
    )
    if handler is not None:
        app.state.ollama_http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return TestClient(app), settings_file


def _seed_job_and_base_resume(client: TestClient) -> tuple[int, int, dict]:
    job_resp = client.post(
        "/api/jobs/ingest",
        json={
            "title_override": "Senior Data & AI Systems Engineer",
            "company_override": "Stripe",
            "role_track": "senior_swe",
            "raw_text": (
                "Senior Data & AI Systems Engineer at Stripe\n"
                "Location: San Francisco, CA\n"
                "Compensation: $205,000 - $265,000 base.\n"
                "Requirements:\n"
                "- 5+ years of production Python, Apache Spark, Kafka, FastAPI, and PostgreSQL experience.\n"
                "- Build low-latency RAG pipelines, OpenTelemetry tracing, and Kubernetes services.\n"
                "- H-1B sponsorship available for qualified candidates."
            ),
        },
    )
    assert job_resp.status_code == 201
    job_id = job_resp.json()["id"]

    boot_resp = client.post(
        "/api/resumes/bootstrap",
        json={
            "full_name": "Alex Rivera",
            "email": "alex.rivera@example.com",
            "location": "San Francisco, CA",
            "role_track": "senior_swe",
            "years_experience": 5,
            "focus_skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"],
            "use_llm": False,
            "save_as_base": True,
            "undergrad_degree": "B.S. in Computer Science, UC Berkeley",
            "graduate_degree": "M.S. in Computer Science, NYU",
            "projects_count": 2,
        },
    )
    assert boot_resp.status_code == 201
    resume_obj = boot_resp.json()["resume"]
    return job_id, resume_obj["id"], resume_obj["content"]


def test_heavy_curation_capitalization_dedupe_and_schema() -> None:
    assert "projects" in _TAILOR_COMPACT_SCHEMA.get("required", [])
    assert "projects" in _TAILOR_COMPACT_SCHEMA.get("properties", {})

    repaired = _repair_and_parse_json('{"summary": "hello"\n"skills": [{"category": "Lang", "items": ["Python"]}]}')
    assert repaired is not None
    assert repaired["summary"] == "hello"

    assert normalize_tech_capitalization("spark") == "Spark"
    assert normalize_tech_capitalization("data pipelines") == "Data Pipelines"
    assert normalize_tech_capitalization("opentelemetry") == "OpenTelemetry"

    heavy_resume = CanonicalResume(
        contact=ContactInfo(full_name="Alex Rivera", location="New York, NY"),
        summary="Senior backend engineer with 6 years building distributed systems.",
        experience=[
            ExperienceItem(
                id="e1",
                company="Scale Labs",
                title="Senior SWE",
                location="New York, NY",
                start_date="Jan 2022",
                end_date="Present",
                bullets=[
                    ExperienceBullet(id="b1", text="Built high-throughput Python and FastAPI microservices handling 40k RPS.", approved=True)
                ],
            )
        ],
        projects=[
            ProjectItem(
                id="p1",
                name="Realtime Ledger Engine",
                tech_stack=["Python", "Kafka", "Docker"],
                bullets=[ExperienceBullet(id="pb1", text="Built idempotent event consumer in Python.", approved=True)],
            ),
            ProjectItem(
                id="p2",
                name="Frontend Color Toy",
                tech_stack=["HTML", "CSS", "Figma"],
                bullets=[ExperienceBullet(id="pb2", text="Styled static landing mockup.", approved=True)],
            ),
            ProjectItem(
                id="p3",
                name="Spark Batch Orchestrator",
                tech_stack=["Spark", "AWS"],
                bullets=[ExperienceBullet(id="pb3", text="Processed batch aggregations on Spark and AWS.", approved=True)],
            ),
        ],
        skills=[
            SkillCategory(category="Languages", items=["Python", "SQL", "TypeScript", "Go"]),
            SkillCategory(category="Data & Cloud", items=["spark", "Kafka", "AWS", "Docker", "Kubernetes", "Redis"]),
            SkillCategory(category="Frontend", items=["React", "Next.js", "CSS", "jQuery", "Tailwind", "Figma", "PHP", "Perl"]),
        ],
        education=[
            EducationItem(institution="NYU", degree="M.S. CS", graduation_date="2019", gpa="3.8")
        ],
    )

    deduped = _dedupe_skill_categories(
        [
            SkillCategory(category="Frameworks", items=["Spark", "FastAPI", "spark"]),
            SkillCategory(category="Data", items=["spark", "Kafka"]),
        ]
    )
    all_deduped = [i for c in deduped for i in c.items]
    assert [x.lower() for x in all_deduped].count("spark") == 1
    assert "Spark" in all_deduped

    weighted = [
        WeightedSkill(keyword="Python", tier="core_must_have", priority_label="Must-Have", weight=3.0, jd_mentions=3),
        WeightedSkill(keyword="Spark", tier="core_must_have", priority_label="Must-Have", weight=3.0, jd_mentions=2),
        WeightedSkill(keyword="Kafka", tier="core_must_have", priority_label="Must-Have", weight=3.0, jd_mentions=2),
        WeightedSkill(keyword="FastAPI", tier="important_systems", priority_label="Important", weight=2.0, jd_mentions=1),
        WeightedSkill(keyword="Kubernetes", tier="important_systems", priority_label="Important", weight=2.0, jd_mentions=1),
    ]
    job_obj = JobAnalysis(
        company="Stripe",
        title="Senior Backend & Data Engineer",
        location="San Francisco, CA",
        role_track="senior_swe",
        weighted_skills=weighted,
    )
    curated_resume, pruned_skills, _ = curate_heavy_resume_sections(
        draft=heavy_resume,
        job=job_obj,
        normalize_fn=normalize_tech_capitalization,
        max_skills_total=12,
        max_projects=2,
    )
    flat_skills = {item for cat in curated_resume.skills for item in cat.items}
    assert {"Python", "AWS", "Docker"}.issubset(flat_skills)
    assert "Spark" in flat_skills
    assert "PHP" not in flat_skills
    assert len(curated_resume.projects) >= 2
    assert len(pruned_skills) >= 1


def test_per_section_prompt_engine_and_manual_export_flow(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "mistral-nemo:latest"}]})
        if request.url.path == "/api/generate":
            body = json.loads(request.content.decode("utf-8"))
            prompt_blob = body.get("prompt", "")
            if '"section_to_edit": "summary"' in prompt_blob:
                return httpx.Response(
                    200,
                    json={
                        "response": json.dumps(
                            {
                                "summary": "Senior Data & AI Systems Engineer with 5+ years delivering Python, Spark, Kafka, and FastAPI services at Stripe scale."
                            }
                        )
                    },
                )
            if '"section_to_edit": "projects"' in prompt_blob:
                return httpx.Response(
                    200,
                    json={
                        "response": json.dumps(
                            {
                                "projects": [
                                    {
                                        "name": "Real-Time Ledger Streaming Pipeline",
                                        "tech_stack": ["Python", "Spark", "Kafka", "OpenTelemetry"],
                                        "bullets": [
                                            "Built fault-tolerant Spark and Kafka ledger ingestion cutting tail latency from 310ms to 95ms across 12M events/day.",
                                            "Instrumented OpenTelemetry tracing and PostgreSQL partitioning to sustain 99.98% delivery SLA.",
                                        ],
                                    },
                                    {
                                        "name": "Low-Latency RAG Service",
                                        "tech_stack": ["FastAPI", "Python", "Kubernetes"],
                                        "bullets": [
                                            "Deployed FastAPI retrieval gateway on Kubernetes serving 2,500 QPS with sub-120ms p95 latency."
                                        ],
                                    },
                                ]
                            }
                        )
                    },
                )
            if '"section_to_edit": "skills"' in prompt_blob:
                return httpx.Response(
                    200,
                    json={
                        "response": json.dumps(
                            {
                                "skills": [
                                    {"category": "Languages", "items": ["Python", "SQL"]},
                                    {"category": "Data & AI", "items": ["Spark", "Kafka", "FastAPI", "OpenTelemetry", "RAG"]},
                                    {"category": "Cloud & Infra", "items": ["AWS", "Docker", "Kubernetes", "PostgreSQL"]},
                                ]
                            }
                        )
                    },
                )
        return httpx.Response(404)

    client, _ = _build_v3_app(tmp_path, handler=handler)
    with client:
        job_id, resume_id, draft = _seed_job_and_base_resume(client)
        orig_edu = draft["education"]
        orig_companies = [e["company"] for e in draft["experience"]]

        # 1. Summary section prompt via Ollama
        sum_resp = client.post(
            "/api/tailor/section",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "section": "summary",
                "current_resume": draft,
                "prompt": "Emphasize Spark, Kafka, and FastAPI experience cleanly.",
                "engine": "ollama",
            },
        )
        assert sum_resp.status_code == 200
        sum_data = sum_resp.json()
        assert sum_data["engine_used"] == "ollama_llm"
        assert "Spark" in sum_data["updated_resume"]["summary"]
        assert sum_data["updated_resume"]["education"] == orig_edu

        # 2. Projects section prompt via Ollama preserves previous summary edit
        proj_resp = client.post(
            "/api/tailor/section",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "section": "projects",
                "current_resume": sum_data["updated_resume"],
                "prompt": "Showcase Spark, Kafka, and OpenTelemetry.",
                "engine": "ollama",
            },
        )
        assert proj_resp.status_code == 200
        proj_data = proj_resp.json()
        assert proj_data["updated_resume"]["summary"] == sum_data["updated_resume"]["summary"]
        assert len(proj_data["updated_resume"]["projects"]) >= 2
        assert proj_data["updated_resume"]["projects"][0]["name"] == "Real-Time Ledger Streaming Pipeline"

        # 3. Skills section prompt via fallback_script
        sk_resp = client.post(
            "/api/tailor/section",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "section": "skills",
                "current_resume": proj_data["updated_resume"],
                "prompt": "Ensure OpenTelemetry and Spark are added cleanly.",
                "engine": "fallback_script",
            },
        )
        assert sk_resp.status_code == 200
        sk_data = sk_resp.json()
        assert sk_data["engine_used"] == "fallback_script"
        assert [e["company"] for e in sk_data["updated_resume"]["experience"]] == orig_companies
        assert sk_data["updated_resume"]["education"] == orig_edu

        # 4. Manual edit + PDF/DOCX export honors edited summary + page_budget
        manual_draft = sk_data["updated_resume"]
        manual_draft["summary"] = "Custom manually edited summary mentioning Python, Spark, Kafka, FastAPI, and Kubernetes."
        exp_resp = client.post(
            "/api/export",
            json={
                "job_id": job_id,
                "resume_id": resume_id,
                "draft_resume": manual_draft,
                "formats": ["pdf"],
                "page_budget": 1.5,
            },
        )
        assert exp_resp.status_code in (200, 201)
        exp_data = exp_resp.json()
        assert any(f.endswith(".pdf") for f in exp_data["generated_files"])
        assert exp_data["ats_score"] >= 60.0


def test_ollama_benchmark_ranking_and_selection(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "broken:latest"},
                        {"name": "mistral-nemo:latest"},
                        {"name": "partial:latest"},
                    ]
                },
            )
        if request.url.path == "/api/generate":
            body = json.loads(request.content.decode("utf-8"))
            model = body["model"]
            if model == "mistral-nemo:latest":
                return httpx.Response(
                    200,
                    json={
                        "response": json.dumps(
                            {
                                "summary": "Senior backend engineer building distributed Python, Kafka, PostgreSQL, and Kubernetes systems with gRPC and OpenTelemetry.",
                                "project_name": "Stripe Ledger Streaming",
                                "project_bullets": [
                                    "Built Python and Kafka ledger consumer on Kubernetes processing 50k TPS.",
                                    "Instrumented gRPC services with OpenTelemetry and PostgreSQL sharding.",
                                ],
                                "skills": ["Python", "Kafka", "gRPC", "PostgreSQL", "Kubernetes", "OpenTelemetry"],
                            }
                        )
                    },
                )
            if model == "partial:latest":
                return httpx.Response(
                    200,
                    json={
                        "response": json.dumps(
                            {
                                "summary": "Engineer building Python services.",
                                "project_name": "API App",
                                "project_bullets": ["Slashed latency by using Python."],
                                "skills": ["Python", "SQL"],
                            }
                        )
                    },
                )
            return httpx.Response(200, json={"response": "not-valid-json{[["})
        return httpx.Response(404)

    client, _ = _build_v3_app(tmp_path, handler=handler)
    with client:
        resp = client.post("/api/config/llm/benchmark", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["reachable"] is True
        assert data["recommended_model"] == "mistral-nemo:latest"
        assert len(data["items"]) == 3
        top = data["items"][0]
        assert top["rank"] == 1
        assert top["model"] == "mistral-nemo:latest"
        assert top["json_valid"] is True
        assert top["schema_complete"] is True
        broken = next(i for i in data["items"] if i["model"] == "broken:latest")
        assert broken["ok"] is False
        assert broken["json_valid"] is False


def test_standing_statuses_reports_excel_and_skills_graph(tmp_path: Path) -> None:
    client, _ = _build_v3_app(tmp_path)
    with client:
        job_id, _, _ = _seed_job_and_base_resume(client)

        patch_resp = client.patch(
            f"/api/jobs/{job_id}",
            json={
                "application_status": "interviewing",
                "application_notes": "Completed recruiter screen; technical loop Friday.",
            },
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["application_status"] == "interviewing"
        assert patched["applied_at"] is not None
        assert "technical loop Friday" in (patched["application_notes"] or "")

        rep_resp = client.get("/api/reports")
        assert rep_resp.status_code == 200
        rep = rep_resp.json()
        assert any(b["label"] == "Stripe" for b in rep["by_company"])
        assert len(rep["by_domain"]) >= 1
        assert len(rep["by_posted_freshness"]) >= 1
        assert len(rep["funnel_stages"]) >= 1
        assert len(rep["applied_jobs"]) == 1
        assert rep["applied_jobs"][0]["application_status"] == "interviewing"
        assert "technical loop Friday" in (rep["applied_jobs"][0]["application_notes"] or "")

        excel_resp = client.get("/api/reports/excel")
        assert excel_resp.status_code == 200
        assert "spreadsheetml.sheet" in excel_resp.headers["content-type"]
        wb = openpyxl.load_workbook(io.BytesIO(excel_resp.content))
        assert wb.sheetnames == [
            "Jobs & Apply Links",
            "Overview & Analytics",
            "Applied Standing",
            "Filtered & Seen Log",
            "Skills Demand",
        ]
        applied_rows = list(wb["Applied Standing"].iter_rows(values_only=True))
        assert any("Stripe" in str(cell) for row in applied_rows for cell in row if cell)

        sg_resp = client.get("/api/reports/skills-graph")
        assert sg_resp.status_code == 200
        sg = sg_resp.json()
        assert sg["total_jobs"] >= 1
        assert len(sg["jobs"]) >= 1
        assert len(sg["domains"]) >= 1
        assert len(sg["skills"]) >= 3
        assert any(e["kind"] == "job_domain" for e in sg["edges"])
        assert any(e["kind"] == "domain_skill" for e in sg["edges"])


def test_carry_forward_applied_jobs_across_sessions(tmp_path: Path):
    """Verify that jobs with active progress (e.g. applied, interviewing) carry forward into new sessions."""
    client, _ = _build_v3_app(tmp_path)
    with client:
        # 1. Create Session 1 and ingest a job
        s1_resp = client.post("/api/sessions", json={"name": "Session 1 (Feb 12)", "freshness": "24h"})
        assert s1_resp.status_code == 201
        s1_id = s1_resp.json()["id"]

        j1_resp = client.post(
            "/api/jobs/ingest",
            json={
                "session_id": s1_id,
                "url": "https://boards.greenhouse.io/datadog/jobs/990011",
                "raw_text": "Datadog is hiring a Senior Software Engineer in New York, NY. Requirements: Python, Distributed Systems, Go, Kafka, AWS, Kubernetes.",
            },
        )
        assert j1_resp.status_code == 201
        job1 = j1_resp.json()
        job1_id = job1["id"]

        # 2. Mark this job as applied with notes
        patch_resp = client.patch(
            f"/api/jobs/{job1_id}",
            json={
                "application_status": "applied",
                "application_notes": "Submitted application via Datadog referral link.",
            },
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["application_status"] == "applied"

        # 3. Create Session 2 (representing a subsequent scrape)
        s2_resp = client.post("/api/sessions", json={"name": "Session 2 (Feb 13)", "freshness": "24h"})
        assert s2_resp.status_code == 201
        s2_id = s2_resp.json()["id"]

        # 4. Trigger scrape in Session 2 that discovers the same posting
        gh_data = {
            "jobs": [
                {
                    "id": 990011,
                    "title": "Senior Software Engineer",
                    "location": {"name": "New York, NY"},
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "absolute_url": "https://boards.greenhouse.io/datadog/jobs/990011",
                    "content": "Datadog is hiring a Senior Software Engineer in New York, NY. Requirements: Python, Distributed Systems, Go, Kafka, AWS, Kubernetes.",
                }
            ]
        }

        def _handler(req: httpx.Request) -> httpx.Response:
            if "datadog" in str(req.url):
                return httpx.Response(200, json=gh_data)
            return httpx.Response(404, json={})

        client.app.state.scrape_http_client = httpx.Client(transport=httpx.MockTransport(_handler))

        scrape_resp = client.post(
            f"/api/sessions/{s2_id}/scrape",
            json={
                "posted_within": "24h",
                "role_tracks": ["senior_swe"],
                "sources": ["greenhouse"],
                "company_boards": ["greenhouse:datadog"],
                "locations": ["ALL_US"],
            },
        )
        assert scrape_resp.status_code == 200
        sc_res = scrape_resp.json()
        assert sc_res["saved_count"] == 1

        # 5. Verify Session 2 now has this carried-forward job with 'applied' status
        s2_jobs_resp = client.get(f"/api/jobs?session_id={s2_id}")
        assert s2_jobs_resp.status_code == 200
        s2_jobs = s2_jobs_resp.json()
        assert len(s2_jobs) == 1
        carried = s2_jobs[0]
        assert carried["analysis"]["company"] == "Datadog"
        assert carried["application_status"] == "applied"
        assert "Carried from Session 1" in (carried["application_notes"] or "")
        assert "Submitted application via Datadog referral link" in (carried["application_notes"] or "")

