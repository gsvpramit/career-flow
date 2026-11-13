"""Two-way YAML configuration manager and schema registry."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from backend.app.config import ROLE_TRACKS_DIR, RULES_PATH, SETTINGS_PATH
from backend.app.schemas.config import (
    AppSettings,
    BigTechRulesConfig,
    ConfigFieldSchema,
    ConfigOption,
    ConfigResponse,
    RoleTrackConfig,
    RoleTrackUpdateRequest,
)

SETTINGS_HEADER = (
    "# CareerFlow — Runtime Configuration (Two-Way Synced with UI)\n"
    "# Any edits here automatically reflect in the Backend & UI.\n\n"
)


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    parsed = yaml.safe_load(raw)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected YAML mapping in {path}, got {type(parsed).__name__}")
    return parsed


def _write_yaml_atomic(path: Path, payload: dict[str, Any], header: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    content = f"{header}{dumped}" if header else dumped
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}_", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


class ConfigManager:
    """Manages two-way sync between local YAML config files, backend services, and UI."""

    def __init__(
        self,
        settings_path: Path = SETTINGS_PATH,
        role_tracks_dir: Path = ROLE_TRACKS_DIR,
        rules_path: Path = RULES_PATH,
    ) -> None:
        self.settings_path = settings_path
        self.role_tracks_dir = role_tracks_dir
        self.rules_path = rules_path
        self._cached_settings: AppSettings | None = None
        self._settings_mtime_ns: int = -1
        self._cached_tracks: dict[str, RoleTrackConfig] = {}
        self._tracks_signature: tuple[tuple[str, int], ...] = ()
        self._cached_rules: BigTechRulesConfig | None = None
        self._rules_mtime_ns: int = -1

    def ensure_initialized(self) -> None:
        """Create default settings.yaml if missing on disk."""
        if not self.settings_path.exists():
            defaults = AppSettings().model_dump()
            _write_yaml_atomic(self.settings_path, defaults, header=SETTINGS_HEADER)
        self.get_settings()
        self.list_role_tracks()
        self.get_rules()

    def get_settings(self) -> AppSettings:
        """Load settings.yaml, automatically reloading when modified on disk."""
        if not self.settings_path.exists():
            defaults = AppSettings().model_dump()
            _write_yaml_atomic(self.settings_path, defaults, header=SETTINGS_HEADER)

        mtime_ns = self.settings_path.stat().st_mtime_ns
        if self._cached_settings is not None and mtime_ns == self._settings_mtime_ns:
            cached = self._cached_settings
        else:
            raw = _read_yaml_file(self.settings_path)
            cached = AppSettings.model_validate(raw)
            self._validate_track_references(cached.target_role_tracks)
            self._cached_settings = cached
            self._settings_mtime_ns = mtime_ns

        env_ollama_url = os.getenv("CAREERFLOW_OLLAMA_BASE_URL", "").strip()
        if env_ollama_url and cached.ollama_base_url != env_ollama_url:
            return cached.model_copy(update={"ollama_base_url": env_ollama_url})
        return cached

    def update_settings(self, updates: dict[str, Any]) -> ConfigResponse:
        """Validate partial updates, persist atomically to YAML, and return full config."""
        valid_keys = set(AppSettings.model_fields.keys())
        unknown_keys = sorted(set(updates.keys()) - valid_keys)
        if unknown_keys:
            raise ValueError(f"Unknown config field(s): {', '.join(unknown_keys)}")

        disk_raw = _read_yaml_file(self.settings_path) if self.settings_path.exists() else {}
        current = AppSettings.model_validate(disk_raw).model_dump() if disk_raw else self.get_settings().model_dump()
        merged = {**current, **updates}
        validated = AppSettings.model_validate(merged)
        self._validate_track_references(validated.target_role_tracks)

        _write_yaml_atomic(self.settings_path, validated.model_dump(), header=SETTINGS_HEADER)
        self._cached_settings = validated
        self._settings_mtime_ns = self.settings_path.stat().st_mtime_ns
        return self.get_config_response()

    def list_role_tracks(self) -> list[RoleTrackConfig]:
        """Return all role tracks from config/role_tracks/*.yaml in ladder/domain order."""
        if not self.role_tracks_dir.exists():
            return []

        files = sorted(self.role_tracks_dir.glob("*.yaml"))
        signature = tuple((f.name, f.stat().st_mtime_ns) for f in files)
        if signature == self._tracks_signature and self._cached_tracks:
            return list(self._cached_tracks.values())

        loaded: list[RoleTrackConfig] = []
        for file_path in files:
            raw = _read_yaml_file(file_path)
            if not raw:
                continue
            track = RoleTrackConfig.model_validate(raw)
            if not track.typical_yoe_label and len(track.target_yoe_range) >= 2:
                track.typical_yoe_label = f"{track.target_yoe_range[0]}–{track.target_yoe_range[1]} yrs"
            loaded.append(track)

        preferred_order = [
            "entry_swe",
            "mid_swe",
            "senior_swe",
            "staff_swe",
            "principal_swe",
            "ai_engineer",
            "ml_engineer",
            "applied_scientist",
            "mlops_ai_infra",
            "data_engineer",
            "data_scientist",
            "backend_systems",
            "fullstack_product",
            "founding_engineer",
            "fde",
            "platform_infra",
            "security_engineer",
            "solutions_architect",
        ]
        order_idx = {tid: idx for idx, tid in enumerate(preferred_order)}
        loaded.sort(key=lambda t: (order_idx.get(t.id, 999), t.display_name.lower()))

        tracks = {t.id: t for t in loaded}
        self._cached_tracks = tracks
        self._tracks_signature = signature
        return list(tracks.values())

    def get_role_track(self, track_id: str) -> RoleTrackConfig:
        """Fetch a single role track by ID or raise ValueError."""
        self.list_role_tracks()
        track = self._cached_tracks.get(track_id)
        if track is None:
            raise ValueError(f"Unknown role track '{track_id}'")
        return track

    def infer_role_track_for_title(self, title: str, preferred_ids: list[str] | None = None) -> str:
        """Infer best matching RoleTrack id from job title and aliases using longest-match scoring."""
        tracks = self.list_role_tracks()
        if not tracks:
            return "senior_swe"

        lower_title = f" {title.lower()} "
        candidates = [t for t in tracks if not preferred_ids or t.id in preferred_ids] or tracks
        best_id = candidates[0].id
        best_score = -1
        for track in candidates:
            terms = [track.display_name, *track.aliases]
            for term in terms:
                norm = term.strip().lower()
                if not norm:
                    continue
                if norm in lower_title and len(norm) > best_score:
                    best_score = len(norm)
                    best_id = track.id
        return best_id

    def update_role_track(self, track_id: str, patch: RoleTrackUpdateRequest) -> RoleTrackConfig:
        """Persist role track keyword, alias, level, or weight updates back to its YAML file."""
        existing = self.get_role_track(track_id)
        updated_data = existing.model_dump()
        for field_name in (
            "display_name",
            "category",
            "typical_yoe_label",
            "search_query",
            "company_examples",
            "target_yoe_range",
            "aliases",
            "description",
            "keywords",
            "weights",
        ):
            value = getattr(patch, field_name)
            if value is not None:
                updated_data[field_name] = value.model_dump() if hasattr(value, "model_dump") else value

        validated = RoleTrackConfig.model_validate(updated_data)
        target_file = self._resolve_track_file(track_id)
        _write_yaml_atomic(target_file, validated.model_dump())
        self._tracks_signature = ()
        self.list_role_tracks()
        return validated

    def get_rules(self) -> BigTechRulesConfig:
        """Load Big Tech ATS ruleset, reloading automatically if changed on disk."""
        if not self.rules_path.exists():
            return BigTechRulesConfig()

        mtime_ns = self.rules_path.stat().st_mtime_ns
        if self._cached_rules is not None and mtime_ns == self._rules_mtime_ns:
            return self._cached_rules

        raw = _read_yaml_file(self.rules_path)
        rules = BigTechRulesConfig.model_validate(raw)
        self._cached_rules = rules
        self._rules_mtime_ns = mtime_ns
        return rules

    def get_config_response(self) -> ConfigResponse:
        """Build simplified schema-driven configuration payload for the UI."""
        settings = self.get_settings()
        tracks = self.list_role_tracks()
        fields = self._build_field_schemas(settings, tracks)
        missing_defaults = [field.key for field in fields if field.is_missing]
        return ConfigResponse(
            values=settings,
            fields=fields,
            missing_defaults=missing_defaults,
            needs_setup=len(missing_defaults) > 0,
            last_modified_ns=self._settings_mtime_ns,
            config_path=str(self.settings_path),
        )

    def _validate_track_references(self, track_ids: list[str]) -> None:
        if not track_ids:
            return
        tracks = self.list_role_tracks()
        known_ids = {t.id for t in tracks}
        unknown = [tid for tid in track_ids if known_ids and tid not in known_ids]
        if unknown:
            raise ValueError(
                f"Unknown role track(s): {', '.join(unknown)}. Available: {sorted(known_ids)}"
            )

    def _resolve_track_file(self, track_id: str) -> Path:
        for file_path in sorted(self.role_tracks_dir.glob("*.yaml")):
            raw = _read_yaml_file(file_path)
            if raw.get("id") == track_id:
                return file_path
        return self.role_tracks_dir / f"{track_id}.yaml"

    def _build_field_schemas(
        self, settings: AppSettings, tracks: list[RoleTrackConfig]
    ) -> list[ConfigFieldSchema]:
        track_options = [
            ConfigOption(
                value=t.id,
                label=(
                    f"{t.display_name} ({t.typical_yoe_label})"
                    if t.typical_yoe_label
                    else t.display_name
                ),
                description=(
                    f"{', '.join(t.company_examples[:4])} — {t.description}"
                    if t.company_examples
                    else t.description
                ),
            )
            for t in tracks
        ]
        definitions: list[tuple[str, str, str, str, bool, list[ConfigOption]]] = [
            (
                "target_role_tracks",
                "Target Roles to Apply For",
                "Pick all role types you want to scrape & tailor resumes for (e.g., Senior SWE / SDE 2, AI Engineer, FDE).",
                "multi_select",
                True,
                track_options,
            ),
            (
                "page_budget",
                "Resume Page Limit",
                "Select 1, 1.5, or 2 pages depending on your preferred bullet density and history depth.",
                "select",
                True,
                [
                    ConfigOption(value=1, label="1 Page (Compact Standard)"),
                    ConfigOption(value=1.5, label="1.5 Pages (Balanced Senior)"),
                    ConfigOption(value=2, label="2 Pages (Extended Experience)"),
                ],
            ),
            (
                "default_bullets_per_role",
                "Bullets per Experience Role",
                "Default number of tailored bullet points generated per work experience entry.",
                "number",
                False,
                [],
            ),
            (
                "avoided_ai_words",
                "Avoided AI Words / Phrases",
                "Banned clichés excluded from LLM prompts and humanizer output (deselect or add words in Tailoring Studio).",
                "tags",
                False,
                [],
            ),
            (
                "custom_tailor_instructions",
                "Custom Tailoring Instructions",
                "Optional extra guidance injected into every resume tailoring prompt.",
                "text",
                False,
                [],
            ),
            (
                "target_salary_min",
                "Minimum Target Base Salary ($ USD / year)",
                "Used to highlight compensation fit on US roles; foreign currencies are shown in session metrics.",
                "number",
                False,
                [],
            ),
            (
                "llm_mode",
                "AI Tailoring Mode",
                "Use fast deterministic rules or invoke a single local Ollama model for tailoring, XYZ bootstrapping, and humanization.",
                "select",
                True,
                [
                    ConfigOption(
                        value="ollama_local",
                        label="Local Ollama AI (Single Model — Recommended)",
                        description="Runs tailoring, generic 5-year bootstrap, and anti-AI-slop humanizer on your local Ollama model.",
                    ),
                    ConfigOption(
                        value="off",
                        label="Built-In Rules Only (Fast & Offline)",
                        description="Deterministic keyword weights, XYZ checks, and humanizer cleanup.",
                    ),
                    ConfigOption(
                        value="ollama_docker",
                        label="Local Docker AI (Ollama Container)",
                        description="Uses Ollama endpoint via Docker or custom host port.",
                    ),
                ],
            ),
            (
                "llm_model",
                "Single Local Ollama Model",
                "One open-source Ollama model handles resume tailoring, generic bootstrap, and humanizer rewrites.",
                "text",
                False,
                [],
            ),
            (
                "ollama_base_url",
                "Ollama Endpoint URL",
                "Local or Docker Ollama API URL (default: http://localhost:11434).",
                "text",
                False,
                [],
            ),
            (
                "strict_humanizer_gate",
                "Strict Humanizer Anti-Slop Gate",
                "Always scrub AI cliches, passive openers, and repeated action verbs before preview or export.",
                "boolean",
                False,
                [],
            ),
        ]

        definitions.extend(
            [
                (
                    "target_locations",
                    "Target Locations",
                    "Preferred cities or Remote tags used to filter jobs during scraping and adapt resume headers.",
                    "tags",
                    False,
                    [],
                ),
                (
                    "work_types",
                    "Work Mode",
                    "Work arrangements to include when scraping job postings.",
                    "multi_select",
                    False,
                    [
                        ConfigOption(value="remote", label="Remote"),
                        ConfigOption(value="hybrid", label="Hybrid"),
                        ConfigOption(value="onsite", label="On-site"),
                    ],
                ),
                (
                    "job_types",
                    "Employment Type",
                    "Include full-time roles and/or contract engagements.",
                    "multi_select",
                    False,
                    [
                        ConfigOption(value="full-time", label="Full-time"),
                        ConfigOption(value="contract", label="Contract"),
                    ],
                ),
                (
                    "work_authorization",
                    "Work Authorization",
                    "Filter out postings that explicitly reject H-1B visa sponsorship or require US citizenship.",
                    "select",
                    False,
                    [
                        ConfigOption(value="h1b", label="H-1B Sponsorship Friendly"),
                        ConfigOption(value="any", label="Any / No Visa Filter"),
                        ConfigOption(value="us_citizen_gc_only", label="US Citizen / GC Required"),
                    ],
                ),
                (
                    "posted_within_default",
                    "Default Freshness Window",
                    "Default job posting age window used when starting a scrape session.",
                    "select",
                    False,
                    [
                        ConfigOption(value="1h", label="Less than 1 hour ago"),
                        ConfigOption(value="12h", label="Less than 12 hours ago"),
                        ConfigOption(value="24h", label="Less than 24 hours ago"),
                        ConfigOption(value="7d", label="Past 7 days"),
                        ConfigOption(value="any", label="Any time"),
                    ],
                ),
                (
                    "min_hourly_rate",
                    "Min Hourly Rate (USD/hr)",
                    "Minimum hourly contract rate in USD. Postings without listed compensation are kept.",
                    "number",
                    False,
                    [],
                ),
                (
                    "min_relevance_score",
                    "Min Relevance Score (0-100)",
                    "Minimum initial keyword match score required while scraping (0 keeps all role-matched jobs).",
                    "number",
                    False,
                    [],
                ),
                (
                    "scraper_sources",
                    "Job Sources",
                    "Top recruiting sources queried during batch scraping.",
                    "multi_select",
                    False,
                    [
                        ConfigOption(value="linkedin", label="LinkedIn Public Search"),
                        ConfigOption(value="greenhouse", label="Greenhouse Boards"),
                        ConfigOption(value="ashby", label="Ashby Boards"),
                        ConfigOption(value="lever", label="Lever Boards"),
                    ],
                ),
                (
                    "company_boards",
                    "Company Boards",
                    "ATS boards in provider:slug format (e.g., greenhouse:anthropic, ashby:openai, lever:palantir).",
                    "tags",
                    False,
                    [],
                ),
                (
                    "title_blocklist",
                    "Title Blocklist",
                    "Exclude postings whose title contains any of these terms (e.g., intern, junior, director).",
                    "tags",
                    False,
                    [],
                ),
                (
                    "resume_filename_format",
                    "Resume Filename Format",
                    "Export template supporting {full_name}, {company}, {role}, and {location}.",
                    "text",
                    False,
                    [],
                ),
            ]
        )

        fields: list[ConfigFieldSchema] = []
        for key, label, description, field_type, required, options in definitions:
            current_val = getattr(settings, key)
            is_missing = required and (current_val is None or current_val == [] or current_val == "")
            fields.append(
                ConfigFieldSchema(
                    key=key,
                    label=label,
                    description=description,
                    field_type=field_type,  # type: ignore[arg-type]
                    required=required,
                    options=options,
                    current_value=current_val,
                    is_missing=is_missing,
                )
            )
        return fields
