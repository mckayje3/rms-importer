"""Daily log data models."""
from pydantic import BaseModel
from typing import Optional
from datetime import date


class RMSEquipmentEntry(BaseModel):
    """Parsed equipment entry from RMS QC Equipment CSV."""

    date: date
    item: str  # e.g., "00000019"
    serial_number: str  # e.g., "303E"
    description: str  # e.g., "CAT 303E Mini Exc"
    idle_hours: float
    operating_hours: float


class RMSLaborEntry(BaseModel):
    """Parsed labor entry from RMS QC Labor CSV."""

    date: date
    employer: str  # e.g., "Global Go, LLC"
    labor_classification: str  # e.g., "CONTRACTOR, GENERAL BLDG"
    num_employees: int
    hours: float


class RMSNarrativeEntry(BaseModel):
    """Parsed narrative entry from RMS QC Narratives CSV."""

    narrative_id: str  # e.g., "QC-00074"
    dated: date
    narrative_type: str  # e.g., "Civil QC Comments"
    narrative_text: str
    unresolved_issue: bool = False


class DailyLogParseResult(BaseModel):
    """Result of parsing daily log CSV files."""

    equipment: list[RMSEquipmentEntry] = []
    labor: list[RMSLaborEntry] = []
    narratives: list[RMSNarrativeEntry] = []
    equipment_count: int = 0
    labor_count: int = 0
    narrative_count: int = 0
    dates_found: list[date] = []
    errors: list[str] = []
    warnings: list[str] = []


class DailyLogCreateAction(BaseModel):
    """An entry to create in Procore."""

    log_type: str  # "equipment", "labor", "narrative"
    date: date
    data: dict  # Procore API payload


class DailyLogSyncPlan(BaseModel):
    """Plan for syncing daily logs to Procore."""

    equipment_creates: int = 0
    labor_creates: int = 0
    narrative_creates: int = 0
    already_exist: int = 0
    total_creates: int = 0
    has_changes: bool = False
    summary: str = ""
    unmatched_vendors: list[str] = []
