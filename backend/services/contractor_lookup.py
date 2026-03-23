"""Contractor lookup service - maps spec sections to contractors."""
import io
from typing import Optional
from dataclasses import dataclass

import pandas as pd


@dataclass
class ContractorInfo:
    """Contractor information for Procore."""
    name: str
    vendor_id: Optional[int] = None  # Procore Directory vendor ID (if matched)


class ContractorLookup:
    """
    Maps spec sections to contractors.

    Current implementation: Spec Section level (90% use case)
    Future: Could extend to support Section-Item level for edge cases

    Match key format: "{Section}" (e.g., "03 30 00")
    """

    def __init__(self, mappings: dict[str, ContractorInfo] | None = None):
        """
        Initialize with optional mappings.

        Args:
            mappings: Dict of section -> ContractorInfo
        """
        self._lookup: dict[str, ContractorInfo] = mappings or {}

    @classmethod
    def from_dict(cls, data: dict[str, str | dict]) -> "ContractorLookup":
        """
        Create lookup from a simple dictionary.

        Args:
            data: Dict where key is section, value is either:
                  - str: contractor name
                  - dict: {"name": str, "vendor_id": int}

        Example:
            {
                "03 30 00": "ABC Concrete LLC",
                "05 12 00": {"name": "XYZ Steel", "vendor_id": 12345}
            }
        """
        mappings = {}
        for section, value in data.items():
            if isinstance(value, str):
                mappings[section] = ContractorInfo(name=value)
            elif isinstance(value, dict):
                mappings[section] = ContractorInfo(
                    name=value.get("name", ""),
                    vendor_id=value.get("vendor_id"),
                )
        return cls(mappings)

    def get_contractor(self, section: str) -> Optional[ContractorInfo]:
        """
        Get contractor for a spec section.

        Args:
            section: Spec section (e.g., "03 30 00")

        Returns:
            ContractorInfo if found, None otherwise
        """
        return self._lookup.get(section)

    def get_contractor_name(self, section: str) -> Optional[str]:
        """Get just the contractor name for a section."""
        info = self._lookup.get(section)
        return info.name if info else None

    def get_vendor_id(self, section: str) -> Optional[int]:
        """Get the Procore vendor ID for a section (if matched)."""
        info = self._lookup.get(section)
        return info.vendor_id if info else None

    def set_vendor_id(self, section: str, vendor_id: int) -> bool:
        """
        Set the Procore vendor ID after matching to Directory.

        Returns True if section exists and was updated.
        """
        if section in self._lookup:
            self._lookup[section].vendor_id = vendor_id
            return True
        return False

    @property
    def total_entries(self) -> int:
        """Total number of mapped sections."""
        return len(self._lookup)

    @property
    def matched_count(self) -> int:
        """Number of sections with Procore vendor IDs."""
        return sum(1 for info in self._lookup.values() if info.vendor_id is not None)

    @property
    def unmatched_count(self) -> int:
        """Number of sections without Procore vendor IDs."""
        return sum(1 for info in self._lookup.values() if info.vendor_id is None)

    def sections(self) -> list[str]:
        """Get all mapped spec sections."""
        return list(self._lookup.keys())

    def unmatched_sections(self) -> list[str]:
        """Get sections that haven't been matched to Procore Directory."""
        return [s for s, info in self._lookup.items() if info.vendor_id is None]

    def to_dict(self) -> dict:
        """Export mappings to dictionary (for saving)."""
        return {
            section: {
                "name": info.name,
                "vendor_id": info.vendor_id,
            }
            for section, info in self._lookup.items()
        }

    @staticmethod
    def generate_template(sections: list[str]) -> bytes:
        """
        Generate a CSV template for user to fill in contractors.

        Args:
            sections: List of spec sections from RMS data

        Returns:
            CSV file as bytes (Section | Contractor columns)
        """
        df = pd.DataFrame({
            "Section": sorted(set(sections)),
            "Contractor": "",
        })
        return df.to_csv(index=False).encode("utf-8")

    @classmethod
    def from_csv(cls, csv_bytes: bytes) -> "ContractorLookup":
        """
        Load contractor mappings from filled-in CSV.

        Expected format:
            Section,Contractor
            03 30 00,Altis Concrete
            05 12 00,XYZ Steel

        Args:
            csv_bytes: CSV file contents

        Returns:
            ContractorLookup with mappings
        """
        df = pd.read_csv(io.BytesIO(csv_bytes))
        df.columns = [c.lower().strip() for c in df.columns]

        mappings = {}
        for _, row in df.iterrows():
            section = str(row.get("section", "")).strip()
            contractor = str(row.get("contractor", "")).strip()

            if section and contractor and contractor.lower() != "nan":
                mappings[section] = ContractorInfo(name=contractor)

        return cls(mappings)

    @classmethod
    def from_excel(cls, excel_bytes: bytes, sheet_name: str = None) -> "ContractorLookup":
        """
        Load contractor mappings from Excel file.

        Expected format:
            Section | Contractor
            03 30 00 | Altis Concrete

        Args:
            excel_bytes: Excel file contents
            sheet_name: Optional sheet name (uses first sheet if not specified)

        Returns:
            ContractorLookup with mappings
        """
        df = pd.read_excel(io.BytesIO(excel_bytes), sheet_name=sheet_name or 0)
        df.columns = [c.lower().strip() for c in df.columns]

        mappings = {}
        for _, row in df.iterrows():
            section = str(row.get("section", "")).strip()
            contractor = str(row.get("contractor", "")).strip()

            if section and contractor and contractor.lower() != "nan":
                mappings[section] = ContractorInfo(name=contractor)

        return cls(mappings)
