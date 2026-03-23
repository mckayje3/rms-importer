"""Specification section matching service.

Matches RMS spec section numbers to existing Procore spec sections.
Since there's no API to create spec sections, we can only link to existing ones.
"""
from dataclasses import dataclass
from typing import Optional

from models.procore import ProcoreSpecSection


@dataclass
class SpecMatchResult:
    """Result of matching a single spec section."""

    rms_section: str
    procore_section: Optional[ProcoreSpecSection]
    matched: bool
    match_type: str  # "exact", "normalized", "none"


@dataclass
class SpecMatchSummary:
    """Summary of spec section matching."""

    total_rms_sections: int
    matched_count: int
    unmatched_count: int
    match_rate: float
    results: dict[str, SpecMatchResult]  # rms_section -> result

    def to_dict(self) -> dict:
        return {
            "total_rms_sections": self.total_rms_sections,
            "matched_count": self.matched_count,
            "unmatched_count": self.unmatched_count,
            "match_rate": self.match_rate,
            "matched": {
                k: {
                    "rms_section": v.rms_section,
                    "procore_id": v.procore_section.id if v.procore_section else None,
                    "procore_number": v.procore_section.number if v.procore_section else None,
                    "procore_description": v.procore_section.description if v.procore_section else None,
                    "match_type": v.match_type,
                }
                for k, v in self.results.items()
                if v.matched
            },
            "unmatched": [
                v.rms_section for v in self.results.values() if not v.matched
            ],
        }


class SpecMatcher:
    """
    Matches RMS spec sections to Procore spec sections.

    Matching strategy:
    1. Exact match on section number
    2. Normalized match (remove spaces, lowercase)
    3. Base section match (e.g., "03 30 00.00 06" matches "03 30 00")
    """

    def __init__(self, procore_sections: list[ProcoreSpecSection]):
        """
        Initialize with Procore spec sections.

        Args:
            procore_sections: List of spec sections from Procore
        """
        self.procore_sections = procore_sections

        # Build lookup tables
        self._exact_lookup: dict[str, ProcoreSpecSection] = {}
        self._normalized_lookup: dict[str, ProcoreSpecSection] = {}
        self._base_lookup: dict[str, ProcoreSpecSection] = {}

        for section in procore_sections:
            # Exact lookup
            self._exact_lookup[section.number] = section

            # Normalized lookup (lowercase, single spaces)
            normalized = self._normalize(section.number)
            self._normalized_lookup[normalized] = section

            # Base section lookup (first 8 chars: "XX XX XX")
            base = self._get_base_section(section.number)
            if base and base not in self._base_lookup:
                self._base_lookup[base] = section

    @staticmethod
    def _normalize(section: str) -> str:
        """Normalize section number for matching."""
        return " ".join(section.lower().split())

    @staticmethod
    def _get_base_section(section: str) -> Optional[str]:
        """
        Extract base section (first 8 chars like "03 30 00").

        UFGS format: "03 30 00.00 06" -> "03 30 00"
        Standard format: "03 30 00" -> "03 30 00"
        """
        normalized = " ".join(section.split())
        if len(normalized) >= 8:
            base = normalized[:8].strip()
            # Validate it looks like a section number
            parts = base.split()
            if len(parts) == 3 and all(len(p) == 2 for p in parts):
                return base.lower()
        return None

    def match_section(self, rms_section: str) -> SpecMatchResult:
        """
        Match a single RMS section to a Procore section.

        Args:
            rms_section: Section number from RMS

        Returns:
            SpecMatchResult with match details
        """
        # Try exact match
        if rms_section in self._exact_lookup:
            return SpecMatchResult(
                rms_section=rms_section,
                procore_section=self._exact_lookup[rms_section],
                matched=True,
                match_type="exact",
            )

        # Try normalized match
        normalized = self._normalize(rms_section)
        if normalized in self._normalized_lookup:
            return SpecMatchResult(
                rms_section=rms_section,
                procore_section=self._normalized_lookup[normalized],
                matched=True,
                match_type="normalized",
            )

        # Try base section match
        base = self._get_base_section(rms_section)
        if base and base in self._base_lookup:
            return SpecMatchResult(
                rms_section=rms_section,
                procore_section=self._base_lookup[base],
                matched=True,
                match_type="base",
            )

        # No match
        return SpecMatchResult(
            rms_section=rms_section,
            procore_section=None,
            matched=False,
            match_type="none",
        )

    def match_all(self, rms_sections: list[str]) -> SpecMatchSummary:
        """
        Match all RMS sections to Procore sections.

        Args:
            rms_sections: List of section numbers from RMS

        Returns:
            SpecMatchSummary with all results
        """
        # Deduplicate RMS sections
        unique_sections = sorted(set(rms_sections))

        results: dict[str, SpecMatchResult] = {}
        for section in unique_sections:
            results[section] = self.match_section(section)

        matched_count = sum(1 for r in results.values() if r.matched)
        total = len(unique_sections)

        return SpecMatchSummary(
            total_rms_sections=total,
            matched_count=matched_count,
            unmatched_count=total - matched_count,
            match_rate=round((matched_count / total * 100) if total > 0 else 0, 1),
            results=results,
        )

    def get_section_id(self, rms_section: str) -> Optional[int]:
        """
        Get Procore section ID for an RMS section.

        Convenience method for use during import.

        Args:
            rms_section: Section number from RMS

        Returns:
            Procore section ID if matched, None otherwise
        """
        result = self.match_section(rms_section)
        return result.procore_section.id if result.matched else None
