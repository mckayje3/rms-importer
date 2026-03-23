"""Models for submittal matching and import modes."""
from pydantic import BaseModel
from typing import Optional, Any
from enum import Enum


class ImportMode(str, Enum):
    """Import mode selection."""

    FULL_MIGRATION = "full_migration"  # Procore is empty, import everything
    SYNC_FROM_RMS = "sync_from_rms"  # RMS is source of truth, update Procore
    RECONCILE = "reconcile"  # Merge both, user resolves conflicts


class MatchStatus(str, Enum):
    """Match status for a submittal."""

    MATCHED = "matched"  # Exists in both RMS and Procore
    RMS_ONLY = "rms_only"  # Only in RMS (will be created)
    PROCORE_ONLY = "procore_only"  # Only in Procore (orphan)


class FieldConflict(BaseModel):
    """A conflict between RMS and Procore values for a field."""

    field_name: str
    rms_value: Optional[Any]
    procore_value: Optional[Any]
    resolved_value: Optional[Any] = None  # User's choice
    use_rms: Optional[bool] = None  # True = use RMS, False = use Procore


class MatchResult(BaseModel):
    """Result of matching a submittal across systems."""

    match_key: str  # e.g., "01 50 00-15-0"
    status: MatchStatus

    # IDs
    rms_index: Optional[int] = None  # Index in RMS submittal list
    procore_id: Optional[int] = None  # Procore submittal ID

    # Data
    section: str
    item_no: int
    revision: int
    title: Optional[str] = None

    # Conflicts (for reconcile mode)
    conflicts: list[FieldConflict] = []
    has_conflicts: bool = False


class MatchingSummary(BaseModel):
    """Summary of matching results."""

    total_rms: int
    total_procore: int
    matched_count: int
    rms_only_count: int
    procore_only_count: int
    conflict_count: int

    # Match rate for auto-detection
    match_rate: float  # matched_count / total_procore (if procore > 0)

    # Recommendation
    recommended_mode: ImportMode
    recommendation_reason: str


class ConflictResolution(BaseModel):
    """User's resolution for conflicts."""

    match_key: str
    resolutions: list[FieldConflict]


class BulkResolution(BaseModel):
    """Bulk conflict resolution choice."""

    field_name: str  # e.g., "status", "all"
    use_rms: bool  # True = use RMS values, False = use Procore
