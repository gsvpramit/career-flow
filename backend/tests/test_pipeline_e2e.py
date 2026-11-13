"""End-to-end pytest coverage for scraping, JD analysis, resume upload, ATS scoring, and PDF/DOCX export."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import httpx
import pytest
import yaml
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.app.config import ROLE_TRACKS_DIR, RULES_PATH
from backend.app.main import create_app
from backend.app.services.config_manager import ConfigManager
from backend.app.services.scraper import ScrapeError, fetch_job_posting, parse_job_html

SAMPLE_AI_JD = """
Senior AI Engineer
Company: Acme Cloud AI
Location: Seattle, WA (Hybrid)
Compensation: $185,000 - $245,000 base salary + equity

What You'll Do:
- Architect and deploy production RAG and AI agents serving 2M+ daily queries at <150ms P99 latency.
- Build automated evaluation (evals) and guardrail pipelines for structured output reliability.
- Mentor engineers across cross-functional product teams and own system design trade-offs.

Required Qualifications:
- 5+ years of experience building scalable Python and FastAPI backend services.
- Deep experience with LLM orchestration, embeddings, vector database tuning, and Kubernetes.
- Track record improving inference throughput and cost optimization on GPUs.

Preferred Qualifications:
- Experience with TensorRT, Triton, or Ray.
"""


def _build_client(tmp_path: Path) -> tuple[TestClient, Path]:
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
                "target_role_tracks": ["senior_swe", "ai_engineer"],
                "llm_mode": "off",
                "llm_model": "qwen3:14b",
                "export_formats": ["pdf", "docx"],
                "page_budget": 1,
                "target_yoe_min": 4,
                "target_yoe_max": 8,
                "target_salary_min": 175000,
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
        db_path=tmp_path / "test.db",
        output_dir_override=output_dir,
    )
    return TestClient(app), output_dir


def _sample_resume_payload(
    name: str = "Senior AI Base Resume",
    role_track: str = "ai_engineer",
) -> dict[str, object]:
    return {
        "name": name,
        "role_track": role_track,
        "is_base": True,
        "content": {
            "contact": {
                "full_name": "Alex Rivera",
                "email": "alex.rivera@example.com",
                "phone": "(555) 234-5678",
                "location": "Seattle, WA",
                "linkedin": "linkedin.com/in/alexrivera",
                "github": "github.com/alexrivera",
            },
            "education": [
                {
                    "institution": "University of Washington",
                    "degree": "M.S. in Computer Science",
                    "location": "Seattle, WA",
                    "graduation_date": "2020",
                },
                {
                    "institution": "State University",
                    "degree": "B.S. in Computer Engineering",
                    "location": "Austin, TX",
                    "graduation_date": "2018",
                },
            ],
            "experience": [
                {
                    "id": "exp_1",
                    "company": "Northstar Systems",
                    "title": "Senior Software Engineer",
                    "location": "Seattle, WA",
                    "start_date": "2022",
                    "end_date": "Present",
                    "bullets": [
                        {
                            "id": "b1",
                            "text": "Architected a production RAG and FastAPI inference service in Python handling 1.8M daily requests, cutting P99 latency by 42%.",
                            "provenance": "VERIFIED_BASE",
                            "approved": True,
                        },
                        {
                            "id": "b2",
                            "text": "Spearheaded cross-functional migration to Docker and Kubernetes, reducing cloud spend by $120K/year.",
                            "provenance": "VERIFIED_BASE",
                            "approved": True,
                        },
                    ],
                },
                {
                    "id": "exp_2",
                    "company": "Beacon Cloud",
                    "title": "Software Engineer",
                    "location": "Austin, TX",
                    "start_date": "2020",
                    "end_date": "2022",
                    "bullets": [
                        {
                            "id": "b3",
                            "text": "Built distributed telemetry APIs in Python and PostgreSQL handling 10M daily events.",
                            "provenance": "VERIFIED_BASE",
                            "approved": True,
                        }
                    ],
                },
            ],
            "projects": [
                {
                    "id": "proj_1",
                    "name": "EvalBench",
                    "tech_stack": ["Python", "PyTorch", "LLM"],
                    "link": "github.com/alexrivera/evalbench",
                    "bullets": [
                        {
                            "id": "p1",
                            "text": "Built automated structured output evals suite benchmarking 12 quantized LLM endpoints across 4K prompts.",
                            "provenance": "VERIFIED_BASE",
                            "approved": True,
                        }
                    ],
                }
            ],
            "certifications": [
                {
                    "name": "AWS Certified Solutions Architect - Associate",
                    "issuer": "Amazon Web Services",
                    "date": "2024",
                }
            ],
            "skills": [
                {"category": "Languages & Frameworks", "items": ["Python", "FastAPI", "PyTorch"]},
                {"category": "AI & Infra", "items": ["LLM", "RAG", "Docker", "Kubernetes"]},
            ],
        },
    }


def test_html_json_ld_scraping_and_bot_block_fallback() -> None:
    html = """
    <html>
      <head>
        <title>Ignored Page Title</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "JobPosting",
          "title": "Senior Software Engineer",
          "hiringOrganization": {"@type": "Organization", "name": "ExampleTech"},
          "jobLocation": {"@type": "Place", "address": {"addressLocality": "San Francisco", "addressRegion": "CA"}},
          "description": "<p>Build distributed Python and Kubernetes systems. 5+ years of experience. $180,000 - $230,000.</p>"
        }
        </script>
      </head>
      <body><main><p>Build distributed Python and Kubernetes systems.</p></main></body>
    </html>
    """
    parsed = parse_job_html(html, "https://boards.greenhouse.io/exampletech/jobs/123")
    assert parsed.title == "Senior Software Engineer"
    assert parsed.company == "ExampleTech"
    assert parsed.location == "San Francisco, CA"
    assert "Kubernetes" in parsed.raw_text

    def blocked_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    mock_client = httpx.Client(transport=httpx.MockTransport(blocked_handler))
    with pytest.raises(ScrapeError, match="paste the job description"):
        fetch_job_posting(url="https://example.com/blocked", client=mock_client)


def test_full_pipeline_ingest_score_and_export_pdf_docx(tmp_path: Path) -> None:
    client, output_dir = _build_client(tmp_path)
    with client:
        # 1. Ingest JD
        job_resp = client.post(
            "/api/jobs/ingest",
            json={"raw_text": SAMPLE_AI_JD, "role_track": "ai_engineer"},
        )
        assert job_resp.status_code == 201
        job = job_resp.json()
        job_id = job["id"]
        analysis = job["analysis"]
        assert analysis["company"] == "Acme Cloud AI"
        assert analysis["title"] == "Senior AI Engineer"
        assert analysis["salary"]["min_amount"] == 185000
        assert analysis["salary"]["max_amount"] == 245000
        assert analysis["salary"]["meets_target"] is True
        assert analysis["yoe"]["min_years"] == 5
        assert analysis["yoe"]["fits_target_range"] is True
        assert any(s["keyword"].lower() == "rag" and s["in_required_section"] is False for s in analysis["weighted_skills"])
        assert any(s["keyword"].lower() == "vector database" and s["in_required_section"] is True for s in analysis["weighted_skills"])

        # 2. Scoring without base resume triggers NO_BASE_RESUME 409 prompt
        no_resume_score = client.post("/api/jobs/score", json={"job_id": job_id})
        assert no_resume_score.status_code == 409
        assert "NO_BASE_RESUME" in no_resume_score.json()["detail"]

        # 3. Create base resume via Web Form payload
        resume_resp = client.post("/api/resumes", json=_sample_resume_payload())
        assert resume_resp.status_code == 201
        resume_id = resume_resp.json()["id"]

        # 4. Score resume against JD
        score_resp = client.post("/api/jobs/score", json={"job_id": job_id, "resume_id": resume_id})
        assert score_resp.status_code == 200
        report = score_resp.json()
        assert 0 < report["overall_score"] <= 100
        missing_kw = {item["keyword"].lower() for item in report["missing_skills"]}
        assert "vector database" in missing_kw
        assert "embeddings" in missing_kw
        # Verify humanizer caught "Spearheaded" AI cliche in b2
        assert any("spearheaded" in d["ai_slop_found"] for d in report["bullet_diagnostics"])

        # 5. Export PDF + DOCX into output/ folder
        export_resp = client.post("/api/export", json={"job_id": job_id, "resume_id": resume_id})
        assert export_resp.status_code == 201
        export_data = export_resp.json()
        assert export_data["pdf_text_verified"] is True
        expected_stem = "Alex_Rivera_Acme_Cloud_AI_Senior_AI_Engineer_J1_R1"
        assert set(export_data["generated_files"]) >= {
            f"{expected_stem}.pdf",
            f"{expected_stem}.docx",
            "job_posting.json",
            "ats_report.json",
            "resume_snapshot.json",
        }

        run_dir = Path(export_data["output_folder"])
        assert run_dir.exists()
        assert run_dir.parent == output_dir

        # Verify PDF selectable text order via pypdf
        pdf_reader = PdfReader(str(run_dir / f"{expected_stem}.pdf"))
        pdf_text = "\n".join((p.extract_text() or "") for p in pdf_reader.pages)
        assert "Alex Rivera" in pdf_text
        assert "Northstar Systems" in pdf_text
        assert "1.8M daily requests" in pdf_text
        assert "AWS Certified Solutions Architect" in pdf_text

        # Verify DOCX readability via python-docx
        docx_doc = Document(str(run_dir / f"{expected_stem}.docx"))
        docx_text = "\n".join(p.text for p in docx_doc.paragraphs)
        assert "Alex Rivera" in docx_text
        assert "Northstar Systems" in docx_text
        assert "AWS Certified Solutions Architect" in docx_text

        # Verify JSON audit files
        saved_report = json.loads((run_dir / "ats_report.json").read_text(encoding="utf-8"))
        assert saved_report["overall_score"] == report["overall_score"]

        # Verify download endpoint
        dl_pdf = client.get(f"/api/export/runs/{export_data['run_id']}/download/{expected_stem}.pdf")
        assert dl_pdf.status_code == 200
        assert dl_pdf.content.startswith(b"%PDF")


def test_docx_and_tex_upload_parsing(tmp_path: Path) -> None:
    client, _ = _build_client(tmp_path)
    with client:
        # Create an in-memory .docx resume
        doc = Document()
        doc.add_paragraph("Jordan Lee")
        doc.add_paragraph("jordan.lee@example.com | (555) 999-1111 | github.com/jordanlee")
        doc.add_paragraph("Experience")
        doc.add_paragraph("Staff Backend Engineer | ScaleCorp | 2021 - Present")
        doc.add_paragraph("- Engineered Go and Kafka ingestion pipeline processing 40M events/day.")
        doc.add_paragraph("Education")
        doc.add_paragraph("Stanford University | M.S. Computer Science | 2020")
        doc.add_paragraph("UC Berkeley | B.S. EECS | 2018")
        doc.add_paragraph("Certifications")
        doc.add_paragraph("CKA (Certified Kubernetes Administrator) | CNCF | 2024")
        doc.add_paragraph("Technical Skills")
        doc.add_paragraph("Languages: Go, Python, SQL")
        buf = io.BytesIO()
        doc.save(buf)

        upload_resp = client.post(
            "/api/resumes/upload",
            files={"file": ("jordan_resume.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"name": "Jordan Uploaded", "is_base": "true"},
        )
        assert upload_resp.status_code == 201
        parsed = upload_resp.json()["content"]
        assert parsed["contact"]["full_name"] == "Jordan Lee"
        assert parsed["contact"]["email"] == "jordan.lee@example.com"
        assert parsed["experience"][0]["company"] == "ScaleCorp"
        assert len(parsed["education"]) == 2
        assert parsed["certifications"][0]["name"] == "CKA (Certified Kubernetes Administrator)"
        assert "40M events/day" in parsed["experience"][0]["bullets"][0]["text"]
        assert "Go" in parsed["skills"][0]["items"]

        # Upload a minimal .tex resume as supplementary context
        tex_bytes = (
            b"\\textbf{Jordan Lee}\n"
            b"\\section{Experience}\n"
            b"\\textbf{Senior Engineer | CloudBase | 2019 - 2021}\n"
            b"- Scaled Redis caching layer reducing P99 latency by 55\\%.\n"
        )
        tex_resp = client.post(
            "/api/resumes/upload",
            files={"file": ("jordan_extra.tex", tex_bytes, "text/plain")},
            data={"name": "Jordan TeX Context", "is_base": "false"},
        )
        assert tex_resp.status_code == 201
        assert tex_resp.json()["source_type"] == "tex"
        assert tex_resp.json()["is_base"] is False
        assert "Redis" in tex_resp.json()["raw_text"]


def test_sessions_role_inference_tailor_preview_and_location_modifier(tmp_path: Path) -> None:
    client, output_dir = _build_client(tmp_path)
    with client:
        # Create one active base resume for AI Engineer and another for Senior SWE
        ai_res = client.post("/api/resumes", json=_sample_resume_payload("AI Profile", "ai_engineer"))
        assert ai_res.status_code == 201

        swe_payload = _sample_resume_payload("SWE Profile", "senior_swe")
        swe_payload["content"]["experience"][0]["title"] = "SDE 2"  # type: ignore[index]
        swe_res = client.post("/api/resumes", json=swe_payload)
        assert swe_res.status_code == 201
        swe_res_id = swe_res.json()["id"]

        resumes_state = client.get("/api/resumes").json()
        assert resumes_state["base_by_role"]["ai_engineer"] == ai_res.json()["id"]
        assert resumes_state["base_by_role"]["senior_swe"] == swe_res_id

        # Create a named scrape session
        sess_resp = client.post("/api/sessions", json={"name": "Session 1 - West Coast"})
        assert sess_resp.status_code == 201
        session_id = sess_resp.json()["id"]

        # Job 1: Seattle SDE 2 -> inferred as senior_swe via alias
        j1 = client.post(
            "/api/jobs/ingest",
            json={
                "session_id": session_id,
                "raw_text": (
                    "SDE 2 (Backend Distributed Systems)\n"
                    "Company: Nimbus Cloud\n"
                    "Location: Seattle, WA\n"
                    "Salary: $180,000 - $215,000\n"
                    "5+ years of experience with Python, distributed systems, microservices, PostgreSQL, Kubernetes."
                ),
            },
        )
        assert j1.status_code == 201
        assert j1.json()["analysis"]["role_track"] == "senior_swe"

        # Job 2: San Diego Senior SWE
        j2 = client.post(
            "/api/jobs/ingest",
            json={
                "session_id": session_id,
                "raw_text": (
                    "Senior Software Engineer\n"
                    "Company: Harbor Tech\n"
                    "Location: San Diego, CA\n"
                    "Compensation: $190,000 - $230,000\n"
                    "Required: Python, FastAPI, Kubernetes, distributed systems, latency optimization."
                ),
            },
        )
        assert j2.status_code == 201
        j2_id = j2.json()["id"]
        assert j2.json()["analysis"]["role_track"] == "senior_swe"
        assert j2.json()["analysis"]["location"] == "San Diego, CA"

        # Job 3: European AI role in EUR
        j3 = client.post(
            "/api/jobs/ingest",
            json={
                "session_id": session_id,
                "raw_text": (
                    "Senior AI Engineer\n"
                    "Company: EuroAI Labs\n"
                    "Location: Berlin, Germany\n"
                    "Compensation: EUR 140,000 - EUR 170,000\n"
                    "Required: LLM, RAG, vector database, Python, Kubernetes."
                ),
            },
        )
        assert j3.status_code == 201
        assert j3.json()["analysis"]["salary"]["currency"] == "EUR"
        assert j3.json()["analysis"]["salary"]["meets_target"] is None

        # Verify session summary groups locations, roles, and currencies
        sessions = client.get("/api/sessions").json()
        target_sess = next(s for s in sessions if s["id"] == session_id)
        assert target_sess["total_jobs"] == 3
        loc_map = {item["location"]: item["count"] for item in target_sess["locations"]}
        assert loc_map["Seattle, WA"] == 1
        assert loc_map["San Diego, CA"] == 1
        assert loc_map["Berlin, Germany"] == 1
        assert set(target_sess["currencies"]) == {"USD", "EUR"}

        # Verify pre-export tailor preview auto-selects senior_swe profile, adapts location, and strips AI slop
        preview_resp = client.post(
            "/api/tailor/preview",
            json={"job_id": j2_id, "adapt_location": True},
        )
        assert preview_resp.status_code == 200
        preview = preview_resp.json()
        assert preview["resume_id"] == swe_res_id
        assert preview["tailored_resume"]["contact"]["location"] == "San Diego, CA"
        assert any(fc["field_name"] == "Header Location" for fc in preview["field_changes"])
        assert len(preview["experience_comparisons"]) == 2
        all_bullets = [
            b
            for exp in preview["experience_comparisons"]
            for b in exp["bullets"]
        ]
        assert any("Led " in b["tailored_text"] and b["status"] in ("polished", "edited") for b in all_bullets)

        # Export the tailored & fact-checked resume
        export_resp = client.post(
            "/api/export",
            json={
                "job_id": j2_id,
                "resume_id": preview["resume_id"],
                "formats": ["pdf"],
                "tailored_resume": preview["tailored_resume"],
            },
        )
        assert export_resp.status_code == 201
        exp_body = export_resp.json()
        assert exp_body["generated_files"] == [
            "Alex_Rivera_Harbor_Tech_Senior_Software_Engineer_J2_R1.pdf",
            "job_posting.json",
            "ats_report.json",
            "resume_snapshot.json",
        ]
        pdf_reader = PdfReader(
            str(Path(exp_body["output_folder"]) / "Alex_Rivera_Harbor_Tech_Senior_Software_Engineer_J2_R1.pdf")
        )
        pdf_text = "\n".join((p.extract_text() or "") for p in pdf_reader.pages)
        assert "San Diego, CA" in pdf_text
        assert output_dir in Path(exp_body["output_folder"]).parents


def test_batch_scrape_simultaneous_filters_and_permanent_discard(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone
    import httpx

    client, output_dir = _build_client(tmp_path)
    now = datetime.now(timezone.utc)
    fresh_iso = (now - timedelta(minutes=20)).isoformat()
    stale_iso = (now - timedelta(hours=3)).isoformat()

    gh_jobs = {
        "jobs": [
            {
                "id": 101,
                "title": "Senior Software Engineer",
                "location": {"name": "Seattle, WA"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/101?utm_source=linkedin",
                "updated_at": fresh_iso,
                "content": (
                    "<p>Build distributed systems in Python, FastAPI, Kubernetes, PostgreSQL. "
                    "We sponsor H-1B visas. Full-time salaried role. 5+ years experience.</p>"
                ),
            },
            {
                "id": 102,
                "title": "Senior AI Engineer",
                "location": {"name": "San Diego, CA"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/102",
                "updated_at": fresh_iso,
                "content": (
                    "<p>Design production LLM and RAG pipelines with embeddings and vector database. "
                    "Full-time role requiring 4-7 years experience. Compensation is confidential.</p>"
                ),
            },
            {
                "id": 103,
                "title": "Senior Software Engineer",
                "location": {"name": "Seattle, WA"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/103",
                "updated_at": fresh_iso,
                "content": (
                    "<p>Full-time Python engineer. Unfortunately we cannot sponsor visas and "
                    "require US citizens only. Salary $190,000 - $220,000.</p>"
                ),
            },
            {
                "id": 104,
                "title": "Senior Software Engineer",
                "location": {"name": "San Francisco, CA"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/104",
                "updated_at": stale_iso,
                "content": "<p>Great role with Python and Go. $200,000 - $240,000.</p>",
            },
            {
                "id": 105,
                "title": "Junior Software Engineer",
                "location": {"name": "Seattle, WA"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/105",
                "updated_at": fresh_iso,
                "content": "<p>Entry level role.</p>",
            },
            {
                "id": 106,
                "title": "Senior Software Engineer (C2C)",
                "location": {"name": "Seattle, WA"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/106",
                "updated_at": fresh_iso,
                "content": "<p>6 month C2C contract position, 1099 independent contractor only.</p>",
            },
            {
                "id": 107,
                "title": "Senior Software Engineer",
                "location": {"name": "Seattle, WA"},
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/107",
                "updated_at": fresh_iso,
                "content": "<p>Full-time Python role. Base salary $110,000 - $130,000.</p>",
            },
        ]
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        if "boards-api.greenhouse.io/v1/boards/acme/jobs" in str(request.url):
            return httpx.Response(200, json=gh_jobs)
        return httpx.Response(404, json={})

    mock_http = httpx.Client(transport=httpx.MockTransport(_handler))
    client.app.state.scrape_http_client = mock_http

    try:
        with client:
            # Configure strict H1B + Full-time + target salary floor $175k + target locations
            cfg = client.put(
                "/api/config",
                json={
                    "updates": {
                        "target_role_tracks": ["senior_swe", "ai_engineer"],
                        "target_locations": ["Seattle, WA", "San Diego, CA", "San Francisco, CA"],
                        "work_authorization": "h1b",
                        "job_types": ["full-time"],
                        "target_salary_min": 175000,
                        "scraper_sources": ["greenhouse"],
                        "company_boards": ["greenhouse:acme"],
                        "title_blocklist": ["junior", "intern"],
                    }
                },
            )
            assert cfg.status_code == 200

            res_resp = client.post("/api/resumes", json=_sample_resume_payload("Main SWE", "senior_swe"))
            assert res_resp.status_code == 201

            # Session 1 with 1h freshness
            s1 = client.post("/api/sessions", json={"name": "Morning 1h", "posted_within": "1h"}).json()["id"]
            b1 = client.post(
                f"/api/sessions/{s1}/scrape",
                json={"posted_within": "1h"},
            )
            assert b1.status_code == 200
            r1 = b1.json()
            assert r1["scanned_count"] == 7
            # Only jobs 101 (no salary + H1B ok) and 102 (no salary, AI engineer) pass inline!
            assert r1["saved_count"] == 2
            saved_titles = {j["analysis"]["title"] for j in r1["saved_jobs"]}
            assert saved_titles == {"Senior Software Engineer", "Senior AI Engineer"}
            assert r1["filter_breakdown"]["stale_outside_window"] == 1
            assert r1["filter_breakdown"]["blocked_title"] == 1
            assert r1["filter_breakdown"]["no_h1b_sponsorship"] == 1
            assert r1["filter_breakdown"]["job_type:contract"] == 1
            assert r1["filter_breakdown"]["below_min_salary"] == 1

            # Discard job 101 -> vanishes from active list AND permanently remembered
            job_101_id = next(
                j["id"] for j in r1["saved_jobs"] if j["analysis"]["title"] == "Senior Software Engineer"
            )
            patch_resp = client.patch(
                f"/api/jobs/{job_101_id}",
                json={"disposition": "discarded"},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["disposition"] == "discarded"

            active_s1 = client.get(f"/api/jobs?session_id={s1}").json()
            assert len(active_s1) == 1
            assert active_s1[0]["analysis"]["title"] == "Senior AI Engineer"

            # Session 2 widens to 24h: previously saved/discarded/auto-filtered stay skipped,
            # while 3h-old SF job 104 becomes eligible because stale drops didn't poison wider windows!
            gh_jobs["jobs"][0]["absolute_url"] = "https://boards.greenhouse.io/acme/jobs/101?utm_medium=email"
            s2 = client.post("/api/sessions", json={"name": "Afternoon Re-run", "posted_within": "24h"}).json()["id"]
            b2 = client.post(f"/api/sessions/{s2}/scrape", json={"posted_within": "24h"})
            assert b2.status_code == 200
            r2 = b2.json()
            assert r2["saved_count"] == 1
            assert r2["saved_jobs"][0]["analysis"]["location"] == "San Francisco, CA"
            assert r2["duplicate_skipped_count"] == 6

            # Session 3 re-runs 24h: now 0 jobs are pulled at all!
            s3 = client.post("/api/sessions", json={"name": "Third Check", "posted_within": "24h"}).json()["id"]
            b3 = client.post(f"/api/sessions/{s3}/scrape", json={"posted_within": "24h"})
            assert b3.status_code == 200
            assert b3.json()["saved_count"] == 0
            assert b3.json()["duplicate_skipped_count"] == 7

            # Skills Gap aggregation & Analytics HTML Report scoped cleanly to Session 1
            gap = client.get(f"/api/skills-gap?session_id={s1}")
            assert gap.status_code == 200
            gap_data = gap.json()
            assert gap_data["total_active_jobs"] == 1
            missing_kws = {item["keyword"].lower() for item in gap_data["overall_missing"]}
            assert "vector database" in missing_kws

            rep = client.get(f"/api/reports?session_id={s1}")
            assert rep.status_code == 200
            rep_data = rep.json()
            assert rep_data["total_saved"] == 1
            assert rep_data["total_discarded"] == 1
            assert rep_data["omitted_salary_count"] == 1
            assert (output_dir / "dashboard.html").is_file()

            html_rep = client.get(f"/api/reports/html?session_id={s1}")
            assert html_rep.status_code == 200
            assert "CareerFlow" in html_rep.text
    finally:
        mock_http.close()


def test_linkedin_relative_time_and_description_markup_extraction() -> None:
    import httpx
    from backend.app.services.batch_scraper import fetch_linkedin_candidates, is_within_freshness
    from backend.app.services.scraper import fetch_job_posting

    search_html = """
    <ul>
      <li>
        <div class="base-card" data-entity-urn="urn:li:jobPosting:4471980185">
          <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/4471980185?trk=public_jobs">Senior Software Engineer</a>
          <h3 class="base-search-card__title">Senior Software Engineer</h3>
          <h4 class="base-search-card__subtitle">NVIDIA</h4>
          <span class="job-search-card__location">Seattle, WA</span>
          <time datetime="2026-11-11">44 minutes ago</time>
        </div>
      </li>
    </ul>
    """
    detail_html = """
    <html><body>
      <div class="join-to-apply__content">Join or sign in to find your next job</div>
      <div class="show-more-less-html__markup">
        We are building distributed GPU inference and Python/C++ microservices at scale.
        Required: 5+ years of production backend experience with Kubernetes, distributed systems, and telemetry.
        Full-time role with visa sponsorship available.
      </div>
    </body></html>
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        if "seeMoreJobPostings" in str(request.url):
            return httpx.Response(200, text=search_html)
        if "jobPosting/4471980185" in str(request.url):
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
        cards = fetch_linkedin_candidates(
            role_query="Senior Software Engineer",
            location_query="Seattle, WA",
            posted_within="1h",
            work_types=["remote", "hybrid", "onsite"],
            job_types=["full-time"],
            client=client,
        )
        assert len(cards) == 1
        assert cards[0].posted_at is not None
        assert is_within_freshness(cards[0].posted_at, "1h") is True
        detail = fetch_job_posting(url=cards[0].detail_url, client=client)
        assert "distributed GPU inference" in detail.raw_text
        assert "Join or sign in" not in detail.raw_text


