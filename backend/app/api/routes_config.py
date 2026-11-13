"""Endpoints for two-way configuration sync, role keyword packs, and ATS rules."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from backend.app.api.deps import get_config_manager
from backend.app.schemas.config import (
    BigTechRulesConfig,
    ConfigResponse,
    ConfigUpdateRequest,
    LlmBenchmarkRequest,
    LlmBenchmarkResponse,
    LlmStatusResponse,
    LlmTestRequest,
    LlmTestResponse,
    RoleTrackConfig,
    RoleTrackUpdateRequest,
)
from backend.app.services.config_manager import ConfigManager
from backend.app.services.llm_tailor import (
    benchmark_ollama_models,
    check_ollama_status,
    test_ollama_connection,
)
from backend.app.services.locations import ALL_US_TECH_CITIES, OTHER_US_TECH_CITIES, TOP_20_US_LOCATIONS

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
def read_config(manager: ConfigManager = Depends(get_config_manager)) -> ConfigResponse:
    """Return current settings, schema-driven dropdown options, and missing defaults."""
    return manager.get_config_response()


@router.put("", response_model=ConfigResponse)
def update_config(
    payload: ConfigUpdateRequest,
    manager: ConfigManager = Depends(get_config_manager),
) -> ConfigResponse:
    """Validate partial updates and write them atomically to config/settings.yaml."""
    try:
        return manager.update_settings(payload.updates)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/role-tracks", response_model=list[RoleTrackConfig])
def list_role_tracks(
    manager: ConfigManager = Depends(get_config_manager),
) -> list[RoleTrackConfig]:
    """Return all configured role tracks and their weighted keyword packs."""
    return manager.list_role_tracks()


@router.put("/role-tracks/{track_id}", response_model=RoleTrackConfig)
def update_role_track(
    track_id: str,
    payload: RoleTrackUpdateRequest,
    manager: ConfigManager = Depends(get_config_manager),
) -> RoleTrackConfig:
    """Update a role track's keywords, aliases, or weights and persist to its YAML file."""
    try:
        return manager.update_role_track(track_id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/rules", response_model=BigTechRulesConfig)
def read_rules(manager: ConfigManager = Depends(get_config_manager)) -> BigTechRulesConfig:
    """Return the Big Tech Senior ATS & recruiter rubric."""
    return manager.get_rules()


@router.get("/locations")
def list_us_locations() -> dict[str, list[str]]:
    """Return Top 20 US tech hubs and the full curated US tech cities list."""
    return {
        "top_20": TOP_20_US_LOCATIONS,
        "other_us": OTHER_US_TECH_CITIES,
        "all_us": ALL_US_TECH_CITIES,
    }


@router.get("/llm/status", response_model=LlmStatusResponse)
def get_llm_status(
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
) -> LlmStatusResponse:
    """Inspect local Ollama reachability and available single open-source models."""
    settings = manager.get_settings()
    ollama_client = getattr(request.app.state, "ollama_http_client", None)
    return check_ollama_status(settings, client=ollama_client)


@router.post("/llm/test", response_model=LlmTestResponse)
def test_llm_endpoint(
    payload: LlmTestRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
) -> LlmTestResponse:
    """Run a quick live JSON probe against the configured single local Ollama model."""
    settings = manager.get_settings()
    ollama_client = getattr(request.app.state, "ollama_http_client", None)
    return test_ollama_connection(
        base_url=payload.base_url or settings.ollama_base_url,
        model=payload.model or settings.llm_model,
        client=ollama_client,
    )


@router.post("/llm/benchmark", response_model=LlmBenchmarkResponse)
def benchmark_llm_endpoint(
    payload: LlmBenchmarkRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
) -> LlmBenchmarkResponse:
    """Benchmark and rank installed local Ollama models on tailoring JSON reliability, accuracy, and speed."""
    settings = manager.get_settings()
    ollama_client = getattr(request.app.state, "ollama_http_client", None)
    return benchmark_ollama_models(
        base_url=payload.base_url or settings.ollama_base_url,
        requested_models=payload.models,
        client=ollama_client,
    )
