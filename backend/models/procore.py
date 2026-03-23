"""Procore data models."""
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class ProcoreCompany(BaseModel):
    """Procore company."""

    id: int
    name: str
    is_active: bool = True


class ProcoreProject(BaseModel):
    """Procore project."""

    id: int
    name: str
    company_id: int
    active: bool = True


class ProcoreSpecSection(BaseModel):
    """Procore specification section."""

    id: int
    number: str
    description: Optional[str] = None

    @property
    def normalized_number(self) -> str:
        """Normalize section number for matching (remove extra spaces, lowercase)."""
        return " ".join(self.number.lower().split())


class ProcoreSubmittal(BaseModel):
    """Procore submittal."""

    id: int
    number: str  # Item number
    title: str
    revision: int = 0
    status: Optional[str] = None
    specification_section: Optional[ProcoreSpecSection] = None

    # Custom fields (if populated)
    custom_fields: dict[str, Any] = {}

    @property
    def match_key(self) -> str:
        """Generate match key for this submittal."""
        section = self.specification_section.number if self.specification_section else "UNKNOWN"
        return f"{section}-{self.number}-{self.revision}"


class ProcoreStats(BaseModel):
    """Statistics about a Procore project's submittals."""

    submittal_count: int
    spec_section_count: int
    revision_count: int
    spec_sections: list[str] = []


class ProcoreVendor(BaseModel):
    """Procore Directory vendor."""

    id: int
    name: str
    company: Optional[str] = None  # Parent company name
    business_phone: Optional[str] = None
    email_address: Optional[str] = None
    is_active: bool = True


class VendorMatch(BaseModel):
    """Result of matching a contractor name to a Procore vendor."""

    input_name: str
    vendor_id: Optional[int] = None
    vendor_name: Optional[str] = None
    match_score: int = 0
    exact_match: bool = False
    suggestions: list["VendorSuggestion"] = []


class VendorSuggestion(BaseModel):
    """A suggested vendor match with score."""

    vendor_id: int
    vendor_name: str
    score: int
    exact: bool = False


# Allow forward reference resolution
VendorMatch.model_rebuild()


class ProcoreObservation(BaseModel):
    """Procore Observation (deficiency/punch item)."""

    id: int
    number: Optional[int] = None
    name: str  # Title/description
    description: Optional[str] = None
    status: str  # "open", "ready_for_review", "not_accepted", "closed"
    priority: Optional[str] = None  # "low", "medium", "high"
    due_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    location: Optional[dict] = None  # Location object with id/name
    assignee: Optional[dict] = None  # Assignee user/vendor
    observation_type: Optional[dict] = None  # Type object with id/name


class ProcoreObservationType(BaseModel):
    """Procore Observation Type (category)."""

    id: int
    name: str
    category: Optional[str] = None  # "deficiency", "safety", etc.


class ProcoreLocation(BaseModel):
    """Procore Location for observations."""

    id: int
    name: str
    parent_id: Optional[int] = None
