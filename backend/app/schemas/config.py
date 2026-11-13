"""Configuration, role track, and ATS ruleset schemas."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

LlmMode = Literal["off", "ollama_local", "ollama_docker"]
ExportFormat = Literal["pdf", "docx"]
WorkAuthMode = Literal["h1b", "any", "us_citizen_gc_only"]
PostedWithinOption = Literal["1h", "12h", "24h", "7d", "any"]
WorkTypeOption = Literal["remote", "hybrid", "onsite"]
JobTypeOption = Literal["full-time", "contract"]
ScraperSourceOption = Literal["greenhouse", "lever", "ashby", "linkedin"]


class AppSettings(BaseModel):
    """Runtime settings persisted in config/settings.yaml and synced with the UI."""

    target_role_tracks: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=lambda: ["ALL_US"])
    work_types: list[WorkTypeOption] = Field(default_factory=lambda: ["remote", "hybrid", "onsite"])
    job_types: list[JobTypeOption] = Field(default_factory=lambda: ["full-time"])
    work_authorization: WorkAuthMode = "h1b"
    posted_within_default: PostedWithinOption = "24h"
    llm_mode: Optional[LlmMode] = None
    llm_model: str = "mistral-nemo:latest"
    ollama_base_url: str = "http://localhost:11434"
    export_formats: list[ExportFormat] = Field(default_factory=lambda: ["pdf", "docx"])
    page_budget: int | float = Field(default=1.5, ge=1.0, le=4.0)
    default_bullets_per_role: int = Field(default=5, ge=2, le=12)
    avoided_ai_words: list[str] = Field(
        default_factory=lambda: [
            "slashed",
            "spearheaded",
            "leveraged",
            "utilized",
            "synergized",
            "revolutionized",
            "cutting-edge",
            "state-of-the-art",
            "best-in-class",
            "game-changing",
            "seamlessly",
            "delved",
            "tapestry",
            "holistic",
            "paradigm shift",
            "fostering",
            "orchestrated",
            "pioneered",
            "supercharged",
            "skyrocketed",
            "myriad",
        ]
    )
    custom_tailor_instructions: str = ""
    target_yoe_min: Optional[int] = Field(default=4, ge=0, le=20)
    target_yoe_max: Optional[int] = Field(default=8, ge=0, le=25)
    target_salary_min: Optional[int] = Field(default=None, ge=0)
    min_hourly_rate: Optional[int] = Field(default=None, ge=0)
    min_relevance_score: int = Field(default=0, ge=0, le=100)
    scraper_sources: list[ScraperSourceOption] = Field(
        default_factory=lambda: ["linkedin", "greenhouse", "ashby", "lever"]
    )
    company_boards: list[str] = Field(default_factory=list)
    title_blocklist: list[str] = Field(default_factory=list)
    resume_filename_format: str = "{full_name}_{company}_{role}"
    strict_humanizer_gate: bool = True
    output_dir: str = "output"

    @model_validator(mode="after")
    def validate_yoe_bounds(self) -> "AppSettings":
        if (
            self.target_yoe_min is not None
            and self.target_yoe_max is not None
            and self.target_yoe_max < self.target_yoe_min
        ):
            raise ValueError("target_yoe_max must be >= target_yoe_min")
        if not self.export_formats:
            raise ValueError("export_formats must contain at least one format")
        return self


class ConfigOption(BaseModel):
    """Selectable option for UI dropdowns and multi-select controls."""

    value: str | int | float | bool
    label: str
    description: str = ""


class ConfigFieldSchema(BaseModel):
    """Metadata describing a configuration field for schema-driven UI rendering."""

    key: str
    label: str
    description: str
    field_type: Literal["select", "multi_select", "number", "text", "boolean", "tags"]
    required: bool = False
    options: list[ConfigOption] = Field(default_factory=list)
    current_value: object = None
    is_missing: bool = False


class ConfigResponse(BaseModel):
    """Full configuration state, schema metadata, and missing-default flags."""

    values: AppSettings
    fields: list[ConfigFieldSchema]
    missing_defaults: list[str]
    needs_setup: bool
    last_modified_ns: int
    config_path: str


class ConfigUpdateRequest(BaseModel):
    """Partial or full settings patch submitted from the UI."""

    updates: dict[str, object] = Field(default_factory=dict)


class RoleTrackWeights(BaseModel):
    """Keyword tier multipliers used when scoring JD requirements."""

    core_must_have: float = 3.0
    important_systems: float = 2.0
    senior_leadership: float = 1.5
    bonus_nice_to_have: float = 1.0


class RoleTrackKeywords(BaseModel):
    """Categorized keywords for a target engineering track."""

    core_must_have: list[str] = Field(default_factory=list)
    important_systems: list[str] = Field(default_factory=list)
    senior_leadership: list[str] = Field(default_factory=list)
    bonus_nice_to_have: list[str] = Field(default_factory=list)


class RoleTrackConfig(BaseModel):
    """Role track definition loaded from config/role_tracks/*.yaml."""

    id: str
    display_name: str
    category: str = "engineering_specialty"
    typical_yoe_label: str = ""
    search_query: str = ""
    company_examples: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    target_yoe_range: list[int] = Field(default_factory=lambda: [4, 8])
    weights: RoleTrackWeights = Field(default_factory=RoleTrackWeights)
    keywords: RoleTrackKeywords = Field(default_factory=RoleTrackKeywords)


class RoleTrackUpdateRequest(BaseModel):
    """Partial update to customize a role track's keywords, aliases, levels, or weights."""

    display_name: Optional[str] = None
    category: Optional[str] = None
    typical_yoe_label: Optional[str] = None
    search_query: Optional[str] = None
    company_examples: Optional[list[str]] = None
    target_yoe_range: Optional[list[int]] = None
    aliases: Optional[list[str]] = None
    description: Optional[str] = None
    keywords: Optional[RoleTrackKeywords] = None
    weights: Optional[RoleTrackWeights] = None


class BigTechRulesConfig(BaseModel):
    """Big Tech Senior ATS & recruiter rubric loaded from config/rules/big_tech_rules.yaml."""

    version: str = "1.0"
    target_seniority: dict[str, object] = Field(default_factory=dict)
    ats_formatting: dict[str, object] = Field(default_factory=dict)
    bullet_quality: dict[str, object] = Field(default_factory=dict)
    humanizer_guardrails: dict[str, object] = Field(default_factory=dict)
    scoring_weights: dict[str, float] = Field(default_factory=dict)


class LlmStatusResponse(BaseModel):
    """Live connectivity and single-model inventory status for local Ollama."""

    reachable: bool
    base_url: str
    configured_model: str
    model_installed: bool
    recommended_model: Optional[str] = None
    available_models: list[str] = Field(default_factory=list)
    llm_mode: Optional[str] = None
    error: Optional[str] = None


class LlmTestRequest(BaseModel):
    """Optional overrides when running a live connectivity probe against Ollama."""

    model: Optional[str] = None
    base_url: Optional[str] = None


class LlmTestResponse(BaseModel):
    """Result of probing the configured single Ollama model."""

    ok: bool
    model: str
    latency_ms: int = 0
    sample_output: str = ""
    error: Optional[str] = None


class LlmBenchmarkRequest(BaseModel):
    """Request to benchmark and rank installed local Ollama models on structured tailoring JSON."""

    models: Optional[list[str]] = None
    base_url: Optional[str] = None


class LlmBenchmarkItem(BaseModel):
    """Benchmark metrics and ranking for one local Ollama model."""

    model: str
    ok: bool
    latency_ms: int = 0
    json_valid: bool = False
    schema_complete: bool = False
    score: float = 0.0
    rank: int = 0
    notes: str = ""
    error: Optional[str] = None


class LlmBenchmarkResponse(BaseModel):
    """Comparison table ranking local Ollama models by JSON reliability, completeness, and speed."""

    reachable: bool
    base_url: str
    recommended_model: Optional[str] = None
    items: list[LlmBenchmarkItem] = Field(default_factory=list)