def test_ashby_scraping_us_locations_async_progress_and_flush(tmp_path: Path) -> None:
    import time
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    client, output_dir = _build_client(tmp_path)

    def _mock_handler(request: httpx.Request) -> httpx.Response:
        if "api.ashbyhq.com/posting-api/job-board/openai" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "title": "Senior AI Engineer",
                            "location": "San Francisco, CA",
                            "secondaryLocations": [{"location": "Seattle, WA"}],
                            "publishedAt": now_iso,
                            "isListed": True,
                            "workplaceType": "Hybrid",
                            "jobUrl": "https://jobs.ashbyhq.com/openai/1",
                            "descriptionPlain": (
                                "Build Python LLM agents, RAG evaluation, Kubernetes microservices. "
                                "5+ years experience. Compensation $210,000 - $280,000."
                            ),
                        },
                        {
                            "title": "Senior AI Engineer",
                            "location": "London, UK",
                            "secondaryLocations": [],
                            "publishedAt": now_iso,
                            "isListed": True,
                            "workplaceType": "Onsite",
                            "jobUrl": "https://jobs.ashbyhq.com/openai/2",
                            "descriptionPlain": "London AI infrastructure role.",
                        },
                        {
                            "title": "Hidden AI Engineer",
                            "location": "Seattle, WA",
                            "publishedAt": now_iso,
                            "isListed": False,
                            "jobUrl": "https://jobs.ashbyhq.com/openai/3",
                            "descriptionPlain": "Unlisted posting.",
                        },
                    ]
                },
            )
        return httpx.Response(404)

    mock_http = httpx.Client(transport=httpx.MockTransport(_mock_handler))
    try:
        with client:
            client.app.state.scrape_http_client = mock_http

            locs = client.get("/api/config/locations")
            assert locs.status_code == 200
            loc_data = locs.json()
            assert len(loc_data["top_20"]) == 20
            assert "Seattle, WA" in loc_data["top_20"]
            assert len(loc_data["all_us"]) > 50

            resume_resp = client.post("/api/resumes", json=_sample_resume_payload())
            assert resume_resp.status_code == 201
            resume_id = resume_resp.json()["id"]

            sess_resp = client.post("/api/sessions", json={"name": "Async Ashby Run"})
            assert sess_resp.status_code == 201
            sess_id = sess_resp.json()["id"]

            start_resp = client.post(
                f"/api/sessions/{sess_id}/scrape/start",
                json={
                    "posted_within": "24h",
                    "sources": ["ashby"],
                    "company_boards": ["ashby:openai"],
                    "locations": ["ALL_US"],
                    "role_tracks": ["ai_engineer"],
                },
            )
            assert start_resp.status_code == 200
            assert start_resp.json()["status"] in ("running", "completed")

            prog = start_resp.json()
            for _ in range(40):
                if prog["status"] in ("completed", "failed"):
                    break
                time.sleep(0.05)
                prog = client.get(f"/api/sessions/{sess_id}/scrape/progress").json()

            assert prog["status"] == "completed", prog.get("error")
            assert prog["result"]["saved_count"] == 1
            assert prog["result"]["filter_breakdown"]["location_mismatch"] == 1
            job_id = prog["result"]["saved_jobs"][0]["id"]

            sessions = client.get("/api/sessions").json()
            sess_sum = next(s for s in sessions if s["id"] == sess_id)
            assert sess_sum["sources_used"] == ["ashby"]
            assert sess_sum["status_counts"].get("ready") == 1
            assert sess_sum["discarded_count"] == 0

            export_resp = client.post(
                "/api/export",
                json={"job_id": job_id, "resume_id": resume_id, "formats": ["pdf"]},
            )
            assert export_resp.status_code == 201
            assert len(list(output_dir.iterdir())) >= 1

            # Partial flush: clear only tailoring runs & exports while keeping jobs + resumes
            partial = client.post(
                "/api/data/flush",
                json={"flush_tailoring_runs": True, "flush_output_files": True},
            )
            assert partial.status_code == 200
            assert partial.json()["tailoring_runs_deleted"] == 1
            assert partial.json()["sessions_deleted"] == 0
            assert partial.json()["resumes_deleted"] == 0
            jobs_after_partial = client.get(f"/api/jobs?session_id={sess_id}").json()
            assert jobs_after_partial[0]["application_status"] == "ready"
            assert list(output_dir.iterdir()) == []

            # Master flush: wipes sessions, jobs, seen ledger, outputs, and preserves resumes
            master = client.post("/api/data/flush", json={"master_flush": True})
            assert master.status_code == 200
            m_data = master.json()
            assert m_data["sessions_deleted"] == 1
            assert master.json()["jobs_deleted"] == 1
            assert master.json()["seen_deleted"] >= 1
            assert master.json()["resumes_deleted"] == 0
            assert client.get("/api/sessions").json() == []
            assert client.get("/api/resumes").json()["has_base_resume"] is True
    finally:
        mock_http.close()


