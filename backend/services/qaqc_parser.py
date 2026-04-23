"""QAQC CSV file parsers for Deficiency Items and QC Tests.

Parses RMS QAQC CSV exports:
- Deficiency Items -> Procore Observations
- QC Tests -> Procore Inspections
"""
import csv
import io
import logging
import re
from datetime import date, datetime
from typing import Optional

from models.rms import (
    RMSDeficiency,
    RMSDeficiencyParseResult,
    RMSTest,
    RMSTestParseResult,
)

logger = logging.getLogger(__name__)


def _decode(file_bytes: bytes) -> str:
    """Decode CSV bytes, handling BOM."""
    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1")


def _skip_header(text: str, expected_column_marker: str) -> tuple[str, Optional[str], Optional[date]]:
    """Skip metadata header lines and return CSV text from the column header onward.

    All RMS QC exports have 4 metadata lines followed by the column header row:
      Row 1: Report title + date (e.g., "Deficiency Items Issued - by  All,17 Apr 2026")
      Row 2: Project name (e.g., "W912QR24C0035  Dobbins AFB, GA ...")
      Row 3: Organization (e.g., "US Army Corps of Engineers")
      Row 4: Contract number (e.g., "H2003670")
      Row 5: Column headers

    Returns:
        Tuple of (csv_text_from_headers, project_name, report_date)
    """
    lines = text.split("\n")
    project_name = None
    report_date = None

    # Extract metadata from first few lines
    if len(lines) >= 2:
        # Row 1 has the report date at the end
        row1_parts = lines[0].split(",")
        if len(row1_parts) >= 2:
            report_date = _parse_date_dmy(row1_parts[1].strip().strip('"'))

        # Row 2 has the project name
        project_name = lines[1].split(",")[0].strip().strip('"')

    # Find the column header line
    for i, line in enumerate(lines):
        if line.startswith(expected_column_marker):
            return "\n".join(lines[i:]), project_name, report_date

    # Fallback: skip first 4 lines
    if len(lines) > 4:
        return "\n".join(lines[4:]), project_name, report_date
    return text, project_name, report_date


def _parse_date_dmy(date_str: str) -> Optional[date]:
    """Parse date in '17 Apr 2026' or 'DD Mon YYYY' format."""
    if not date_str:
        return None
    for fmt in ["%d %b %Y", "%d %B %Y", "%m/%d/%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


class DeficiencyParser:
    """Parse RMS Deficiency Items CSV.

    CSV format after 4 header rows:
        Item Number,Description,Location,Status,Date Issued,Age (days),Staff
        QA-00001,"description...",Building Pad,QA Concurs Corrected,15 Sep 2025,177,Salvador Sanchez
    """

    def parse(self, file_bytes: bytes) -> RMSDeficiencyParseResult:
        text = _decode(file_bytes)
        csv_text, project_name, report_date = _skip_header(text, "Item Number,")

        reader = csv.reader(io.StringIO(csv_text))
        header = next(reader, None)
        if not header:
            return RMSDeficiencyParseResult(
                deficiencies=[], total_count=0, open_count=0, closed_count=0,
                errors=["Empty CSV after header detection"],
            )

        deficiencies: list[RMSDeficiency] = []
        locations: set[str] = set()
        errors: list[str] = []
        warnings: list[str] = []

        for row_num, row in enumerate(reader, start=2):
            if not row or not row[0].strip():
                continue

            item_number = row[0].strip()
            # Accept both QA- and QC- prefixed items
            if not (item_number.startswith("QA-") or item_number.startswith("QC-")):
                continue

            try:
                description = row[1].strip() if len(row) > 1 else ""
                location = row[2].strip() if len(row) > 2 and row[2].strip() else None
                status = row[3].strip() if len(row) > 3 and row[3].strip() else "Open"
                date_issued = _parse_date_dmy(row[4].strip()) if len(row) > 4 else None
                age_days = None
                if len(row) > 5 and row[5].strip():
                    try:
                        age_days = int(row[5].strip())
                    except ValueError:
                        pass
                staff = row[6].strip() if len(row) > 6 and row[6].strip() else None

                deficiencies.append(RMSDeficiency(
                    item_number=item_number,
                    description=description,
                    location=location,
                    status=status,
                    date_issued=date_issued,
                    age_days=age_days,
                    staff=staff,
                ))

                if location:
                    locations.add(location)

            except Exception as e:
                errors.append(f"Row {row_num}: Failed to parse deficiency: {e}")

        open_count = sum(1 for d in deficiencies if d.is_open)

        return RMSDeficiencyParseResult(
            deficiencies=deficiencies,
            project_name=project_name,
            report_date=report_date,
            total_count=len(deficiencies),
            open_count=open_count,
            closed_count=len(deficiencies) - open_count,
            locations=sorted(locations),
            errors=errors,
            warnings=warnings,
        )


class TestParser:
    """Parse RMS QC Test List CSV.

    CSV format after 4 header rows:
        QC Test No.,Description,Performed By,Location,Status
        CT-00001,"Specification Section: 31 00 00...",NOVA,Building Pad,Completed
    """

    def parse(self, file_bytes: bytes) -> RMSTestParseResult:
        text = _decode(file_bytes)
        csv_text, project_name, report_date = _skip_header(text, "QC Test No.,")

        reader = csv.reader(io.StringIO(csv_text))
        header = next(reader, None)
        if not header:
            return RMSTestParseResult(
                tests=[], total_count=0, completed_count=0, outstanding_count=0,
                errors=["Empty CSV after header detection"],
            )

        tests: list[RMSTest] = []
        locations: set[str] = set()
        performers: set[str] = set()
        errors: list[str] = []
        warnings: list[str] = []

        for row_num, row in enumerate(reader, start=2):
            if not row or not row[0].strip():
                continue

            test_number = row[0].strip()
            if not test_number.startswith("CT-"):
                continue

            try:
                description = row[1].strip() if len(row) > 1 else ""
                performed_by = row[2].strip() if len(row) > 2 and row[2].strip() else None
                location = row[3].strip() if len(row) > 3 and row[3].strip() else None
                status = row[4].strip() if len(row) > 4 and row[4].strip() else "Outstanding"

                tests.append(RMSTest(
                    test_number=test_number,
                    description=description,
                    performed_by=performed_by,
                    location=location,
                    status=status,
                ))

                if location:
                    locations.add(location)
                if performed_by:
                    performers.add(performed_by)

            except Exception as e:
                errors.append(f"Row {row_num}: Failed to parse test: {e}")

        completed_count = sum(1 for t in tests if t.is_complete)

        return RMSTestParseResult(
            tests=tests,
            project_name=project_name,
            report_date=report_date,
            total_count=len(tests),
            completed_count=completed_count,
            outstanding_count=len(tests) - completed_count,
            locations=sorted(locations),
            performers=sorted(performers),
            errors=errors,
            warnings=warnings,
        )


# Backwards-compatible alias
QAQCParser = DeficiencyParser
