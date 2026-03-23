"""Vendor matching service - fuzzy match contractor names to Procore Directory."""
import re
from dataclasses import dataclass
from typing import Optional

from models.procore import ProcoreVendor, VendorMatch, VendorSuggestion


@dataclass
class MatchResult:
    """Internal match result."""

    vendor: ProcoreVendor
    score: int
    exact: bool


class VendorMatcher:
    """
    Matches contractor names to Procore Directory vendors.

    Matching algorithm:
    1. Exact match (score 100)
    2. Case-insensitive exact (score 99)
    3. Contains match (score 80) - one name contains the other
    4. Fuzzy match (score 50-79) - word similarity
    5. No match (<50) - flagged for manual review
    """

    def __init__(self, vendors: list[ProcoreVendor]):
        """
        Initialize with list of Procore vendors.

        Args:
            vendors: List of vendors from Procore Directory
        """
        self.vendors = vendors
        self._vendor_lookup = {v.id: v for v in vendors}

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for comparison."""
        # Lowercase, remove non-alphanumeric except spaces
        return re.sub(r"[^a-z0-9\s]", "", text.lower())

    @staticmethod
    def _get_words(text: str) -> list[str]:
        """Extract significant words (>2 chars) from text."""
        normalized = VendorMatcher._normalize(text)
        return [w for w in normalized.split() if len(w) > 2]

    @staticmethod
    def _word_similarity(s1: str, s2: str) -> int:
        """
        Calculate similarity score based on common words.

        Returns score 0-100.
        """
        words1 = VendorMatcher._get_words(s1)
        words2 = VendorMatcher._get_words(s2)

        if not words1 or not words2:
            return 0

        # Count common words
        common = len(set(words1) & set(words2))
        total = max(len(words1), len(words2))

        return round((common / total) * 100)

    def find_best_match(self, contractor_name: str) -> Optional[MatchResult]:
        """
        Find the best matching vendor for a contractor name.

        Args:
            contractor_name: The contractor name from user input

        Returns:
            MatchResult with vendor, score, and exact flag, or None if no match >= 50%
        """
        if not contractor_name or not contractor_name.strip():
            return None

        best_match: Optional[MatchResult] = None
        best_score = 0

        for vendor in self.vendors:
            vendor_name = vendor.name

            # Exact match
            if vendor_name == contractor_name:
                return MatchResult(vendor=vendor, score=100, exact=True)

            # Case-insensitive exact
            if vendor_name.lower() == contractor_name.lower():
                return MatchResult(vendor=vendor, score=99, exact=True)

            # Contains match
            if (
                contractor_name.lower() in vendor_name.lower()
                or vendor_name.lower() in contractor_name.lower()
            ):
                if 80 > best_score:
                    best_score = 80
                    best_match = MatchResult(vendor=vendor, score=80, exact=False)
                continue

            # Fuzzy match
            score = self._word_similarity(contractor_name, vendor_name)
            if score > best_score:
                best_score = score
                best_match = MatchResult(vendor=vendor, score=score, exact=False)

        # Only return if score >= 50
        if best_match and best_score >= 50:
            return best_match

        return None

    def find_top_suggestions(
        self, contractor_name: str, limit: int = 3
    ) -> list[VendorSuggestion]:
        """
        Find top N vendor suggestions for a contractor name.

        Args:
            contractor_name: The contractor name from user input
            limit: Max suggestions to return

        Returns:
            List of VendorSuggestion sorted by score descending
        """
        if not contractor_name or not contractor_name.strip():
            return []

        scores: list[tuple[ProcoreVendor, int, bool]] = []

        for vendor in self.vendors:
            vendor_name = vendor.name

            # Exact match
            if vendor_name == contractor_name:
                scores.append((vendor, 100, True))
                continue

            # Case-insensitive exact
            if vendor_name.lower() == contractor_name.lower():
                scores.append((vendor, 99, True))
                continue

            # Contains match
            if (
                contractor_name.lower() in vendor_name.lower()
                or vendor_name.lower() in contractor_name.lower()
            ):
                scores.append((vendor, 80, False))
                continue

            # Fuzzy match
            score = self._word_similarity(contractor_name, vendor_name)
            if score > 0:
                scores.append((vendor, score, False))

        # Sort by score descending and take top N
        scores.sort(key=lambda x: x[1], reverse=True)

        return [
            VendorSuggestion(
                vendor_id=v.id,
                vendor_name=v.name,
                score=s,
                exact=e,
            )
            for v, s, e in scores[:limit]
        ]

    def match_contractors(
        self, contractor_names: dict[str, str]
    ) -> dict[str, VendorMatch]:
        """
        Match multiple contractors to vendors.

        Args:
            contractor_names: Dict of section -> contractor name

        Returns:
            Dict of section -> VendorMatch with results and suggestions
        """
        results = {}

        for section, name in contractor_names.items():
            if not name or not name.strip():
                continue

            match = self.find_best_match(name)
            suggestions = self.find_top_suggestions(name)

            if match:
                results[section] = VendorMatch(
                    input_name=name,
                    vendor_id=match.vendor.id,
                    vendor_name=match.vendor.name,
                    match_score=match.score,
                    exact_match=match.exact,
                    suggestions=suggestions,
                )
            else:
                results[section] = VendorMatch(
                    input_name=name,
                    vendor_id=None,
                    vendor_name=None,
                    match_score=0,
                    exact_match=False,
                    suggestions=suggestions,
                )

        return results

    def get_vendor_by_id(self, vendor_id: int) -> Optional[ProcoreVendor]:
        """Get a vendor by ID."""
        return self._vendor_lookup.get(vendor_id)
