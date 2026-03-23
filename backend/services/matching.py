"""Submittal matching service."""
from typing import Optional

from models.rms import RMSParseResult, RMSSubmittal
from models.procore import ProcoreSubmittal
from models.matching import (
    MatchResult,
    MatchingSummary,
    MatchStatus,
    FieldConflict,
    ImportMode,
)


class MatchingService:
    """Service for matching submittals between RMS and Procore."""

    def analyze(
        self,
        rms_data: RMSParseResult,
        procore_submittals: list[ProcoreSubmittal],
    ) -> MatchingSummary:
        """
        Analyze RMS data against Procore submittals.

        Returns summary with match statistics and recommended mode.
        """
        # Build lookup maps
        rms_lookup = self._build_rms_lookup(rms_data)
        procore_lookup = self._build_procore_lookup(procore_submittals)

        # Find matches
        all_keys = set(rms_lookup.keys()) | set(procore_lookup.keys())

        matched_count = 0
        rms_only_count = 0
        procore_only_count = 0
        conflict_count = 0

        for key in all_keys:
            in_rms = key in rms_lookup
            in_procore = key in procore_lookup

            if in_rms and in_procore:
                matched_count += 1
                # Check for conflicts
                if self._has_conflicts(rms_lookup[key], procore_lookup[key]):
                    conflict_count += 1
            elif in_rms:
                rms_only_count += 1
            else:
                procore_only_count += 1

        # Calculate match rate
        total_procore = len(procore_submittals)
        match_rate = matched_count / total_procore if total_procore > 0 else 0.0

        # Determine recommended mode
        recommended_mode, reason = self._recommend_mode(
            total_procore, match_rate, rms_only_count, conflict_count
        )

        return MatchingSummary(
            total_rms=len(rms_data.submittals),
            total_procore=total_procore,
            matched_count=matched_count,
            rms_only_count=rms_only_count,
            procore_only_count=procore_only_count,
            conflict_count=conflict_count,
            match_rate=match_rate,
            recommended_mode=recommended_mode,
            recommendation_reason=reason,
        )

    def get_match_results(
        self,
        rms_data: RMSParseResult,
        procore_submittals: list[ProcoreSubmittal],
    ) -> list[MatchResult]:
        """Get detailed match results for all submittals."""
        rms_lookup = self._build_rms_lookup(rms_data)
        procore_lookup = self._build_procore_lookup(procore_submittals)

        results = []
        all_keys = set(rms_lookup.keys()) | set(procore_lookup.keys())

        for key in sorted(all_keys):
            rms_sub = rms_lookup.get(key)
            procore_sub = procore_lookup.get(key)

            if rms_sub and procore_sub:
                status = MatchStatus.MATCHED
                conflicts = self._get_conflicts(rms_sub, procore_sub)
            elif rms_sub:
                status = MatchStatus.RMS_ONLY
                conflicts = []
            else:
                status = MatchStatus.PROCORE_ONLY
                conflicts = []

            # Parse key for section/item/revision
            parts = key.rsplit("-", 2)
            section = parts[0] if len(parts) > 0 else ""
            item_no = int(parts[1]) if len(parts) > 1 else 0
            revision = int(parts[2]) if len(parts) > 2 else 0

            result = MatchResult(
                match_key=key,
                status=status,
                rms_index=rms_data.submittals.index(rms_sub) if rms_sub else None,
                procore_id=procore_sub.id if procore_sub else None,
                section=section,
                item_no=item_no,
                revision=revision,
                title=rms_sub.description if rms_sub else (procore_sub.title if procore_sub else None),
                conflicts=conflicts,
                has_conflicts=len(conflicts) > 0,
            )
            results.append(result)

        return results

    def _build_rms_lookup(self, rms_data: RMSParseResult) -> dict[str, RMSSubmittal]:
        """Build lookup map from RMS submittals by match key."""
        lookup = {}

        # Add base submittals (revision 0)
        for sub in rms_data.submittals:
            key = sub.match_key
            lookup[key] = sub

        # Note: Revisions would be added from transmittal log
        # For now, we just track the base submittals

        return lookup

    def _build_procore_lookup(
        self, submittals: list[ProcoreSubmittal]
    ) -> dict[str, ProcoreSubmittal]:
        """Build lookup map from Procore submittals by match key."""
        lookup = {}
        for sub in submittals:
            key = sub.match_key
            lookup[key] = sub
        return lookup

    def _normalize_key(self, key: str) -> str:
        """Normalize a match key for comparison."""
        # Remove extra spaces, normalize section format
        parts = key.split("-")
        if len(parts) >= 3:
            section = " ".join(parts[0].split())  # Normalize spaces
            item = str(int(parts[1]))  # Remove leading zeros
            revision = parts[2]
            return f"{section}-{item}-{revision}"
        return key

    def _has_conflicts(
        self, rms_sub: RMSSubmittal, procore_sub: ProcoreSubmittal
    ) -> bool:
        """Check if there are any conflicts between RMS and Procore data."""
        # Compare status
        if rms_sub.status and procore_sub.status:
            if rms_sub.status.lower() != procore_sub.status.lower():
                return True

        # Date conflicts would be checked against custom fields
        # For now, just check status

        return False

    def _get_conflicts(
        self, rms_sub: RMSSubmittal, procore_sub: ProcoreSubmittal
    ) -> list[FieldConflict]:
        """Get list of field conflicts between RMS and Procore."""
        conflicts = []

        # Status conflict
        if rms_sub.status and procore_sub.status:
            if rms_sub.status.lower() != procore_sub.status.lower():
                conflicts.append(
                    FieldConflict(
                        field_name="status",
                        rms_value=rms_sub.status,
                        procore_value=procore_sub.status,
                    )
                )

        # Add more field comparisons as needed
        # (dates would come from transmittal log and custom fields)

        return conflicts

    def _recommend_mode(
        self,
        total_procore: int,
        match_rate: float,
        rms_only_count: int,
        conflict_count: int,
    ) -> tuple[ImportMode, str]:
        """Recommend an import mode based on analysis."""
        if total_procore == 0:
            return (
                ImportMode.FULL_MIGRATION,
                "Procore project has no submittals. Full migration recommended.",
            )

        if match_rate > 0.8:
            return (
                ImportMode.SYNC_FROM_RMS,
                f"High match rate ({match_rate:.0%}). "
                f"Will update {int(match_rate * total_procore)} submittals, "
                f"create {rms_only_count} new.",
            )

        if match_rate > 0.2:
            return (
                ImportMode.RECONCILE,
                f"Partial overlap ({match_rate:.0%}). "
                f"{conflict_count} conflicts need review.",
            )

        # Low match rate - unusual situation
        return (
            ImportMode.RECONCILE,
            f"Low match rate ({match_rate:.0%}). "
            "Procore data may be from different project. Review recommended.",
        )
