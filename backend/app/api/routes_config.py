"""Endpoints for two-way configuration sync, role keyword packs, and ATS rules."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from backend.app.api.deps import get_config_manager
from backend.app.schemas.config import (
    BigTechRulesConfig,
    ConfigResponse,
    ConfigUpdateRequest,
    RoleTrackConfig,
    RoleTrackUpdateRequest,
)
from backend.app.services.config_manager import ConfigManager

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
