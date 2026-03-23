"""Date lookup service - maps Transmittal Log dates to submittals."""
from datetime import date
from typing import Optional
from dataclasses import dataclass

from models.rms import TransmittalLogEntry


@dataclass
class SubmittalDates:
    """Dates for a submittal from Transmittal Log."""
    contractor_prepared: Optional[date] = None
    government_received: Optional[date] = None
    government_returned: Optional[date] = None
    contractor_received: Optional[date] = None


class DateLookup:
    """
    Builds a lookup table from Transmittal Log entries.

    Maps match keys to their 4 date fields.
    Match key format: "{Section}-{ItemNo}-{Revision}"

    Example:
        Transmittal Log row:
            Section: "03 30 00"
            Transmittal Number: "03 30 00-4.1"  (revision = 1)
            Items: "15,11,12"
            Dates: Dec 1, Dec 5, Dec 10, Dec 15

        Creates entries for:
            "03 30 00-15-1" -> dates
            "03 30 00-11-1" -> dates
            "03 30 00-12-1" -> dates
    """

    def __init__(self, transmittal_entries: list[TransmittalLogEntry]):
        """Build lookup from transmittal entries."""
        self._lookup: dict[str, SubmittalDates] = {}

        for entry in transmittal_entries:
            dates = SubmittalDates(
                contractor_prepared=entry.contractor_prepared,
                government_received=entry.government_received,
                government_returned=entry.government_returned,
                contractor_received=entry.contractor_received,
            )

            # Each entry can have multiple items - all get the same dates
            for match_key in entry.match_keys():
                self._lookup[match_key] = dates

    def get_dates(self, section: str, item_no: int, revision: int = 0) -> Optional[SubmittalDates]:
        """
        Get dates for a submittal.

        Args:
            section: Spec section (e.g., "03 30 00")
            item_no: Item number
            revision: Revision number (0 = original)

        Returns:
            SubmittalDates if found, None otherwise
        """
        match_key = f"{section}-{item_no}-{revision}"
        return self._lookup.get(match_key)

    def get_dates_by_key(self, match_key: str) -> Optional[SubmittalDates]:
        """Get dates by match key directly."""
        return self._lookup.get(match_key)

    @property
    def total_entries(self) -> int:
        """Total number of submittal date entries."""
        return len(self._lookup)

    def keys(self) -> list[str]:
        """Get all match keys that have dates."""
        return list(self._lookup.keys())
