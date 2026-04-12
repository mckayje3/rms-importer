"""Models for sync operations."""
from pydantic import BaseModel, computed_field
from typing import Optional, Any
from enum import Enum
from datetime import datetime


class SyncMode(str, Enum):
    """Sync operation mode."""
    FULL_MIGRATION = "full_migration"  # No baseline, create all
    INCREMENTAL = "incremental"  # Has baseline, sync changes only


class FieldChange(BaseModel):
    """A single field that changed between baseline and new data."""
    field: str
    old_value: Any
    new_value: Any


class CreateAction(BaseModel):
    """Action to create a new submittal in Procore."""
    key: str  # section|item_no|revision
    section: str
    item_no: int
    revision: int
    title: str
    type: Optional[str] = None
    paragraph: Optional[str] = None
    info: Optional[str] = None
    qa_code: Optional[str] = None
    qc_code: Optional[str] = None
    status: Optional[str] = None  # Procore status name (e.g., "Closed", "Open")
    government_received: Optional[str] = None
    government_returned: Optional[str] = None


class UpdateAction(BaseModel):
    """Action to update an existing submittal in Procore."""
    key: str
    procore_id: int
    changes: list[FieldChange]


class FlagAction(BaseModel):
    """Action to flag an item for review (deleted from RMS)."""
    key: str
    procore_id: int
    reason: str = "Removed from RMS export"


class FileUploadAction(BaseModel):
    """Action to upload a file."""
    filename: str
    submittal_keys: list[str]  # May upload to multiple submittals


class SyncPlan(BaseModel):
    """Complete plan for what will be synced."""
    mode: SyncMode
    creates: list[CreateAction] = []
    updates: list[UpdateAction] = []
    flags: list[FlagAction] = []  # Items to flag for review (not auto-delete)
    file_uploads: list[FileUploadAction] = []
    files_already_uploaded: int = 0

    @computed_field
    @property
    def has_changes(self) -> bool:
        return bool(self.creates or self.updates or self.file_uploads)

    @computed_field
    @property
    def summary(self) -> str:
        parts = []
        if self.creates:
            parts.append(f"{len(self.creates)} new submittals")
        if self.updates:
            # Count unique change types
            qa_changes = sum(
                1 for u in self.updates
                if any(c.field == "qa_code" for c in u.changes)
            )
            date_changes = sum(
                1 for u in self.updates
                if any(c.field in ["government_received", "government_returned"]
                       for c in u.changes)
            )
            other_changes = len(self.updates) - max(qa_changes, date_changes)

            if qa_changes:
                parts.append(f"{qa_changes} QA code updates")
            if date_changes:
                parts.append(f"{date_changes} date updates")
            if other_changes > 0:
                parts.append(f"{other_changes} other updates")

        if self.file_uploads:
            parts.append(f"{len(self.file_uploads)} files to upload")
        if self.flags:
            parts.append(f"{len(self.flags)} items removed (flagged for review)")

        return ", ".join(parts) or "No changes detected"


class BaselineInfo(BaseModel):
    """Information about stored baseline."""
    has_baseline: bool
    last_sync: Optional[datetime] = None
    submittal_count: int = 0
    file_count: int = 0


class SyncAnalysisResponse(BaseModel):
    """Response from sync analysis endpoint."""
    baseline: BaselineInfo
    plan: SyncPlan
    summary: str


class SyncExecuteRequest(BaseModel):
    """Request to execute a sync plan."""
    session_id: str
    apply_creates: bool = True
    apply_updates: bool = True
    apply_date_updates: bool = True
    repair_custom_fields: bool = False  # Re-send all custom field values even if baseline matches


class SyncExecuteResponse(BaseModel):
    """Response from sync execution."""
    status: str  # "completed", "partial", "rate_limited", "failed", "background"
    created: int = 0
    updated: int = 0
    files_uploaded: int = 0
    flagged: int = 0
    errors: list[str] = []
    rate_limited: bool = False
    rate_limit_message: Optional[str] = None
    baseline_updated: bool = False
    update_job_id: Optional[str] = None  # Set when updates run in background


class StoredSubmittal(BaseModel):
    """Submittal data stored in baseline."""
    section: str
    item_no: int
    revision: int
    title: str
    type: Optional[str] = None
    paragraph: Optional[str] = None
    qa_code: Optional[str] = None
    qc_code: Optional[str] = None
    info: Optional[str] = None
    status: Optional[str] = None
    government_received: Optional[str] = None
    government_returned: Optional[str] = None
    procore_id: Optional[int] = None

    @property
    def key(self) -> str:
        return f"{self.section}|{self.item_no}|{self.revision}"


class StoredFile(BaseModel):
    """File data stored in baseline."""
    filename: str
    submittal_key: str = ""
    uploaded: bool = False
    procore_file_id: Optional[int] = None


class BaselineData(BaseModel):
    """Full baseline data structure."""
    submittals: dict[str, StoredSubmittal] = {}
    files: dict[str, StoredFile] = {}
