"""RFI data models."""
from pydantic import BaseModel
from typing import Optional
from datetime import date


class RMSRFI(BaseModel):
    """Parsed RFI from RMS export."""

    rfi_number: str  # e.g., "RFI-0001"
    number: int  # e.g., 1 (numeric part)
    subject: str  # Short subject line
    question_body: str  # Full question text
    response_body: Optional[str] = None  # Government response (if answered)
    date_requested: Optional[date] = None
    date_received: Optional[date] = None
    date_answered: Optional[date] = None
    requester_name: Optional[str] = None
    responder_name: Optional[str] = None
    mod_required: Optional[str] = None
    change_no: Optional[str] = None
    is_answered: bool = False


class RFIParseResult(BaseModel):
    """Result of parsing an RFI report file."""

    rfis: list[RMSRFI]
    total_count: int
    answered_count: int
    outstanding_count: int
    errors: list[str] = []
    warnings: list[str] = []


class RFICreateAction(BaseModel):
    """An RFI to create in Procore."""

    rfi_number: str
    number: int
    subject: str
    question_body: str
    response_body: Optional[str] = None
    date_requested: Optional[date] = None
    date_received: Optional[date] = None
    date_answered: Optional[date] = None
    is_answered: bool = False


class RFISyncPlan(BaseModel):
    """Plan for syncing RFIs to Procore."""

    creates: list[RFICreateAction]
    already_exist: int = 0
    total_rms: int
    has_changes: bool = False
    summary: str = ""
