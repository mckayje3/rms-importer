"""RMS Excel file parser service."""
import io
import re
from datetime import datetime
from typing import Optional

import pandas as pd

import openpyxl

from models.rms import (
    RMSSubmittal,
    RMSAssignment,
    TransmittalLogEntry,
    TransmittalReportEntry,
    RMSParseResult,
)


class RMSParser:
    """Parser for RMS export Excel files."""

    # Expected column headers (case-insensitive matching)
    REGISTER_COLUMNS = [
        "section",
        "item no",
        "sd no",
        "description",
        "date in",
        "qc code",
        "date out",
        "qa code",
        "status",
    ]

    ASSIGNMENTS_COLUMNS = [
        "section",
        "item no",
        "description",
        "sd no",
        "info only",
        "required for activity",
    ]

    TRANSMITTAL_COLUMNS = [
        "section",
        "transmittal number",
        "submittal items included on transmittal",
        "contractor prepared",
        "government received",
        "government returned",
        "contractor received",
    ]

    def parse_all(
        self,
        register_bytes: bytes,
        assignments_bytes: bytes,
        transmittal_bytes: bytes,
        transmittal_report_bytes: Optional[bytes] = None,
    ) -> RMSParseResult:
        """Parse all RMS export files."""
        errors = []
        warnings = []

        # Parse each file
        submittals, reg_errors = self._parse_register(register_bytes)
        errors.extend(reg_errors)

        assignments, assign_errors = self._parse_assignments(assignments_bytes)
        errors.extend(assign_errors)

        transmittal_entries, trans_errors = self._parse_transmittal_log(transmittal_bytes)
        errors.extend(trans_errors)

        # Parse transmittal report (QA codes)
        transmittal_report: list[TransmittalReportEntry] = []
        if transmittal_report_bytes:
            transmittal_report, report_errors = self._parse_transmittal_report(transmittal_report_bytes)
            errors.extend(report_errors)

        # Calculate stats
        spec_sections = set(s.section for s in submittals)
        revision_count = sum(1 for t in transmittal_entries if t.revision > 0)

        return RMSParseResult(
            submittals=submittals,
            assignments=assignments,
            transmittal_entries=transmittal_entries,
            transmittal_report=transmittal_report,
            submittal_count=len(submittals),
            spec_section_count=len(spec_sections),
            revision_count=revision_count,
            errors=errors,
            warnings=warnings,
        )

    def _parse_register(self, file_bytes: bytes) -> tuple[list[RMSSubmittal], list[str]]:
        """Parse Submittal Register Excel file."""
        errors = []
        submittals = []

        try:
            df = pd.read_excel(io.BytesIO(file_bytes))
            df.columns = [str(c).lower().strip() for c in df.columns]

            # Validate columns
            missing = self._check_columns(df.columns, self.REGISTER_COLUMNS[:4])  # First 4 required
            if missing:
                errors.append(f"Submittal Register missing columns: {missing}")
                return [], errors

            for idx, row in df.iterrows():
                try:
                    submittal = RMSSubmittal(
                        section=str(row.get("section", "")).strip(),
                        item_no=int(row.get("item no", 0)),
                        sd_no=self._safe_str(row.get("sd no")),
                        description=str(row.get("description", "")).strip(),
                        date_in=self._parse_date(row.get("date in")),
                        qc_code=self._safe_str(row.get("qc code")),
                        date_out=self._parse_date(row.get("date out")),
                        qa_code=self._safe_str(row.get("qa code")),
                        status=self._safe_str(row.get("status")),
                    )
                    if submittal.section:  # Skip empty rows
                        submittals.append(submittal)
                except Exception as e:
                    errors.append(f"Row {idx + 2}: {str(e)}")

        except Exception as e:
            errors.append(f"Failed to parse Submittal Register: {str(e)}")

        return submittals, errors

    def _parse_assignments(self, file_bytes: bytes) -> tuple[list[RMSAssignment], list[str]]:
        """Parse Submittal Assignments Excel file."""
        errors = []
        assignments = []

        try:
            df = pd.read_excel(io.BytesIO(file_bytes))
            df.columns = [str(c).lower().strip() for c in df.columns]

            # Validate columns
            missing = self._check_columns(df.columns, self.ASSIGNMENTS_COLUMNS[:3])
            if missing:
                errors.append(f"Submittal Assignments missing columns: {missing}")
                return [], errors

            for idx, row in df.iterrows():
                try:
                    assignment = RMSAssignment(
                        section=str(row.get("section", "")).strip(),
                        item_no=int(row.get("item no", 0)),
                        description=str(row.get("description", "")).strip(),
                        sd_no=self._safe_str(row.get("sd no")),
                        info_only=self._safe_str(row.get("info only")),
                        required_for_activity=self._safe_str(row.get("required for activity")),
                    )
                    if assignment.section:
                        assignments.append(assignment)
                except Exception as e:
                    errors.append(f"Assignments row {idx + 2}: {str(e)}")

        except Exception as e:
            errors.append(f"Failed to parse Submittal Assignments: {str(e)}")

        return assignments, errors

    def _parse_transmittal_log(
        self, file_bytes: bytes
    ) -> tuple[list[TransmittalLogEntry], list[str]]:
        """Parse Transmittal Log Excel file."""
        errors = []
        entries = []

        try:
            df = pd.read_excel(io.BytesIO(file_bytes))
            df.columns = [str(c).lower().strip() for c in df.columns]

            # Validate columns
            missing = self._check_columns(df.columns, self.TRANSMITTAL_COLUMNS[:3])
            if missing:
                errors.append(f"Transmittal Log missing columns: {missing}")
                return [], errors

            for idx, row in df.iterrows():
                try:
                    section = str(row.get("section", "")).strip()
                    transmittal_num = str(row.get("transmittal number", "")).strip()
                    items_str = str(row.get("submittal items included on transmittal", ""))

                    if not section or not items_str:
                        continue

                    # Parse revision from transmittal number (e.g., "01 50 00-4.2" -> 2)
                    revision = 0
                    rev_match = re.search(r"\.(\d+)$", transmittal_num)
                    if rev_match:
                        revision = int(rev_match.group(1))

                    # Parse item numbers (comma-separated)
                    item_numbers = []
                    for item in items_str.split(","):
                        item = item.strip()
                        if item.isdigit():
                            item_numbers.append(int(item))

                    if not item_numbers:
                        continue

                    entry = TransmittalLogEntry(
                        section=section,
                        transmittal_number=transmittal_num,
                        item_numbers=item_numbers,
                        revision=revision,
                        contractor_prepared=self._parse_date(row.get("contractor prepared")),
                        government_received=self._parse_date(row.get("government received")),
                        government_returned=self._parse_date(row.get("government returned")),
                        contractor_received=self._parse_date(row.get("contractor received")),
                    )
                    entries.append(entry)

                except Exception as e:
                    errors.append(f"Transmittal row {idx + 2}: {str(e)}")

        except Exception as e:
            errors.append(f"Failed to parse Transmittal Log: {str(e)}")

        return entries, errors

    def _parse_transmittal_report(
        self, file_bytes: bytes
    ) -> tuple[list[TransmittalReportEntry], list[str]]:
        """
        Parse Transmittal Report (CSV or Excel, hierarchical format).

        The report alternates between transmittal header rows and item data rows:
        - Header row: "Transmittal No 03 30 00-2.1  Date In: ..."
        - Item rows: item_no, description, ..., classification, qa_code
        """
        # Detect format: CSV or Excel
        try:
            text = file_bytes.decode("utf-8-sig", errors="replace")  # utf-8-sig strips BOM
            if text.lstrip().startswith("Transmittal Log") or "Transmittal No " in text[:2000]:
                return self._parse_transmittal_report_csv(text)
        except Exception:
            pass

        return self._parse_transmittal_report_xlsx(file_bytes)

    def _parse_transmittal_report_csv(
        self, text: str
    ) -> tuple[list[TransmittalReportEntry], list[str]]:
        """Parse Transmittal Report from CSV format."""
        import csv

        errors = []
        entries = []

        header_re = re.compile(
            r"^Transmittal No\s+(.+?)-(\d+)(?:\.(\d+))?\s"
        )

        current_section = None
        current_transmittal_no = None
        current_revision = 0

        reader = csv.reader(text.splitlines())
        for row in reader:
            if not row:
                continue

            col1 = row[0].strip()

            # Check for transmittal header row
            header_match = header_re.match(col1)
            if header_match:
                current_section = header_match.group(1).strip()
                current_transmittal_no = int(header_match.group(2))
                current_revision = int(header_match.group(3)) if header_match.group(3) else 0
                continue

            # Item data row (starts with a number)
            # CSV columns (from header row 5):
            # 0: Item No., 1: Description, 2: Type of Submittal,
            # 3: Office, 4: Reviewer, 5: Classification, 6: QA Code
            # Rows may have 6 columns (no QA code) or 7 (with QA code)
            if col1.isdigit() and current_section is not None:
                item_no = int(col1)
                qa_code = row[6].strip() if len(row) > 6 and row[6].strip() else None
                classification = row[5].strip() if len(row) > 5 and row[5].strip() else None

                entries.append(TransmittalReportEntry(
                    section=current_section,
                    transmittal_no=current_transmittal_no,
                    revision=current_revision,
                    item_no=item_no,
                    qa_code=qa_code,
                    classification=classification,
                ))

        return entries, errors

    def _parse_transmittal_report_xlsx(
        self, file_bytes: bytes
    ) -> tuple[list[TransmittalReportEntry], list[str]]:
        """Parse Transmittal Report from Excel format."""
        errors = []
        entries = []

        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            ws = wb.active

            header_re = re.compile(
                r"^Transmittal No\s+(.+?)-(\d+)(?:\.(\d+))?\s"
            )

            current_section = None
            current_transmittal_no = None
            current_revision = 0

            for row in ws.iter_rows(min_row=13, max_col=14, values_only=True):
                col1 = str(row[0]).strip() if row[0] else ""

                if not col1:
                    continue

                header_match = header_re.match(col1)
                if header_match:
                    current_section = header_match.group(1).strip()
                    current_transmittal_no = int(header_match.group(2))
                    current_revision = int(header_match.group(3)) if header_match.group(3) else 0
                    continue

                if col1.isdigit() and current_section is not None:
                    item_no = int(col1)
                    qa_code = str(row[13]).strip() if row[13] else None
                    classification = str(row[12]).strip() if row[12] else None

                    if qa_code == "None":
                        qa_code = None
                    if classification == "None":
                        classification = None

                    entries.append(TransmittalReportEntry(
                        section=current_section,
                        transmittal_no=current_transmittal_no,
                        revision=current_revision,
                        item_no=item_no,
                        qa_code=qa_code if qa_code else None,
                        classification=classification,
                    ))

            wb.close()

        except Exception as e:
            errors.append(f"Failed to parse Transmittal Report: {str(e)}")

        return entries, errors

    def _check_columns(self, actual: list[str], required: list[str]) -> list[str]:
        """Check if required columns exist. Returns missing columns."""
        actual_lower = [c.lower() for c in actual]
        missing = []
        for req in required:
            if req.lower() not in actual_lower:
                missing.append(req)
        return missing

    def _safe_str(self, value) -> Optional[str]:
        """Convert value to string, handling NaN/None."""
        if pd.isna(value) or value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def _parse_date(self, value) -> Optional[datetime]:
        """Parse a date value from Excel."""
        if pd.isna(value) or value is None:
            return None

        if isinstance(value, datetime):
            return value.date()

        try:
            # Try common formats
            s = str(value).strip()
            for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y"]:
                try:
                    return datetime.strptime(s, fmt).date()
                except ValueError:
                    continue
        except Exception:
            pass

        return None
