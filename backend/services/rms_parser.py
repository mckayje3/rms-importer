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

    def parse_all(
        self,
        register_bytes: bytes,
        assignments_bytes: Optional[bytes] = None,
        transmittal_report_bytes: Optional[bytes] = None,
    ) -> RMSParseResult:
        """Parse all RMS export files. Only register is required."""
        errors = []

        # Parse register (required)
        submittals, reg_errors = self._parse_register(register_bytes)
        errors.extend(reg_errors)

        # Parse assignments (optional)
        assignments: list[RMSAssignment] = []
        if assignments_bytes:
            assignments, assign_errors = self._parse_assignments(assignments_bytes)
            errors.extend(assign_errors)

        # Parse transmittal report (optional)
        transmittal_report: list[TransmittalReportEntry] = []
        if transmittal_report_bytes:
            transmittal_report, report_errors = self._parse_transmittal_report(transmittal_report_bytes)
            errors.extend(report_errors)

        # Calculate stats
        spec_sections = set(s.section for s in submittals)
        revision_count = len(set(
            (e.section, e.item_no, e.revision)
            for e in transmittal_report if e.revision > 0
        ))

        return RMSParseResult(
            submittals=submittals,
            assignments=assignments,
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
        from datetime import datetime

        errors = []
        entries = []

        header_re = re.compile(
            r"^Transmittal No\s+(.+?)-(\d+)(?:\.(\d+))?\s"
        )
        date_in_re = re.compile(r"Date In:\s*(\d{2}/\d{2}/\d{4})")
        date_out_re = re.compile(r"Date Out:\s*(\d{2}/\d{2}/\d{4})")

        current_section = None
        current_transmittal_no = None
        current_revision = 0
        current_date_in = None
        current_date_out = None

        def parse_date_str(s: str):
            try:
                return datetime.strptime(s, "%m/%d/%Y").date()
            except (ValueError, TypeError):
                return None

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

                # Extract dates from header line
                full_line = ",".join(row) if len(row) > 1 else col1
                date_in_match = date_in_re.search(full_line)
                date_out_match = date_out_re.search(full_line)
                current_date_in = parse_date_str(date_in_match.group(1)) if date_in_match else None
                current_date_out = parse_date_str(date_out_match.group(1)) if date_out_match else None
                continue

            # Item data row (starts with a number)
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
                    government_received=current_date_in,
                    government_returned=current_date_out,
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
            current_date_in = None
            current_date_out = None

            date_in_re = re.compile(r"Date In:\s*(\d{2}/\d{2}/\d{4})")
            date_out_re = re.compile(r"Date Out:\s*(\d{2}/\d{2}/\d{4})")

            def parse_date_str(s: str):
                from datetime import datetime
                try:
                    return datetime.strptime(s, "%m/%d/%Y").date()
                except (ValueError, TypeError):
                    return None

            for row in ws.iter_rows(min_row=13, max_col=14, values_only=True):
                col1 = str(row[0]).strip() if row[0] else ""

                if not col1:
                    continue

                header_match = header_re.match(col1)
                if header_match:
                    current_section = header_match.group(1).strip()
                    current_transmittal_no = int(header_match.group(2))
                    current_revision = int(header_match.group(3)) if header_match.group(3) else 0

                    # Extract dates from header cell
                    date_in_match = date_in_re.search(col1)
                    date_out_match = date_out_re.search(col1)
                    current_date_in = parse_date_str(date_in_match.group(1)) if date_in_match else None
                    current_date_out = parse_date_str(date_out_match.group(1)) if date_out_match else None
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
                        government_received=current_date_in,
                        government_returned=current_date_out,
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
