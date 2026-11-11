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
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["role_tracks_loaded"] == 6


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
