"""RMS file parser service."""
import io
import re
from typing import Optional

import openpyxl

from models.rms import (
    RMSSubmittal,
    TransmittalReportEntry,
    RMSParseResult,
)


class RMSParser:
    """Parser for RMS export files."""

    def parse_all(
        self,
        register_report_bytes: bytes,
        transmittal_report_bytes: Optional[bytes] = None,
    ) -> RMSParseResult:
        """Parse RMS export files.

        register_report_bytes is required (Submittal Register CSV).
        transmittal_report_bytes is optional (adds revisions, dates, QA codes).
        """
        errors = []
        warnings = []

        submittals, report_errors = self._parse_register_report(register_report_bytes)
        errors.extend(report_errors)

        # Parse transmittal report (optional — adds revisions, dates, QA codes)
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
            transmittal_report=transmittal_report,
            submittal_count=len(submittals),
            spec_section_count=len(spec_sections),
            revision_count=revision_count,
            errors=errors,
            warnings=warnings,
        )

    def _parse_register_report(
        self, file_bytes: bytes
    ) -> tuple[list[RMSSubmittal], list[str]]:
        """Parse Submittal Register CSV.

        Hierarchical format with section headers and data rows:
        - Section header: "Section 03 30 00" or "Section 03 30 00 CAST-IN-PLACE CONCRETE"
        - Data rows: 16 CSV columns (activity, transmittal, item, paragraph, desc, type, class, ...)
        """
        import csv
        from models.mappings import TYPE_TEXT_TO_SD

        errors = []
        submittals = []

        try:
            text = file_bytes.decode("utf-8-sig", errors="replace")

            section_re = re.compile(r"^Section\s+([\d\s\.]+)")
            current_section = None

            reader = csv.reader(text.splitlines())
            for row_num, row in enumerate(reader, 1):
                if not row:
                    continue

                col1 = row[0].strip()

                # Skip header rows (first 3 lines)
                if row_num <= 3:
                    continue

                # Section header
                section_match = section_re.match(col1)
                if section_match:
                    current_section = section_match.group(1).strip()
                    continue

                # Data row — item_no is in column 3 (index 2)
                if current_section and len(row) >= 7:
                    item_str = row[2].strip() if len(row) > 2 else ""
                    if not item_str or not item_str.isdigit():
                        continue

                    item_no = int(item_str)
                    paragraph = row[3].strip() if len(row) > 3 else None
                    description = row[4].strip() if len(row) > 4 else ""
                    type_text = row[5].strip() if len(row) > 5 else ""
                    classification = row[6].strip() if len(row) > 6 else None

                    # Map type text to SD number
                    sd_no = TYPE_TEXT_TO_SD.get(type_text)

                    # Government action (QA code + dates)
                    qc_code = row[12].strip() if len(row) > 12 and row[12].strip() else None
                    qa_code = row[14].strip() if len(row) > 14 and row[14].strip() else None

                    # Classification (Info field: GA, FIO, S)
                    info = classification if classification and classification not in ("", "nan") else None

                    try:
                        submittal = RMSSubmittal(
                            section=current_section,
                            item_no=item_no,
                            sd_no=sd_no,
                            description=description,
                            qc_code=qc_code,
                            qa_code=qa_code,
                            paragraph=paragraph if paragraph else None,
                            info=info,
                        )
                        submittals.append(submittal)

                    except Exception as e:
                        errors.append(f"Submittal Register row {row_num}: {str(e)}")

        except Exception as e:
            errors.append(f"Failed to parse Submittal Register: {str(e)}")

        return submittals, errors

    def _parse_transmittal_report(
        self, file_bytes: bytes
    ) -> tuple[list[TransmittalReportEntry], list[str]]:
        """
        Parse Transmittal Log (CSV or Excel, hierarchical format).

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
        """Parse Transmittal Log from CSV format."""
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
        """Parse Transmittal Log from Excel format."""
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
            errors.append(f"Failed to parse Transmittal Log: {str(e)}")

        return entries, errors

