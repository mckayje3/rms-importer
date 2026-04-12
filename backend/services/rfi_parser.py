"""Parser for RMS RFI Report CSV files."""
import csv
import io
import re
import logging
from datetime import date, datetime
from typing import Optional

from models.rfi import RMSRFI, RFIParseResult

logger = logging.getLogger(__name__)

# Header row starts with "RFI No."
HEADER_MARKER = "RFI No."


class RFIParser:
    """Parse RMS RFI Report CSV export."""

    def parse(self, file_bytes: bytes) -> RFIParseResult:
        """Parse an RFI Report CSV file.

        The CSV has a multi-line header (title, contract info, column names)
        followed by data rows with embedded newlines in quoted fields.
        """
        errors: list[str] = []
        warnings: list[str] = []
        rfis: list[RMSRFI] = []

        # Decode the file
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")

        # Find the header row and skip everything before it
        lines = text.split("\n")
        header_line_idx = None
        for i, line in enumerate(lines):
            if line.startswith(HEADER_MARKER):
                header_line_idx = i
                break

        if header_line_idx is None:
            return RFIParseResult(
                rfis=[],
                total_count=0,
                answered_count=0,
                outstanding_count=0,
                errors=["Could not find header row starting with 'RFI No.' in CSV"],
            )

        # Rejoin from header onward and parse as CSV
        csv_text = "\n".join(lines[header_line_idx:])
        reader = csv.reader(io.StringIO(csv_text))

        # Read header row
        header = next(reader, None)
        if not header:
            return RFIParseResult(
                rfis=[], total_count=0, answered_count=0, outstanding_count=0,
                errors=["Empty CSV after header detection"],
            )

        # Parse data rows
        for row in reader:
            if not row or not row[0].strip():
                continue

            rfi_no = row[0].strip()
            if not re.match(r"RFI-\d+", rfi_no):
                continue

            try:
                rfi = self._parse_row(row)
                rfis.append(rfi)
            except Exception as e:
                errors.append(f"Failed to parse {rfi_no}: {str(e)}")

        answered = sum(1 for r in rfis if r.is_answered)

        return RFIParseResult(
            rfis=rfis,
            total_count=len(rfis),
            answered_count=answered,
            outstanding_count=len(rfis) - answered,
            errors=errors,
            warnings=warnings,
        )

    def _parse_row(self, row: list[str]) -> RMSRFI:
        """Parse a single CSV row into an RMSRFI."""
        rfi_no = row[0].strip()
        number = int(re.search(r"\d+", rfi_no).group())

        # Dates (columns 1-3)
        date_requested = self._parse_date(row[1].strip()) if len(row) > 1 else None
        date_received = self._parse_date(row[2].strip()) if len(row) > 2 else None
        date_answered = self._parse_date(row[3].strip()) if len(row) > 3 else None

        # Requester / Responder (column 4, multi-line: "Name\nAnswer Prepared by")
        requester_name = None
        responder_name = None
        if len(row) > 4 and row[4].strip():
            names = row[4].strip().split("\n")
            requester_name = names[0].strip() if len(names) > 0 else None
            responder_name = names[1].strip() if len(names) > 1 else None

        # Mod Required / Change No. (column 5, multi-line)
        mod_required = None
        change_no = None
        if len(row) > 5 and row[5].strip():
            mod_parts = row[5].strip().split("\n")
            mod_required = mod_parts[0].strip() if len(mod_parts) > 0 else None
            change_no = mod_parts[1].strip() if len(mod_parts) > 1 else None

        # Subject + Question + Response (column 6, the big multi-line field)
        subject = rfi_no
        question_body = ""
        response_body = None

        if len(row) > 6 and row[6].strip():
            full_text = row[6].strip()
            subject, question_body, response_body = self._parse_qa_text(full_text, rfi_no)

        is_answered = response_body is not None and len(response_body.strip()) > 0

        return RMSRFI(
            rfi_number=rfi_no,
            number=number,
            subject=subject,
            question_body=question_body,
            response_body=response_body,
            date_requested=date_requested,
            date_received=date_received,
            date_answered=date_answered,
            requester_name=requester_name,
            responder_name=responder_name,
            mod_required=mod_required,
            change_no=change_no,
            is_answered=is_answered,
        )

    def _parse_qa_text(self, text: str, rfi_no: str) -> tuple[str, str, Optional[str]]:
        """Extract subject, question body, and response from the combined text field.

        Format: "INFORMATION REQUESTED: Subject - Details...\\n\\nGOVERNMENT RESPONSE: ..."
        """
        question_body = ""
        response_body = None

        # Split on GOVERNMENT RESPONSE marker
        gov_pattern = re.compile(r"\n\s*GOVERNMENT RESPONSE:\s*", re.IGNORECASE)
        parts = gov_pattern.split(text, maxsplit=1)

        question_part = parts[0].strip()
        if len(parts) > 1:
            response_body = parts[1].strip()

        # Extract question text (strip the "INFORMATION REQUESTED:" prefix)
        info_pattern = re.compile(r"^INFORMATION REQUESTED:\s*", re.IGNORECASE)
        question_body = info_pattern.sub("", question_part).strip()

        # Extract subject: text before the first " - " delimiter, or first ~100 chars
        subject = question_body
        dash_match = re.search(r"\s+-\s+", question_body)
        if dash_match and dash_match.start() < 120:
            subject = question_body[: dash_match.start()].strip()
        elif len(subject) > 120:
            # Truncate at a word boundary
            subject = subject[:120].rsplit(" ", 1)[0] + "..."

        return subject, question_body, response_body

    def _parse_date(self, date_str: str) -> Optional[date]:
        """Parse a date string in MM/DD/YYYY format."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%m/%d/%Y").date()
        except ValueError:
            return None
