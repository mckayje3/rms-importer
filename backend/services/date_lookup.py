"""Date lookup service - maps Transmittal Log dates to submittals."""
from datetime import date
from typing import Optional
from dataclasses import dataclass

from models.rms import TransmittalReportEntry


@dataclass
class SubmittalDates:
    """Dates for a submittal from Transmittal Log."""
    government_received: Optional[date] = None  # Date In
    government_returned: Optional[date] = None  # Date Out


class DateLookup:
    """
    Builds a lookup table from Transmittal Log entries.

    Maps match keys to their date fields.
    Match key format: "{Section}|{ItemNo}|{Revision}"

    Example:
        Transmittal Log header:
            "Transmittal No 03 30 00-4.1  Date In: 12/01/2025  Date Out: 12/10/2025"
        Data row:
            15, Description, ..., GA, B

        Creates entry: "03 30 00|15|1" -> dates(received=Dec 1, returned=Dec 10)
    """

    def __init__(self, report_entries: list[TransmittalReportEntry]):
        """Build lookup from transmittal report entries."""
        self._lookup: dict[str, SubmittalDates] = {}

        for entry in report_entries:
            if entry.government_received or entry.government_returned:
                dates = SubmittalDates(
                    government_received=entry.government_received,
                    government_returned=entry.government_returned,
                )
                self._lookup[entry.match_key] = dates

    def get(self, key: str) -> Optional[SubmittalDates]:
        """Get dates by match key (section|item_no|revision)."""
        return self._lookup.get(key)

    @property
    def total_entries(self) -> int:
        """Total number of submittal date entries."""
        return len(self._lookup)
