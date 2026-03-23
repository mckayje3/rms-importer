"""Info lookup service - maps Submittal Assignments info to submittals."""
from typing import Optional

from models.rms import RMSAssignment


class InfoLookup:
    """
    Builds a lookup table from Submittal Assignments.

    Maps submittals to their Info field (GA, FIO, S).
    Match key format: "{Section}-{ItemNo}" (no revision - applies to base submittal)

    Info values:
        - GA: Government Approval required
        - FIO: For Information Only
        - S: Standard (or blank)
    """

    def __init__(self, assignments: list[RMSAssignment]):
        """Build lookup from assignment entries."""
        self._lookup: dict[str, str] = {}

        for assignment in assignments:
            if assignment.info_only:
                key = f"{assignment.section}-{assignment.item_no}"
                self._lookup[key] = assignment.info_only.strip().upper()

    def get_info(self, section: str, item_no: int) -> Optional[str]:
        """
        Get Info field for a submittal.

        Args:
            section: Spec section (e.g., "03 30 00")
            item_no: Item number

        Returns:
            Info value (GA, FIO, S) or None if not found
        """
        key = f"{section}-{item_no}"
        return self._lookup.get(key)

    @property
    def total_entries(self) -> int:
        """Total number of submittals with Info values."""
        return len(self._lookup)

    def keys(self) -> list[str]:
        """Get all match keys that have Info values."""
        return list(self._lookup.keys())
