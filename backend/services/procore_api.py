"""Procore API client service."""
import httpx
from typing import Optional
import asyncio

from config import get_settings
from models.procore import (
    ProcoreCompany,
    ProcoreProject,
    ProcoreSubmittal,
    ProcoreSpecSection,
    ProcoreStats,
    ProcoreVendor,
    ProcoreObservation,
    ProcoreObservationType,
    ProcoreLocation,
)

settings = get_settings()


class ProcoreAPI:
    """Client for Procore REST API."""

    def __init__(self, access_token: str, company_id: Optional[int] = None):
        self.access_token = access_token
        self.company_id = company_id
        self.base_url = settings.procore_base_url

    def _headers(self) -> dict:
        """Get request headers."""
        headers = {"Authorization": f"Bearer {self.access_token}"}
        if self.company_id:
            headers["Procore-Company-Id"] = str(self.company_id)
        return headers

    async def _get(self, endpoint: str, params: Optional[dict] = None) -> dict | list:
        """Make GET request to Procore API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}{endpoint}",
                headers=self._headers(),
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def _get_paginated(
        self, endpoint: str, params: Optional[dict] = None, per_page: int = 100
    ) -> list:
        """Get all pages of a paginated endpoint."""
        all_items = []
        page = 1
        params = params or {}

        while True:
            params["page"] = page
            params["per_page"] = per_page

            items = await self._get(endpoint, params)

            if not items:
                break

            all_items.extend(items)

            if len(items) < per_page:
                break

            page += 1
            await asyncio.sleep(0.1)  # Rate limit protection

        return all_items

    async def _post(self, endpoint: str, data: dict) -> dict:
        """Make POST request to Procore API."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}{endpoint}",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=data,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def _patch(self, endpoint: str, data: dict) -> dict:
        """Make PATCH request to Procore API."""
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.base_url}{endpoint}",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=data,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    # === Company & Project Methods ===

    async def get_companies(self) -> list[ProcoreCompany]:
        """Get list of companies user has access to."""
        data = await self._get("/rest/v1.0/companies")
        return [
            ProcoreCompany(id=c["id"], name=c["name"], is_active=c.get("is_active", True))
            for c in data
        ]

    async def get_projects(self) -> list[ProcoreProject]:
        """Get list of projects for the company."""
        data = await self._get("/rest/v1.0/projects", params={"company_id": self.company_id})
        return [
            ProcoreProject(
                id=p["id"],
                name=p["name"],
                company_id=self.company_id,
                active=p.get("active", True),
            )
            for p in data
        ]

    # === Submittal Methods ===

    async def get_submittals(self, project_id: int) -> list[ProcoreSubmittal]:
        """Get all submittals for a project."""
        data = await self._get_paginated(
            f"/rest/v1.0/projects/{project_id}/submittals"
        )
        return [self._parse_submittal(s) for s in data]

    def _parse_submittal(self, data: dict) -> ProcoreSubmittal:
        """Parse a submittal from API response."""
        spec_section = None
        if data.get("specification_section"):
            ss = data["specification_section"]
            spec_section = ProcoreSpecSection(
                id=ss["id"],
                number=ss.get("number", ""),
                description=ss.get("description"),
            )

        return ProcoreSubmittal(
            id=data["id"],
            number=str(data.get("number", "")),
            title=data.get("title", ""),
            revision=data.get("revision", 0),
            status=data["status"]["status"] if isinstance(data.get("status"), dict) else data.get("status"),
            specification_section=spec_section,
        )

    async def get_submittal_stats(self, project_id: int) -> ProcoreStats:
        """Get submittal statistics for a project."""
        submittals = await self.get_submittals(project_id)

        spec_sections = set()
        revision_count = 0

        for sub in submittals:
            if sub.specification_section:
                spec_sections.add(sub.specification_section.number)
            if sub.revision > 0:
                revision_count += 1

        return ProcoreStats(
            submittal_count=len(submittals),
            spec_section_count=len(spec_sections),
            revision_count=revision_count,
            spec_sections=sorted(spec_sections),
        )

    async def create_submittal(self, project_id: int, submittal_data: dict) -> dict:
        """Create a new submittal."""
        return await self._post(
            f"/rest/v1.0/projects/{project_id}/submittals",
            {"submittal": submittal_data},
        )

    async def update_submittal(
        self, project_id: int, submittal_id: int, submittal_data: dict
    ) -> dict:
        """Update an existing submittal."""
        return await self._patch(
            f"/rest/v1.0/projects/{project_id}/submittals/{submittal_id}",
            {"submittal": submittal_data},
        )

    # === File Upload Methods ===

    async def upload_file_to_submittal(
        self,
        project_id: int,
        submittal_id: int,
        file_path: str,
        upload_folder_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Upload a file and attach it to a submittal.

        6-step Procore upload process:
        1. Create upload → get S3 presigned URL
        2. Upload file bytes to S3
        3. Create document in project
        4. Get prostore_file_id from document
        5. Get existing attachments on submittal
        6. PATCH submittal with all attachment IDs

        Returns prostore_file_id on success, None on failure.
        """
        import os
        import mimetypes

        folder_id = upload_folder_id or settings.procore_upload_folder_id
        if not folder_id:
            raise Exception(
                "PROCORE_UPLOAD_FOLDER_ID not configured. "
                "Set it in .env to the Documents folder ID where files should be uploaded."
            )

        filename = os.path.basename(file_path)
        content_type = mimetypes.guess_type(filename)[0] or "application/pdf"

        # Step 1: Create project upload
        upload_info = await self._post(
            f"/rest/v1.0/projects/{project_id}/uploads",
            {
                "response_filename": filename,
                "response_content_type": content_type,
            },
        )

        # Step 2: Upload to S3
        file_bytes = open(file_path, "rb").read()
        async with httpx.AsyncClient() as client:
            # Build multipart form data with S3 fields
            files = {"file": (filename, file_bytes, content_type)}
            data = {k: str(v) for k, v in upload_info["fields"].items()}

            response = await client.post(
                upload_info["url"],
                data=data,
                files=files,
                timeout=120.0,
            )
            response.raise_for_status()

        # Step 3: Create document in project
        doc_response = await self._post(
            f"/rest/v1.0/projects/{project_id}/documents",
            {
                "document": {
                    "name": filename,
                    "upload_uuid": upload_info["uuid"],
                    "parent_id": folder_id,
                },
            },
        )
        doc_id = doc_response["id"]

        # Step 4: Get prostore_file_id
        await asyncio.sleep(0.5)  # Wait for processing
        docs = await self._get(
            f"/rest/v1.0/projects/{project_id}/documents",
            params={
                "view": "extended",
                "filters[document_type]": "file",
                "per_page": 10,
                "sort": "-updated_at",
            },
        )
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if not doc or not doc.get("file", {}).get("current_version", {}).get("prostore_file"):
            raise Exception(f"Could not get prostore_file_id for document {doc_id}")

        prostore_file_id = doc["file"]["current_version"]["prostore_file"]["id"]

        # Step 5: Get existing attachments on submittal
        submittal = await self._get(
            f"/rest/v1.0/projects/{project_id}/submittals/{submittal_id}"
        )
        existing_ids = [att["id"] for att in submittal.get("attachments", [])]
        all_ids = existing_ids + [prostore_file_id]

        # Step 6: Attach to submittal
        await self._patch(
            f"/rest/v1.1/projects/{project_id}/submittals/{submittal_id}",
            {"submittal": {"prostore_file_ids": all_ids}},
        )

        return prostore_file_id

    # === Specification Methods ===

    async def get_specification_sets(self, project_id: int) -> list[dict]:
        """Get specification sets for a project."""
        return await self._get(f"/rest/v1.0/projects/{project_id}/specification_sets")

    async def get_spec_sections(self, project_id: int) -> list[ProcoreSpecSection]:
        """
        Get all unique spec sections from project submittals.

        Note: There's no direct API to list spec sections, so we extract
        them from existing submittals.
        """
        submittals = await self.get_submittals(project_id)

        # Extract unique spec sections
        sections: dict[int, ProcoreSpecSection] = {}
        for sub in submittals:
            if sub.specification_section and sub.specification_section.id not in sections:
                sections[sub.specification_section.id] = sub.specification_section

        return list(sections.values())

    # === Directory/Vendor Methods ===

    async def get_project_vendors(self, project_id: int) -> list[ProcoreVendor]:
        """Get all vendors from project directory."""
        data = await self._get_paginated(f"/rest/v1.0/projects/{project_id}/vendors")
        return [self._parse_vendor(v) for v in data]

    async def get_company_vendors(self) -> list[ProcoreVendor]:
        """Get all vendors from company directory."""
        data = await self._get_paginated("/rest/v1.0/vendors")
        return [self._parse_vendor(v) for v in data]

    def _parse_vendor(self, data: dict) -> ProcoreVendor:
        """Parse a vendor from API response."""
        return ProcoreVendor(
            id=data["id"],
            name=data.get("name", ""),
            company=data.get("company"),
            business_phone=data.get("business_phone"),
            email_address=data.get("email_address"),
            is_active=data.get("is_active", True),
        )

    # === Observation Methods ===

    async def get_observations(self, project_id: int) -> list[ProcoreObservation]:
        """Get all observations for a project."""
        data = await self._get_paginated(
            f"/rest/v1.0/projects/{project_id}/observations/items"
        )
        return [self._parse_observation(o) for o in data]

    async def get_observation_types(self, project_id: int) -> list[ProcoreObservationType]:
        """Get observation types for a project."""
        data = await self._get(f"/rest/v1.0/projects/{project_id}/observations/types")
        return [
            ProcoreObservationType(
                id=t["id"],
                name=t.get("name", ""),
                category=t.get("category"),
            )
            for t in data
        ]

    async def get_locations(self, project_id: int) -> list[ProcoreLocation]:
        """Get all locations for a project."""
        data = await self._get_paginated(f"/rest/v1.0/projects/{project_id}/locations")
        return [
            ProcoreLocation(
                id=loc["id"],
                name=loc.get("name", ""),
                parent_id=loc.get("parent_id"),
            )
            for loc in data
        ]

    async def create_observation(self, project_id: int, observation_data: dict) -> dict:
        """Create a new observation.

        Args:
            project_id: Procore project ID
            observation_data: Observation fields including:
                - name: Title (required)
                - description: Detailed description
                - status: open, ready_for_review, not_accepted, closed
                - priority: low, medium, high
                - type_id: Observation type ID
                - location_id: Location ID
                - assignee_id: User/vendor ID

        Returns:
            Created observation data
        """
        return await self._post(
            f"/rest/v1.0/projects/{project_id}/observations/items",
            {"observation_item": observation_data},
        )

    async def update_observation(
        self, project_id: int, observation_id: int, observation_data: dict
    ) -> dict:
        """Update an existing observation."""
        return await self._patch(
            f"/rest/v1.0/projects/{project_id}/observations/items/{observation_id}",
            {"observation_item": observation_data},
        )

    async def create_location(self, project_id: int, name: str, parent_id: Optional[int] = None) -> dict:
        """Create a new location.

        Args:
            project_id: Procore project ID
            name: Location name
            parent_id: Parent location ID (optional)

        Returns:
            Created location data
        """
        location_data = {"name": name}
        if parent_id:
            location_data["parent_id"] = parent_id

        return await self._post(
            f"/rest/v1.0/projects/{project_id}/locations",
            {"location": location_data},
        )

    def _parse_observation(self, data: dict) -> ProcoreObservation:
        """Parse an observation from API response."""
        return ProcoreObservation(
            id=data["id"],
            number=data.get("number"),
            name=data.get("name", ""),
            description=data.get("description"),
            status=data.get("status", "open"),
            priority=data.get("priority"),
            due_date=data.get("due_date"),
            created_at=data.get("created_at"),
            location=data.get("location"),
            assignee=data.get("assignee"),
            observation_type=data.get("type"),
        )
