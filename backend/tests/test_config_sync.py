"""Tests verifying two-way config sync, schema dropdowns, and role track loading."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from backend.app.config import ROLE_TRACKS_DIR, RULES_PATH
from backend.app.main import create_app
from backend.app.services.config_manager import ConfigManager


def _make_test_client(tmp_path: Path) -> tuple[TestClient, Path, Path]:
    cfg_dir = tmp_path / "config"
    tracks_dir = cfg_dir / "role_tracks"
    rules_dir = cfg_dir / "rules"
    tracks_dir.mkdir(parents=True)
    rules_dir.mkdir(parents=True)

    for yaml_file in ROLE_TRACKS_DIR.glob("*.yaml"):
        shutil.copy(yaml_file, tracks_dir / yaml_file.name)
    shutil.copy(RULES_PATH, rules_dir / "big_tech_rules.yaml")

    settings_file = cfg_dir / "settings.yaml"
    settings_file.write_text(
        yaml.safe_dump(
            {
                "target_role_tracks": [],
                "llm_mode": None,
                "llm_model": "qwen3:14b",
                "export_formats": ["pdf", "docx"],
                "page_budget": 1,
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
    app = create_app(config_manager=manager, db_path=tmp_path / "test.db")
    return TestClient(app), settings_file, tracks_dir


def test_missing_defaults_surface_schema_dropdowns(tmp_path: Path) -> None:
    client, _, _ = _make_test_client(tmp_path)
    with client:
        resp = client.get("/api/config")
        assert resp.status_code == 200
        body = resp.json()

        assert body["needs_setup"] is True
        assert set(body["missing_defaults"]) == {
            "target_role_tracks",
            "llm_mode",
        }

        fields_by_key = {f["key"]: f for f in body["fields"]}
        track_options = {opt["value"] for opt in fields_by_key["target_role_tracks"]["options"]}
        assert {"senior_swe", "ai_engineer", "fde"} <= track_options


def test_ui_update_writes_local_yaml_file_and_clears_setup(tmp_path: Path) -> None:
    client, settings_file, _ = _make_test_client(tmp_path)
    with client:
        resp = client.put(
            "/api/config",
            json={
                "updates": {
                    "target_role_tracks": ["senior_swe", "ai_engineer"],
                    "llm_mode": "ollama_docker",
                    "target_salary_min": 185000,
                }
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["needs_setup"] is False
        assert body["missing_defaults"] == []
        assert body["values"]["target_role_tracks"] == ["senior_swe", "ai_engineer"]
        assert body["values"]["target_salary_min"] == 185000
        assert body["values"]["strict_humanizer_gate"] is True

        disk_data = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
        assert disk_data["target_role_tracks"] == ["senior_swe", "ai_engineer"]
        assert disk_data["llm_mode"] == "ollama_docker"
        assert disk_data["target_salary_min"] == 185000


def test_disk_edit_reflects_immediately_in_api(tmp_path: Path) -> None:
    client, settings_file, _ = _make_test_client(tmp_path)
    with client:
        # Initial load
        assert client.get("/api/config").json()["values"]["page_budget"] == 1

        # Simulate external user edit on disk
        disk_data = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
        disk_data["target_role_tracks"] = ["fde", "senior_swe"]
        disk_data["llm_mode"] = "off"
        disk_data["page_budget"] = 2
        settings_file.write_text(yaml.safe_dump(disk_data, sort_keys=False), encoding="utf-8")

        refreshed = client.get("/api/config").json()
        assert refreshed["needs_setup"] is False
        assert refreshed["values"]["target_role_tracks"] == ["fde", "senior_swe"]
        assert refreshed["values"]["page_budget"] == 2


def test_invalid_config_update_rejected_cleanly(tmp_path: Path) -> None:
    client, settings_file, _ = _make_test_client(tmp_path)
    before_text = settings_file.read_text(encoding="utf-8")
    with client:
        resp = client.put(
            "/api/config",
            json={"updates": {"target_role_tracks": ["nonexistent_track"]}},
        )
        assert resp.status_code == 422
        assert settings_file.read_text(encoding="utf-8") == before_text


def test_role_track_keyword_and_alias_update_persists_to_yaml(tmp_path: Path) -> None:
    client, _, tracks_dir = _make_test_client(tmp_path)
    with client:
        tracks = client.get("/api/config/role-tracks").json()
        swe_track = next(t for t in tracks if t["id"] == "senior_swe")
        assert "SDE 2" in swe_track["aliases"]

        ai_track = next(t for t in tracks if t["id"] == "ai_engineer")
        updated_core = [*ai_track["keywords"]["core_must_have"], "mcp", "tool use"]

        resp = client.put(
            "/api/config/role-tracks/ai_engineer",
            json={
                "aliases": [*ai_track.get("aliases", []), "Applied AI Engineer"],
                "keywords": {
                    **ai_track["keywords"],
                    "core_must_have": updated_core,
                },
            },
        )
        assert resp.status_code == 200
        assert "mcp" in resp.json()["keywords"]["core_must_have"]
        assert "Applied AI Engineer" in resp.json()["aliases"]

        reloaded_yaml = yaml.safe_load((tracks_dir / "ai_engineer.yaml").read_text(encoding="utf-8"))
        assert "mcp" in reloaded_yaml["keywords"]["core_must_have"]
        assert "Applied AI Engineer" in reloaded_yaml["aliases"]


def test_health_and_rules_endpoints(tmp_path: Path) -> None:
    client, _, _ = _make_test_client(tmp_path)
    with client:
        expected_tracks = len(list(ROLE_TRACKS_DIR.glob("*.yaml")))
        assert expected_tracks >= 18

        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["role_tracks_loaded"] == expected_tracks

        tracks = client.get("/api/config/role-tracks").json()
        by_id = {t["id"]: t for t in tracks}
        assert {"entry_swe", "mid_swe", "senior_swe", "staff_swe", "principal_swe", "founding_engineer"} <= set(by_id)
        assert by_id["staff_swe"]["typical_yoe_label"] == "8–12+ yrs"
        assert by_id["staff_swe"]["target_yoe_range"] == [8, 12]
        assert any("L6" in ex for ex in by_id["staff_swe"]["company_examples"])

        cfg = client.get("/api/config").json()
        target_field = next(f for f in cfg["fields"] if f["key"] == "target_role_tracks")
        staff_opt = next(o for o in target_field["options"] if o["value"] == "staff_swe")
        assert "8–12+ yrs" in staff_opt["label"]


def test_filter_settings_sync_and_missing_clear_default(tmp_path: Path) -> None:
    client, settings_path, _ = _make_test_client(tmp_path)
    with client:
        resp = client.put(
            "/api/config",
            json={
                "updates": {
                    "target_role_tracks": ["senior_swe", "ai_engineer"],
                    "llm_mode": "off",
                    "work_authorization": "h1b",
                    "posted_within_default": "1h",
                    "target_locations": ["Seattle, WA", "San Diego, CA"],
                    "job_types": ["full-time"],
                    "resume_filename_format": "{full_name}_{company}_{role}",
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["values"]["work_authorization"] == "h1b"
        assert data["values"]["posted_within_default"] == "1h"
        assert data["values"]["target_locations"] == ["Seattle, WA", "San Diego, CA"]
        written = settings_path.read_text(encoding="utf-8")
        assert "h1b" in written
        assert "Seattle, WA" in written

        rules = client.get("/api/config/rules")
        assert rules.status_code == 200
        assert rules.json()["ats_formatting"]["single_column_only"] is True


def test_optional_yoe_bounds_and_eastern_timezone(tmp_path: Path) -> None:
    from datetime import datetime, timezone
    from backend.app.services.timezone_utils import to_eastern

    client, settings_path, _ = _make_test_client(tmp_path)
    with client:
        # Clearing both Min YoE and Max YoE should succeed without validation error
        resp = client.put(
            "/api/config",
            json={
                "updates": {
                    "target_role_tracks": ["senior_swe"],
                    "llm_mode": "off",
                    "target_yoe_min": None,
                    "target_yoe_max": None,
                }
            },
        )
        assert resp.status_code == 200
        vals = resp.json()["values"]
        assert vals["target_yoe_min"] is None
        assert vals["target_yoe_max"] is None
        disk_data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        assert disk_data["target_yoe_min"] is None
        assert disk_data["target_yoe_max"] is None

        # Only Min YoE set with Max YoE empty should also succeed
        one_bound = client.put(
            "/api/config",
            json={"updates": {"target_yoe_min": 5, "target_yoe_max": None}},
        )
        assert one_bound.status_code == 200
        assert one_bound.json()["values"]["target_yoe_min"] == 5
        assert one_bound.json()["values"]["target_yoe_max"] is None

        # Session timestamps serialize with Eastern offset (-05:00 or -04:00)
        sess_resp = client.post("/api/sessions", json={"name": "Eastern TZ Check"})
        assert sess_resp.status_code == 201
        created_at = sess_resp.json()["created_at"]
        assert created_at.endswith("-05:00") or created_at.endswith("-04:00")

        # Job ingestion works cleanly with None Max YoE and returns Eastern timestamps
        ingest = client.post(
            "/api/jobs/ingest",
            json={
                "session_id": sess_resp.json()["id"],
                "raw_text": "Senior Backend Engineer at Acme\nLocation: New York, NY\nRequirements: 12+ years of Python, Distributed Systems.",
            },
        )
        assert ingest.status_code == 201
        assert ingest.json()["created_at"].endswith("-05:00") or ingest.json()["created_at"].endswith("-04:00")

    # Verify naive UTC datetime converts 23:40 UTC -> 18:40 EST in November
    naive_utc = datetime(2026, 11, 11, 23, 40)
    eastern_dt = to_eastern(naive_utc)
    assert eastern_dt is not None
    assert eastern_dt.hour == 18
    assert eastern_dt.minute == 40
    assert eastern_dt.tzname() == "EST"
    # Verify aware UTC conversion matches
    assert to_eastern(datetime(2026, 7, 15, 22, 40, tzinfo=timezone.utc)).hour == 18


def test_basic_auth_protection_and_container_env_overrides(tmp_path: Path, monkeypatch) -> None:
    """Verify HTTP Basic Auth locks down endpoints cleanly and env overrides do not corrupt settings.yaml."""
    import base64

    monkeypatch.setenv("CAREERFLOW_BASIC_AUTH_USER", "pramit")
    monkeypatch.setenv("CAREERFLOW_BASIC_AUTH_PASS", "test-pass-9876")
    monkeypatch.setenv("CAREERFLOW_OLLAMA_BASE_URL", "http://host.docker.internal:11434")

    client, settings_path, _ = _make_test_client(tmp_path)
    with client:
        # Unauthenticated /api/health returns minimal probe only without leaking details
        health_unauth = client.get("/api/health")
        assert health_unauth.status_code == 200
        assert health_unauth.json() == {"status": "ok"}
        assert health_unauth.headers["X-Content-Type-Options"] == "nosniff"
        assert health_unauth.headers["X-Frame-Options"] == "DENY"

        # Protected endpoints require HTTP Basic Auth
        unauth_cfg = client.get("/api/config")
        assert unauth_cfg.status_code == 401
        assert "Basic" in unauth_cfg.headers.get("WWW-Authenticate", "")

        bad_token = base64.b64encode(b"pramit:wrong-pass").decode("ascii")
        bad_cfg = client.get("/api/config", headers={"Authorization": f"Basic {bad_token}"})
        assert bad_cfg.status_code == 401

        good_token = base64.b64encode(b"pramit:test-pass-9876").decode("ascii")
        headers = {"Authorization": f"Basic {good_token}"}
        good_health = client.get("/api/health", headers=headers)
        assert good_health.status_code == 200
        assert "role_tracks_loaded" in good_health.json()

        good_cfg = client.get("/api/config", headers=headers)
        assert good_cfg.status_code == 200
        assert good_cfg.json()["values"]["ollama_base_url"] == "http://host.docker.internal:11434"

        # Updating unrelated settings should keep settings.yaml clean on disk
        upd = client.put("/api/config", headers=headers, json={"updates": {"page_budget": 1.5}})
        assert upd.status_code == 200
        disk_data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        assert disk_data["ollama_base_url"] == "http://localhost:11434"

        # Repeated wrong-credential attempts lock out brute-force client IP with 429
        for attempt in range(8):
            res = client.get(
                "/api/config",
                headers={"Authorization": f"Basic {bad_token}", "CF-Connecting-IP": "198.51.100.42"},
            )
            if attempt < 7:
                assert res.status_code == 401
            else:
                assert res.status_code == 429
                assert int(res.headers.get("Retry-After", "0")) > 0
        # Legitimate client IP remains unaffected and unauthenticated /api/health still answers ok
        still_ok = client.get("/api/config", headers=headers)
        assert still_ok.status_code == 200

