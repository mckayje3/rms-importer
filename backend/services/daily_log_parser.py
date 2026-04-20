"""Parsers for RMS QC Daily Log CSV exports."""
import csv
import io
import re
import logging
from datetime import date, datetime
from typing import Optional

from models.daily_log import (
    RMSEquipmentEntry,
    RMSLaborEntry,
    RMSNarrativeEntry,
    DailyLogParseResult,
)

logger = logging.getLogger(__name__)


def _decode(file_bytes: bytes) -> str:
    """Decode CSV bytes, handling BOM."""
    try:
        return file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1")


def _parse_date_mdy(date_str: str) -> Optional[date]:
    """Parse M/D/YYYY date format."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
    except ValueError:
        try:
            return datetime.strptime(date_str.strip(), "%m/%d/%y").date()
        except ValueError:
            return None


def _skip_header(text: str, expected_column_marker: str) -> str:
    """Skip metadata header lines and return CSV text from the column header onward.

    All RMS QC exports have 4 metadata lines followed by the column header row.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(expected_column_marker):
            return "\n".join(lines[i:])
    # Fallback: skip first 4 lines
    if len(lines) > 4:
        return "\n".join(lines[4:])
    return text


class EquipmentLogParser:
    """Parse RMS QC Equipment Hours CSV."""

    def parse(self, file_bytes: bytes) -> tuple[list[RMSEquipmentEntry], list[str]]:
        text = _decode(file_bytes)
        csv_text = _skip_header(text, "Item,")
        reader = csv.reader(io.StringIO(csv_text))

        # Read column header
        header = next(reader, None)
        if not header:
            return [], ["Empty CSV after header detection"]

        entries: list[RMSEquipmentEntry] = []
        errors: list[str] = []
        current_date: Optional[date] = None

        for row in reader:
            if not row or not row[0].strip():
                continue

            first = row[0].strip()

            # Report Date separator
            match = re.match(r"Report Date\s+(\d+/\d+/\d+)", first)
            if match:
                current_date = _parse_date_mdy(match.group(1))
                continue

            # Total row — skip
            if first.lower() == "total":
                continue

            if not current_date:
                continue

            try:
                entries.append(RMSEquipmentEntry(
                    date=current_date,
                    item=first,
                    serial_number=row[1].strip() if len(row) > 1 else "",
                    description=row[2].strip() if len(row) > 2 else "",
                    idle_hours=float(row[3]) if len(row) > 3 and row[3].strip() else 0,
                    operating_hours=float(row[4]) if len(row) > 4 and row[4].strip() else 0,
                ))
            except Exception as e:
                errors.append(f"Equipment row '{first}': {e}")

        return entries, errors


class LaborLogParser:
    """Parse RMS QC Labor Hours CSV."""

    def parse(self, file_bytes: bytes) -> tuple[list[RMSLaborEntry], list[str]]:
        text = _decode(file_bytes)
        csv_text = _skip_header(text, "Employer,")
        reader = csv.reader(io.StringIO(csv_text))

        header = next(reader, None)
        if not header:
            return [], ["Empty CSV after header detection"]

        entries: list[RMSLaborEntry] = []
        errors: list[str] = []
        current_date: Optional[date] = None

        for row in reader:
            if not row or not row[0].strip():
                continue

            first = row[0].strip()

            # Report Date separator
            match = re.match(r"Report Date\s+(\d+/\d+/\d+)", first)
            if match:
                current_date = _parse_date_mdy(match.group(1))
                continue

            # Total row — skip
            if first.lower() == "total":
                continue

            if not current_date:
                continue

            try:
                entries.append(RMSLaborEntry(
                    date=current_date,
                    employer=first,
                    labor_classification=row[1].strip() if len(row) > 1 else "",
                    num_employees=int(float(row[2])) if len(row) > 2 and row[2].strip() else 0,
                    hours=float(row[3]) if len(row) > 3 and row[3].strip() else 0,
                ))
            except Exception as e:
                errors.append(f"Labor row '{first}': {e}")

        return entries, errors


class NarrativeLogParser:
    """Parse RMS QC Narratives CSV."""

    def parse(self, file_bytes: bytes) -> tuple[list[RMSNarrativeEntry], list[str]]:
        text = _decode(file_bytes)
        csv_text = _skip_header(text, "ID,")
        reader = csv.reader(io.StringIO(csv_text))

        header = next(reader, None)
        if not header:
            return [], ["Empty CSV after header detection"]

        entries: list[RMSNarrativeEntry] = []
        errors: list[str] = []
        current_category: str = "General"

        for row in reader:
            if not row or not row[0].strip():
                continue

            first = row[0].strip()

            # Data row: starts with QC-XXXXX
            if re.match(r"QC-\d+", first):
                try:
                    dated = _parse_date_mdy(row[1].strip()) if len(row) > 1 else None
                    if not dated:
                        errors.append(f"Narrative {first}: invalid date '{row[1] if len(row) > 1 else ''}'")
                        continue

                    narrative_text = row[2].strip() if len(row) > 2 else ""
                    unresolved = row[3].strip().lower() if len(row) > 3 else "no"

                    entries.append(RMSNarrativeEntry(
                        narrative_id=first,
                        dated=dated,
                        narrative_type=current_category,
                        narrative_text=narrative_text,
                        unresolved_issue=unresolved == "yes",
                    ))
                except Exception as e:
                    errors.append(f"Narrative {first}: {e}")
                continue

            # Category header: non-QC row with no data in other columns
            if len(row) <= 1 or all(not c.strip() for c in row[1:]):
                current_category = first
                continue

        return entries, errors


class DailyLogParser:
    """Unified parser that delegates to individual log parsers."""

    def parse(
        self,
        equipment_bytes: Optional[bytes] = None,
        labor_bytes: Optional[bytes] = None,
        narrative_bytes: Optional[bytes] = None,
    ) -> DailyLogParseResult:
        equipment: list[RMSEquipmentEntry] = []
        labor: list[RMSLaborEntry] = []
        narratives: list[RMSNarrativeEntry] = []
        errors: list[str] = []
        warnings: list[str] = []
        all_dates: set[date] = set()

        if equipment_bytes:
            entries, errs = EquipmentLogParser().parse(equipment_bytes)
            equipment = entries
            errors.extend(errs)
            all_dates.update(e.date for e in entries)
            logger.info(f"Parsed {len(entries)} equipment entries")

        if labor_bytes:
            entries, errs = LaborLogParser().parse(labor_bytes)
            labor = entries
            errors.extend(errs)
            all_dates.update(e.date for e in entries)
            logger.info(f"Parsed {len(entries)} labor entries")

        if narrative_bytes:
            entries, errs = NarrativeLogParser().parse(narrative_bytes)
            narratives = entries
            errors.extend(errs)
            all_dates.update(e.dated for e in entries)
            logger.info(f"Parsed {len(entries)} narrative entries")

        if not equipment and not labor and not narratives:
            errors.append("No data found in any uploaded file")

        return DailyLogParseResult(
            equipment=equipment,
            labor=labor,
            narratives=narratives,
            equipment_count=len(equipment),
            labor_count=len(labor),
            narrative_count=len(narratives),
            dates_found=sorted(all_dates),
            errors=errors,
            warnings=warnings,
        )