def test_filtered_seen_audit_promote_restore_and_stop_scrape(tmp_path) -> None:
    """Verify filtered/seen differentiation, multi-select restore to saved list, and mid-run stop."""
    import threading
    import time
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    ts_recent = (now - timedelta(minutes=8)).isoformat()
    li_entered = threading.Event()
    allow_li_finish = threading.Event()

    gh_jobs = {
        "jobs": [
            {
                "id": 301,
                "title": "Senior Software Engineer",
                "location": {"name": "Seattle, WA"},
                "updated_at": ts_recent,
                "absolute_url": "https://boards.greenhouse.io/gamma/jobs/301",
                "content": (
                    "<p>We build distributed Python and FastAPI backend services in Seattle, WA.</p>"
                    "<p>We sponsor H-1B visas. $195,000 - $220,000 per year.</p>"
                ),
            },
            {
                "id": 302,
                "title": "Senior Software Engineer",
                "location": {"name": "Austin, TX"},
                "updated_at": ts_recent,
                "absolute_url": "https://boards.greenhouse.io/gamma/jobs/302",
                "content": "<p>Python and AWS distributed systems role in Austin, TX.</p>",
            },
            {
                "id": 303,
                "title": "Junior Software Engineer",
                "location": {"name": "Seattle, WA"},
                "updated_at": ts_recent,
                "absolute_url": "https://boards.greenhouse.io/gamma/jobs/303",
                "content": "<p>Entry role in Seattle.</p>",
            },
        ]
    }
    slow_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal slow_calls
        url_str = str(request.url)
        if "boards-api.greenhouse.io/v1/boards/gamma/jobs" in url_str:
            return httpx.Response(200, json=gh_jobs)
        if "seeMoreJobPostings/search" in url_str:
            slow_calls += 1
            li_entered.set()
            allow_li_finish.wait(timeout=2.0)
            return httpx.Response(200, text="<html><body></body></html>")
        return httpx.Response(404)

    mock_http = httpx.Client(transport=httpx.MockTransport(handler))
    client, _output_dir = _build_client(tmp_path)

    try:
        with client:
            client.app.state.scrape_http_client = mock_http
            cfg = client.put(
                "/api/config",
                json={
                    "updates": {
                        "target_role_tracks": ["senior_swe"],
                        "target_locations": ["Seattle, WA"],
                        "work_authorization": "h1b",
                        "job_types": ["full-time"],
                        "target_salary_min": 150000,
                        "scraper_sources": ["greenhouse"],
                        "company_boards": ["greenhouse:gamma"],
                        "title_blocklist": ["junior", "intern"],
                    }
                },
            )
            assert cfg.status_code == 200
            assert client.post("/api/resumes", json=_sample_resume_payload("Main SWE", "senior_swe")).status_code == 201

            # 1) Session 1 captures 1 saved + 2 rule-filtered roles
            s1 = client.post("/api/sessions", json={"name": "Audit Session 1", "posted_within": "24h"}).json()["id"]
            r1 = client.post(
                f"/api/sessions/{s1}/scrape",
                json={"sources": ["greenhouse"], "company_boards": ["greenhouse:gamma"], "locations": ["Seattle, WA"]},
            )
            assert r1.status_code == 200
            assert r1.json()["saved_count"] == 1
            assert r1.json()["filtered_count"] == 2

            f1 = client.get(f"/api/sessions/{s1}/filtered").json()
            assert len(f1) == 2
            assert {item["category"] for item in f1} == {"auto_filtered"}
            assert {item["filter_reason"] for item in f1} == {"location_mismatch", "blocked_title"}

            # 2) Session 2 sees all 3 as seen/skipped and differentiates them from rule-filtered
            s2 = client.post("/api/sessions", json={"name": "Audit Session 2", "posted_within": "24h"}).json()["id"]
            r2 = client.post(
                f"/api/sessions/{s2}/scrape",
                json={"sources": ["greenhouse"], "company_boards": ["greenhouse:gamma"], "locations": ["Seattle, WA"]},
            )
            assert r2.status_code == 200
            assert r2.json()["saved_count"] == 0
            assert r2.json()["duplicate_skipped_count"] == 3

            sessions_meta = {s["id"]: s for s in client.get("/api/sessions").json()}
            assert sessions_meta[s2]["seen_skipped_count"] == 3

            f2 = client.get(f"/api/sessions/{s2}/filtered").json()
            assert len(f2) == 3
            assert {item["category"] for item in f2} == {"seen_skipped"}
            seen_reasons = {item["filter_reason"] for item in f2}
            assert seen_reasons == {"seen:saved", "seen:auto_filtered"}

            # Promote 2 selected rows from s2's Seen/Skipped list into s2's Saved Jobs
            austin_seen = next(item for item in f2 if "Austin" in item["location"])
            seattle_seen = next(item for item in f2 if item["filter_reason"] == "seen:saved")
            promo = client.post(
                f"/api/sessions/{s2}/filtered/promote",
                json={"filtered_ids": [seattle_seen["id"], austin_seen["id"]]},
            )
            assert promo.status_code == 200
            assert promo.json()["added_count"] == 2
            assert promo.json()["already_saved_count"] == 0

            s2_jobs = client.get(f"/api/jobs?session_id={s2}").json()
            assert len(s2_jobs) == 2
            # Re-promoting is idempotent
            promo_again = client.post(
                f"/api/sessions/{s2}/filtered/promote",
                json={"filtered_ids": [austin_seen["id"]]},
            )
            assert promo_again.status_code == 200
            assert promo_again.json()["added_count"] == 0
            assert promo_again.json()["already_saved_count"] == 1

            # Discard & bulk-restore from Discarded tab
            target_job_id = s2_jobs[0]["id"]
            assert client.patch(f"/api/jobs/{target_job_id}", json={"disposition": "discarded"}).status_code == 200
            assert len(client.get(f"/api/jobs?session_id={s2}").json()) == 1
            assert len(client.get(f"/api/jobs?session_id={s2}&include_discarded=true").json()) == 2
            restore = client.post(
                f"/api/sessions/{s2}/discarded/restore",
                json={"job_ids": [target_job_id]},
            )
            assert restore.status_code == 200
            assert restore.json()["added_count"] == 1
            assert len(client.get(f"/api/jobs?session_id={s2}").json()) == 2

            # 3) Mid-run Stop Scrape preserves fast board candidates and stops subsequent LinkedIn queries
            gh_jobs["jobs"][0]["id"] = 304
            gh_jobs["jobs"][0]["absolute_url"] = "https://boards.greenhouse.io/gamma/jobs/304"
            gh_jobs["jobs"][0]["title"] = "Senior Software Engineer II"
            s3 = client.post("/api/sessions", json={"name": "Stoppable Session", "posted_within": "24h"}).json()["id"]
            start = client.post(
                f"/api/sessions/{s3}/scrape/start",
                json={
                    "sources": ["greenhouse", "linkedin"],
                    "company_boards": ["greenhouse:gamma"],
                    "role_tracks": ["senior_swe", "ai_engineer"],
                    "locations": ["Seattle, WA"],
                },
            )
            assert start.status_code == 200
            assert li_entered.wait(timeout=3.0)
            stop_resp = client.post(f"/api/sessions/{s3}/scrape/stop")
            assert stop_resp.status_code == 200
            allow_li_finish.set()

            prog = stop_resp.json()
            for _ in range(50):
                if prog["status"] in ("cancelled", "completed", "failed"):
                    break
                time.sleep(0.03)
                prog = client.get(f"/api/sessions/{s3}/scrape/progress").json()

            assert prog["status"] == "cancelled", prog
            assert prog["result"]["cancelled"] is True
            assert slow_calls == 1
            # Job 304 from Greenhouse board fetched before stop was preserved!
            s3_jobs = client.get(f"/api/jobs?session_id={s3}").json()
            assert len(s3_jobs) == 1
            assert s3_jobs[0]["analysis"]["title"] == "Senior Software Engineer II"

            # Master flush deletes SessionFilteredJobRecord without FK errors
            flush_res = client.post("/api/data/flush", json={"master_flush": True})
            assert flush_res.status_code == 200
            assert client.get("/api/sessions").json() == []
    finally:
        allow_li_finish.set()
        mock_http.close()


