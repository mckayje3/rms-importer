"""RMS data models."""
import re
from pydantic import BaseModel, computed_field
from typing import Optional
from datetime import date

from .mappings import map_status, map_sd_to_type


class RMSSubmittal(BaseModel):
    """Submittal from RMS Register Report."""

    section: str  # Spec section (e.g., "01 50 00")
    item_no: int  # Item number
    sd_no: Optional[str] = None  # SD number (01-11)
    description: str
    qc_code: Optional[str] = None  # A, B, C, D
    qa_code: Optional[str] = None  # A, B, C, D, E, F, G, X
    status: Optional[str] = None  # RMS status (Outstanding, Complete, In Review)
    paragraph: Optional[str] = None  # Spec paragraph reference (e.g., "1.14", "3.4.1")
    info: Optional[str] = None  # Classification (GA, FIO, S)

    @property
    def match_key(self) -> str:
        """Generate match key for this submittal (revision 0 = original)."""
        return f"{self.section}-{self.item_no}-0"

    @computed_field
    @property
    def procore_status(self) -> Optional[str]:
        """Map QA code to Procore status. Returns None if no QA code (leave unchanged)."""
        return map_status(self.qa_code)

    @computed_field
    @property
    def procore_type(self) -> Optional[str]:
        """Map SD No to Procore submittal type."""
        return map_sd_to_type(self.sd_no)


class TransmittalReportEntry(BaseModel):
    """Entry from Transmittal Report (QA codes, dates, and revision info)."""

    section: str  # Spec section (e.g., "01 01 00")
    transmittal_no: int  # Transmittal number within section
    revision: int  # 0 = original, 1+ = revision
    item_no: int  # Item number
    qa_code: Optional[str] = None  # A, B, C, D, E, F, G, X
    classification: Optional[str] = None  # GA, FIO, S
    government_received: Optional[date] = None  # Date In
    government_returned: Optional[date] = None  # Date Out

    @property
    def match_key(self) -> str:
        """Generate match key: section|item_no|revision."""
        return f"{self.section}|{self.item_no}|{self.revision}"


class RMSParseResult(BaseModel):
    """Result of parsing RMS export files."""

    submittals: list[RMSSubmittal]
    transmittal_report: list[TransmittalReportEntry] = []

    # Stats
    submittal_count: int
    spec_section_count: int
    revision_count: int

    # Validation
    errors: list[str] = []
    warnings: list[str] = []


class RMSDeficiency(BaseModel):
    """Deficiency item from RMS QAQC Deficiencies report."""

    item_number: str  # e.g., "QA-00001"
    description: str
    location: Optional[str] = None  # e.g., "Building Pad", "Foundation"
    status: str  # e.g., "QA Verification Required", "QA Concurs Corrected"
    date_issued: Optional[date] = None
    age_days: Optional[int] = None
    staff: Optional[str] = None  # Assigned staff member

    @property
    def is_open(self) -> bool:
        """Check if this deficiency is still open."""
        return "Corrected" not in self.status and "Closed" not in self.status

    @property
    def procore_status(self) -> str:
        """Map RMS status to Procore observation status.

        Procore statuses: initiated, ready_for_review, not_accepted, closed
        """
        status_lower = self.status.lower()
        if "corrected" in status_lower or "closed" in status_lower:
            return "closed"
        if "verification" in status_lower:
            return "ready_for_review"
        return "initiated"


class RMSDeficiencyParseResult(BaseModel):
    """Result of parsing RMS QAQC Deficiencies report."""

    deficiencies: list[RMSDeficiency]
    project_name: Optional[str] = None
    report_date: Optional[date] = None

    # Stats
    total_count: int
    open_count: int
    closed_count: int
    locations: list[str] = []

    # Validation
    errors: list[str] = []
    warnings: list[str] = []


class RMSTest(BaseModel):
    """QC Test item from RMS QC Test List report."""

    test_number: str  # e.g., "CT-00001"
    description: str
    performed_by: Optional[str] = None  # e.g., "NOVA", "DC Mechanical"
    location: Optional[str] = None  # e.g., "Building Pad", "Footings"
    status: str  # "Completed" or "Outstanding"

    @property
    def is_complete(self) -> bool:
        """Check if this test is completed."""
        return self.status.lower() == "completed"

    @property
    def spec_section(self) -> Optional[str]:
        """Extract spec section from description if present."""
        match = re.search(r"Specification Section:\s*([\d\s]+)", self.description)
        if match:
            return match.group(1).strip()
        return None

    @property
    def paragraph(self) -> Optional[str]:
        """Extract paragraph reference from description if present."""
        match = re.search(r"Paragraph:\s*([\w\d\s.\-]+?)(?:\s+[A-Z]|$)", self.description)
        if match:
            return match.group(1).strip()
        return None


class RMSTestParseResult(BaseModel):
    """Result of parsing RMS QC Test List report."""

    tests: list[RMSTest]
    project_name: Optional[str] = None
    report_date: Optional[date] = None

    # Stats
    total_count: int
    completed_count: int
    outstanding_count: int
    locations: list[str] = []
    performers: list[str] = []

    # Validation
    errors: list[str] = []
    warnings: list[str] = []