def test_us_only_default_primary_location_and_all_unsuitability_reasons(tmp_path: Path) -> None:
    """Verify US-only default even when locations=[] and capture of ALL unsuitability reasons."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    recent_iso = (now - timedelta(minutes=15)).isoformat()
    stale_iso = (now - timedelta(days=3)).isoformat()

    gh_jobs = {
        "jobs": [
            {
                "id": 401,
                "title": "Senior Software Engineer",
                "location": {"name": "Chicago, IL"},
                "updated_at": recent_iso,
                "absolute_url": "https://boards.greenhouse.io/usonly/jobs/401",
                "content": "<p>Python and Go microservices in Chicago, IL. We sponsor H-1B visas.</p>",
            },
            {
                "id": 402,
                "title": "Junior Account Executive",
                "location": {"name": "Toronto, ON"},
                "updated_at": stale_iso,
                "absolute_url": "https://boards.greenhouse.io/usonly/jobs/402",
                "content": (
                    "<p>We cannot sponsor visas for this role. Salary $95,000 per year.</p>"
                ),
            },
            {
                "id": 403,
                "title": "Senior AI Engineer",
                "location": {"name": "Remote, Europe"},
                "updated_at": recent_iso,
                "absolute_url": "https://boards.greenhouse.io/usonly/jobs/403",
                "content": "<p>Remote engineering across EMEA.</p>",
            },
        ]
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        if "boards-api.greenhouse.io/v1/boards/usonly/jobs" in str(request.url):
            return httpx.Response(200, json=gh_jobs)
        return httpx.Response(404)

    mock_http = httpx.Client(transport=httpx.MockTransport(_handler))
    client, _ = _build_client(tmp_path)
    try:
        with client:
            client.app.state.scrape_http_client = mock_http
            cfg = client.put(
                "/api/config",
                json={
                    "updates": {
                        "target_role_tracks": ["senior_swe", "ai_engineer"],
                        "target_locations": [],
                        "work_authorization": "h1b",
                        "job_types": ["full-time"],
                        "target_salary_min": 175000,
                        "scraper_sources": ["greenhouse"],
                        "company_boards": ["greenhouse:usonly"],
                        "title_blocklist": ["junior", "account executive"],
                    }
                },
            )
            assert cfg.status_code == 200

            s1 = client.post("/api/sessions", json={"name": "US Default Run", "posted_within": "24h"}).json()["id"]
            resp = client.post(
                f"/api/sessions/{s1}/scrape",
                json={
                    "sources": ["greenhouse"],
                    "company_boards": ["greenhouse:usonly"],
                    "locations": [],
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            # Chicago, IL (US) passes by default; Toronto, ON & Remote, Europe are blocked by US guard
            assert data["saved_count"] == 1
            assert data["saved_jobs"][0]["analysis"]["location"] == "Chicago, IL"
            assert data["filtered_count"] == 2

            filtered = client.get(f"/api/sessions/{s1}/filtered").json()
            assert len(filtered) == 2
            toronto = next(item for item in filtered if "Toronto" in item["location"])
            assert toronto["filter_reason"] == "location_mismatch"
            assert set(toronto["filter_reasons"]) >= {
                "location_mismatch",
                "stale_outside_window",
                "blocked_title",
                "role_mismatch",
                "no_h1b_sponsorship",
                "below_min_salary",
            }
            assert len(toronto["suitability_notes"]) >= 5
            europe = next(item for item in filtered if "Europe" in item["location"])
            assert europe["filter_reason"] == "location_mismatch"
    finally:
        mock_http.close()


def test_expanded_role_tracks_level_disambiguation(tmp_path: Path) -> None:
    """Verify Staff vs Mid vs Founding/MTS aliases match their intended level without leakage."""
    from datetime import datetime, timedelta, timezone

    now_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    gh_jobs = {
        "jobs": [
            {
                "id": 501,
                "title": "Staff Member of Technical Staff",
                "location": {"name": "San Francisco, CA"},
                "updated_at": now_iso,
                "absolute_url": "https://boards.greenhouse.io/frontier/jobs/501",
                "content": "<p>8+ years experience leading distributed LLM architecture in Python and Go. We sponsor H-1B.</p>",
            },
            {
                "id": 502,
                "title": "Member of Technical Staff",
                "location": {"name": "San Francisco, CA"},
                "updated_at": now_iso,
                "absolute_url": "https://boards.greenhouse.io/frontier/jobs/502",
                "content": "<p>3+ years experience shipping production APIs. We sponsor H-1B.</p>",
            },
            {
                "id": 503,
                "title": "Founding AI Engineer",
                "location": {"name": "New York, NY"},
                "updated_at": now_iso,
                "absolute_url": "https://boards.greenhouse.io/frontier/jobs/503",
                "content": "<p>Build 0 to 1 product in TypeScript, React, Python. We sponsor H-1B.</p>",
            },
        ]
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        if "boards-api.greenhouse.io/v1/boards/frontier/jobs" in str(request.url):
            return httpx.Response(200, json=gh_jobs)
        return httpx.Response(404)

    mock_http = httpx.Client(transport=httpx.MockTransport(_handler))
    client, _ = _build_client(tmp_path)
    try:
        with client:
            client.app.state.scrape_http_client = mock_http
            assert (
                client.put(
                    "/api/config",
                    json={
                        "updates": {
                            "target_role_tracks": ["staff_swe", "founding_engineer"],
                            "target_locations": ["ALL_US"],
                            "work_authorization": "h1b",
                            "target_yoe_min": None,
                            "target_yoe_max": None,
                            "scraper_sources": ["greenhouse"],
                            "company_boards": ["greenhouse:frontier"],
                            "title_blocklist": ["intern"],
                        }
                    },
                ).status_code
                == 200
            )
            s1 = client.post("/api/sessions", json={"name": "Role Levels", "posted_within": "24h"}).json()["id"]
            resp = client.post(
                f"/api/sessions/{s1}/scrape",
                json={
                    "role_tracks": ["staff_swe", "founding_engineer"],
                    "sources": ["greenhouse"],
                    "company_boards": ["greenhouse:frontier"],
                    "locations": ["ALL_US"],
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["saved_count"] == 2
            by_title = {j["analysis"]["title"]: j["analysis"]["role_track"] for j in data["saved_jobs"]}
            assert by_title == {
                "Staff Member of Technical Staff": "staff_swe",
                "Founding AI Engineer": "founding_engineer",
            }
            filtered = client.get(f"/api/sessions/{s1}/filtered").json()
            assert len(filtered) == 1
            assert filtered[0]["title"] == "Member of Technical Staff"
            assert filtered[0]["filter_reason"] == "role_mismatch"
    finally:
        mock_http.close()


def test_reports_clean_capitalization_and_no_paths(tmp_path: Path) -> None:
    """Verify Reports API returns clean capitalized labels and exposes zero local file paths."""
    client, _ = _build_client(tmp_path)
    with client:
        boot = client.post(
            "/api/resumes/bootstrap",
            json={"full_name": "Alex Rivera", "role_track": "senior_swe", "use_llm": False, "save_as_base": True},
        )
        assert boot.status_code == 201
        res_id = boot.json()["resume"]["id"]

        sess = client.post("/api/sessions", json={"name": "Capitalization Check", "posted_within": "24h"}).json()
        ingest = client.post(
            "/api/jobs/ingest",
            json={
                "session_id": sess["id"],
                "raw_text": (
                    "Senior Software Engineer\nCompany: Stripe\nLocation: Seattle, WA\n"
                    "Requirements: Python, FastAPI, Docker, Kubernetes, PostgreSQL, Redis, CI/CD.\n"
                ),
            },
        )
        assert ingest.status_code == 201
        job_id = ingest.json()["id"]

        exp = client.post(
            "/api/export",
            json={"job_id": job_id, "resume_id": res_id, "formats": ["docx"]},
        )
        assert exp.status_code == 201

        rep_resp = client.get("/api/reports")
        assert rep_resp.status_code == 200
        rep = rep_resp.json()
        assert rep["html_report_path"] is None
        role_labels = [b["label"] for b in rep["by_role"]]
        source_labels = [b["label"] for b in rep["by_source"]]
        status_labels = [b["label"] for b in rep["by_status"]]
        assert "Senior Software Engineer" in role_labels
        assert "senior_swe" not in role_labels
        assert "Resume Created" in status_labels
        assert "resume_created" not in status_labels
        assert all("_" not in lbl for lbl in source_labels + status_labels + role_labels)


def test_bulk_session_export_auto_seniority_and_zip(tmp_path: Path) -> None:
    """Verify bulk session export auto-sizes 6-8 YoE senior roles, targets 80-85% band, and serves zip."""
    client, _ = _build_client(tmp_path)
    with client:
        boot = client.post(
            "/api/resumes/bootstrap",
            json={
                "full_name": "Alex Rivera",
                "role_track": "senior_swe",
                "years_experience": 7,
                "employers": [
                    {"company": "Amazon", "title": "Senior SWE", "start_date": "Jan 2022", "end_date": "Present", "bullets_count": 6},
                    {"company": "Intuit", "title": "SWE II", "start_date": "Jan 2020", "end_date": "Dec 2021", "bullets_count": 5},
                ],
                "use_llm": False,
                "save_as_base": True,
            },
        )
        assert boot.status_code == 201
        res_id = boot.json()["resume"]["id"]

        sess_id = client.post("/api/sessions", json={"name": "Bulk Test", "posted_within": "24h"}).json()["id"]
        j1 = client.post(
            "/api/jobs/ingest",
            json={
                "session_id": sess_id,
                "raw_text": (
                    "Senior Distributed Systems Engineer\nCompany: Databricks\nLocation: San Francisco, CA\n"
                    "6-8 years experience building scalable Python, Go, Kafka, Spark, Kubernetes, Docker, "
                    "PostgreSQL, Terraform, and CI/CD infrastructure.\n"
                ),
            },
        ).json()["id"]
        j2 = client.post(
            "/api/jobs/ingest",
            json={
                "session_id": sess_id,
                "raw_text": (
                    "Software Engineer II\nCompany: Figma\nLocation: New York, NY\n"
                    "3 years experience with TypeScript, Python, React, PostgreSQL, Redis, Docker, and AWS.\n"
                ),
            },
        ).json()["id"]

        bulk_resp = client.post(
            f"/api/sessions/{sess_id}/bulk-export",
            json={
                "resume_id": res_id,
                "formats": ["docx"],
                "tailor_strategy": "fallback_script",
                "auto_size": True,
                "target_score_min": 80,
                "target_score_max": 85,
            },
        )
        assert bulk_resp.status_code == 200
        bulk = bulk_resp.json()
        assert bulk["total_saved_jobs"] == 2
        assert bulk["succeeded_count"] == 2
        assert bulk["failed_count"] == 0
        by_job = {item["job_id"]: item for item in bulk["items"]}
        assert by_job[j1]["page_budget"] == 2.0
        assert by_job[j1]["bullets_per_role_counts"][0] >= 6
        assert any(f.endswith(f"_J{j1}_R{by_job[j1]['run_id']}.docx") for f in by_job[j1]["generated_files"])
        assert any(f.endswith(f"_J{j2}_R{by_job[j2]['run_id']}.docx") for f in by_job[j2]["generated_files"])
        assert 80.0 <= by_job[j1]["tailored_score"] <= 85.0
        assert 80.0 <= by_job[j2]["tailored_score"] <= 85.0

        zip_resp = client.get(bulk["zip_download_url"])
        assert zip_resp.status_code == 200
        assert "application/zip" in zip_resp.headers["content-type"]
        assert zip_resp.content[:2] == b"PK"

