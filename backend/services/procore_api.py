"""Procore API client service."""
import httpx
import logging
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
    ProcoreRFI,
)

settings = get_settings()
logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when Procore rate limit is exceeded after all retries."""
    pass


class ProcoreAPI:
    """Client for Procore REST API."""

    # Rate limit retry config
    MAX_RETRIES = 3
    RETRY_DELAYS = [30, 60, 120]  # seconds: 30s, 1min, 2min backoff

    def __init__(self, access_token: str, company_id: Optional[int] = None):
        self.access_token = access_token
        self.company_id = company_id
        self.base_url = settings.procore_base_url
        self.rate_limit_hits = 0  # Track how many 429s we've hit

    def _headers(self) -> dict:
        """Get request headers."""
        headers = {"Authorization": f"Bearer {self.access_token}"}
        if self.company_id:
            headers["Procore-Company-Id"] = str(self.company_id)
        return headers

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> httpx.Response:
        """
        Make an HTTP request with automatic retry on 429 rate limit errors.

        Retries with increasing backoff (30s, 60s, 120s).
        Raises RateLimitError if all retries are exhausted.
        """
        url = f"{self.base_url}{endpoint}"

        for attempt in range(self.MAX_RETRIES + 1):
            async with httpx.AsyncClient() as client:
                request_method = getattr(client, method)
                response = await request_method(url, **kwargs)

                if response.status_code != 429:
                    if response.status_code >= 400:
                        # Include response body in error for debugging
                        body = response.text[:500]
                        logger.error(f"{method.upper()} {endpoint} → {response.status_code}: {body}")
                    response.raise_for_status()
                    return response

                # Rate limited
                self.rate_limit_hits += 1

                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Rate limited (429) on {method.upper()} {endpoint}, "
                        f"retry {attempt + 1}/{self.MAX_RETRIES} in {delay}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise RateLimitError(
                        f"Rate limit exceeded after {self.MAX_RETRIES} retries "
                        f"on {method.upper()} {endpoint}"
                    )

    async def _get(self, endpoint: str, params: Optional[dict] = None) -> dict | list:
        """Make GET request to Procore API with rate limit retry."""
        response = await self._request_with_retry(
            "get", endpoint,
            headers=self._headers(),
            params=params,
            timeout=30.0,
        )
        return response.json()

    async def _get_with_headers(
        self, endpoint: str, params: Optional[dict] = None
    ) -> tuple[dict | list, "httpx.Headers"]:
        """GET that also returns response headers (for Total / pagination)."""
        response = await self._request_with_retry(
            "get", endpoint,
            headers=self._headers(),
            params=params,
            timeout=30.0,
        )
        return response.json(), response.headers

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
            await asyncio.sleep(0.5)  # Rate limit protection

        return all_items

    async def _post(self, endpoint: str, data: dict) -> dict:
        """Make POST request to Procore API with rate limit retry."""
        response = await self._request_with_retry(
            "post", endpoint,
            headers={**self._headers(), "Content-Type": "application/json"},
            json=data,
            timeout=30.0,
        )
        return response.json()

    async def _patch(self, endpoint: str, data: dict) -> dict:
        """Make PATCH request to Procore API with rate limit retry."""
        response = await self._request_with_retry(
            "patch", endpoint,
            headers={**self._headers(), "Content-Type": "application/json"},
            json=data,
            timeout=30.0,
        )
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
        """Get submittal statistics for a project.

        Uses Procore's Total pagination header from a per_page=1 list request
        to get the count without pulling record data — one API call instead
        of (count / 100) paginated calls. Procore Marketplace API guidelines
        favor targeted queries over broad data pulls; this is the targeted
        version. Spec section and revision counts are not populated on the
        fast path because Procore has no listing endpoint that returns them
        without iterating submittals.
        """
        try:
            _, headers = await self._get_with_headers(
                f"/rest/v1.0/projects/{project_id}/submittals",
                params={"per_page": 1, "page": 1},
            )
            total_str = headers.get("Total") or headers.get("X-Total")
            if total_str is not None:
                count = int(total_str)
                return ProcoreStats(
                    submittal_count=count,
                    spec_section_count=None,
                    revision_count=None,
                    spec_sections=[],
                )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Could not read Total header for stats, falling back: {e}")

        # Fallback (header missing): full fetch. Should be rare.
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

    # Known custom field labels from PowerShell migration scripts.
    # Procore's submittal detail response doesn't include field labels,
    # and the admin definition endpoint requires elevated permissions.
    KNOWN_FIELD_LABELS = {
        "custom_field_598134325870420": "Paragraph",
        "custom_field_598134325871359": "QC Code",
        "custom_field_598134325871360": "QA Code",
        "custom_field_598134325871364": "Info",
        "custom_field_598134325872866": "Contractor Prepared",
        "custom_field_598134325872868": "Government Received",
        "custom_field_598134325872869": "Government Returned",
        "custom_field_598134325872871": "Contractor Received",
    }

    async def get_custom_fields_for_submittals(self, project_id: int) -> list[dict]:
        """
        Discover custom fields on submittals by reading a submittal detail.

        The company-level custom field definition endpoints require elevated
        permissions not available with user OAuth tokens. Instead, we fetch
        a single submittal's detail to get the list of custom field keys,
        then apply known labels where available.
        """
        try:
            # Fetch one submittal to inspect its custom fields
            subs = await self._get(
                f"/rest/v1.0/projects/{project_id}/submittals",
                params={"per_page": 1},
            )
            if not subs:
                logger.warning("No submittals found to discover custom fields from")
                return []

            # Get the full detail (list endpoint may not include custom fields)
            sub_id = subs[0]["id"]
            detail = await self._get(
                f"/rest/v1.0/projects/{project_id}/submittals/{sub_id}"
            )

            custom_fields_data = detail.get("custom_fields", {})
            if not custom_fields_data:
                logger.warning(f"Submittal {sub_id} has no custom_fields in response")
                return []

            logger.warning(f"Discovered {len(custom_fields_data)} custom fields from submittal {sub_id}")

            custom_fields = []
            for field_key in custom_fields_data.keys():
                cf_id = field_key.replace("custom_field_", "")
                field_data = custom_fields_data[field_key]

                # Try to extract label from field data, fall back to known labels
                label = None
                if isinstance(field_data, dict):
                    label = field_data.get("label") or field_data.get("name")
                if not label:
                    label = self.KNOWN_FIELD_LABELS.get(field_key, field_key)

                # Log for debugging
                logger.warning(f"  {field_key}: label='{label}', data_type={type(field_data).__name__}")

                custom_fields.append({
                    "id": cf_id,
                    "label": label,
                    "data_type": "string",
                    "field_key": field_key,
                })

            return custom_fields
        except Exception as e:
            logger.warning(f"Failed to discover custom fields from submittal: {e}")
            return []

    async def get_submittal_statuses(self, project_id: int) -> list[dict]:
        """
        Get available submittal statuses for a project.

        Tries the settings endpoint first, then falls back to scanning
        a sample of existing submittals. Returns list of dicts with 'name' and 'id'.
        """
        default_statuses = [
            {"name": "Draft", "id": None},
            {"name": "Open", "id": None},
            {"name": "Closed", "id": None},
        ]

        try:
            # Try settings endpoint for status configuration
            settings = await self._get(
                f"/rest/v1.0/projects/{project_id}/submittals/settings"
            )
            if isinstance(settings, dict) and "statuses" in settings:
                statuses = []
                for s in settings["statuses"]:
                    statuses.append({
                        "name": s.get("name", ""),
                        "id": s.get("id"),
                    })
                if statuses:
                    return statuses
        except Exception as e:
            logger.warning(f"Settings endpoint failed, scanning submittals: {e}")

        try:
            # Fallback: scan raw submittal data to discover statuses with IDs
            raw_data = await self._get_paginated(
                f"/rest/v1.0/projects/{project_id}/submittals"
            )
            found = {}
            for sub in raw_data:
                status = sub.get("status")
                if isinstance(status, dict):
                    name = status.get("name") or status.get("status", "")
                    sid = status.get("id")
                    if name and name not in found:
                        found[name] = {"name": name, "id": sid}
            if found:
                return sorted(found.values(), key=lambda s: s["name"])
        except Exception as e:
            logger.warning(f"Failed to scan submittals for statuses: {e}")

        return default_statuses

    # === File Upload Methods ===

    async def upload_file(
        self,
        project_id: int,
        file_path: str,
        upload_folder_id: Optional[int] = None,
    ) -> int:
        """
        Upload a file to Procore and return its prostore_file_id.

        First checks if the file already exists (by name) to avoid
        duplicate uploads and wasted API calls. If found, returns
        the existing prostore_file_id immediately (1 API call).

        Otherwise does the full upload (4 API calls):
        1. Create upload → get S3 presigned URL
        2. Upload file bytes to S3
        3. Create document in project
        4. Get prostore_file_id from document

        Returns prostore_file_id.
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

        # Check if file already exists BEFORE uploading (1 API call vs 4+)
        existing_id = await self._find_existing_document(project_id, filename, folder_id)
        if existing_id:
            logger.info(f"File '{filename}' already in Documents, reusing prostore_file_id {existing_id}")
            return existing_id

        await asyncio.sleep(1)  # Spike limit protection

        # Step 1: Create project upload
        upload_info = await self._post(
            f"/rest/v1.0/projects/{project_id}/uploads",
            {
                "response_filename": filename,
                "response_content_type": content_type,
            },
        )

        # Step 2: Upload to S3 (not a Procore API call — no rate limit)
        file_bytes = open(file_path, "rb").read()
        async with httpx.AsyncClient() as client:
            files = {"file": (filename, file_bytes, content_type)}
            data = {k: str(v) for k, v in upload_info["fields"].items()}

            response = await client.post(
                upload_info["url"],
                data=data,
                files=files,
                timeout=120.0,
            )
            response.raise_for_status()

        await asyncio.sleep(1)  # Spike limit protection

        # Step 3: Create document in project
        try:
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
        except Exception as e:
            # "name has already been taken" — file exists but the cache missed
            # it (e.g. created between cache build and now, or cache failed).
            # Bust the cache and rebuild via _find_existing_document so the
            # paginated lookup catches it.
            if "400" in str(e):
                logger.info(f"Document '{filename}' already exists (400), rebuilding doc cache...")
                self._doc_cache.pop(project_id, None)
                pid = await self._find_existing_document(project_id, filename, folder_id)
                if pid:
                    return pid
                raise Exception(
                    f"POST /documents returned 400 for '{filename}' but no matching "
                    f"document found in folder {folder_id} after cache rebuild"
                )
            raise

        await asyncio.sleep(1)  # Spike limit protection

        # Step 4: Get prostore_file_id
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

        return doc["file"]["current_version"]["prostore_file"]["id"]

    # Cache of known documents: {project_id: {filename: prostore_file_id}}
    # Populated once per project on first lookup, reused for all subsequent files.
    _doc_cache: dict[int, dict[str, int]] = {}

    async def _find_existing_document(
        self,
        project_id: int,
        filename: str,
        folder_id: int,
    ) -> Optional[int]:
        """Find an existing document by filename and return its prostore_file_id.

        Uses a per-project cache: first call paginates through every doc in
        the folder so we can detect duplicates regardless of folder size.
        Folders from prior migrations can hold 1000+ files; without
        pagination, an upload of a file beyond page 1 would 400 out at the
        document-create step with "name has already been taken".
        """
        # Build cache on first call for this project
        if project_id not in self._doc_cache:
            self._doc_cache[project_id] = {}
            page = 1
            per_page = 300
            try:
                while True:
                    docs = await self._get(
                        f"/rest/v1.0/projects/{project_id}/documents",
                        params={
                            "view": "extended",
                            "filters[document_type]": "file",
                            "filters[parent_id]": folder_id,
                            "per_page": per_page,
                            "page": page,
                        },
                    )
                    for doc in docs:
                        name = doc.get("name", "")
                        prostore = doc.get("file", {}).get("current_version", {}).get("prostore_file")
                        if name and prostore:
                            self._doc_cache[project_id][name] = prostore["id"]
                    if len(docs) < per_page:
                        break
                    page += 1
                    await asyncio.sleep(0.5)  # Rate limit protection
                logger.info(f"Cached {len(self._doc_cache[project_id])} existing documents for project {project_id}")
            except Exception as e:
                logger.warning(f"Failed to cache existing documents: {e}")

        prostore_id = self._doc_cache[project_id].get(filename)
        if prostore_id:
            logger.info(f"Found existing document '{filename}' (cached) with prostore_file_id {prostore_id}")
        return prostore_id

    async def list_folder_files(
        self,
        project_id: int,
        folder_id: int,
    ) -> list[str]:
        """List all filenames in a Procore Documents folder.

        Paginates through all files. Returns list of filenames.
        """
        filenames = []
        page = 1
        while True:
            docs = await self._get(
                f"/rest/v1.0/projects/{project_id}/documents",
                params={
                    "filters[document_type]": "file",
                    "filters[parent_id]": folder_id,
                    "per_page": 300,
                    "page": page,
                },
            )
            for doc in docs:
                name = doc.get("name", "")
                if name:
                    filenames.append(name)
            if len(docs) < 300:
                break
            page += 1
            await asyncio.sleep(1)
        return filenames

    async def attach_file_to_submittal(
        self,
        project_id: int,
        submittal_id: int,
        prostore_file_id: int,
    ) -> None:
        """
        Attach an already-uploaded file to a submittal.

        Steps 5-6 only: GET existing attachments, PATCH to add the new one.
        Uses 2 API calls vs 6 for a full upload.
        """
        # Get existing attachments
        submittal = await self._get(
            f"/rest/v1.0/projects/{project_id}/submittals/{submittal_id}"
        )
        existing_ids = [att["id"] for att in submittal.get("attachments", [])]

        # Skip if already attached
        if prostore_file_id in existing_ids:
            return

        all_ids = existing_ids + [prostore_file_id]

        # Attach
        await self._patch(
            f"/rest/v1.1/projects/{project_id}/submittals/{submittal_id}",
            {"submittal": {"prostore_file_ids": all_ids}},
        )

    async def upload_file_to_submittal(
        self,
        project_id: int,
        submittal_id: int,
        file_path: str,
        upload_folder_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Upload a file and attach it to a single submittal.

        Convenience method that combines upload_file() + attach_file_to_submittal().
        For multi-item transmittals, use upload_file() once then
        attach_file_to_submittal() for each target.

        Returns prostore_file_id on success.
        """
        prostore_file_id = await self.upload_file(
            project_id, file_path, upload_folder_id
        )
        await self.attach_file_to_submittal(
            project_id, submittal_id, prostore_file_id
        )
        return prostore_file_id

    # === Specification Methods ===

    async def get_specification_sets(self, project_id: int) -> list[dict]:
        """Get specification sets for a project."""
        return await self._get(f"/rest/v1.0/projects/{project_id}/specification_sets")

    async def get_spec_sections(self, project_id: int) -> list[ProcoreSpecSection]:
        """
        Get all unique spec sections from project submittals.

        Note: There's no direct Procore API to list spec sections independently,
        so we extract them from existing submittals. The SpecMatcher service
        handles fuzzy matching (normalized, base section) to compensate.
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
                - type_id: Observation type ID (required)
                - description: Detailed description
                - status: initiated, ready_for_review, not_accepted, closed
                - priority: Low, Medium, High, Urgent
                - location_id: Location ID
                - assignee_id: User/vendor ID
                - due_date: YYYY-MM-DD
                - personal: bool

        Returns:
            Created observation data
        """
        return await self._post(
            f"/rest/v1.0/observations/items",
            {"project_id": project_id, "observation": observation_data},
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

    # === RFI Methods ===

    async def get_rfis(self, project_id: int) -> list[ProcoreRFI]:
        """Get all RFIs for a project."""
        data = await self._get_paginated(
            f"/rest/v1.0/projects/{project_id}/rfis"
        )
        return [self._parse_rfi(r) for r in data]

    def _parse_rfi(self, data: dict) -> ProcoreRFI:
        """Parse an RFI from API response."""
        return ProcoreRFI(
            id=data["id"],
            number=data.get("number"),
            subject=data.get("subject", ""),
            status=data.get("status"),
            due_date=data.get("due_date"),
            created_at=data.get("created_at"),
        )

    async def create_rfi(self, project_id: int, rfi_data: dict) -> dict:
        """Create a new RFI.

        Args:
            project_id: Procore project ID
            rfi_data: RFI fields including subject, question_body, number, etc.
        """
        return await self._post(
            f"/rest/v1.0/projects/{project_id}/rfis",
            {"rfi": rfi_data},
        )

    async def update_rfi(self, project_id: int, rfi_id: int, rfi_data: dict) -> dict:
        """Update an existing RFI."""
        return await self._patch(
            f"/rest/v1.0/projects/{project_id}/rfis/{rfi_id}",
            {"rfi": rfi_data},
        )

    async def attach_file_to_rfi(
        self,
        project_id: int,
        rfi_id: int,
        prostore_file_id: int,
    ) -> None:
        """Attach an already-uploaded file to an RFI.

        PATCH /rfis/{id} with `prostore_file_ids` *replaces* the entire
        attachment list — it does not append. So when more than one file
        targets the same RFI, we have to GET the existing attachments,
        merge our new id in, and PATCH the full list. Without the merge,
        every file after the first overwrites its predecessor and the RFI
        ends up with at most one attachment.

        Procore stores RFI attachments on the question body
        (`questions[0].attachments`); we also fall back to a top-level
        `attachments` field defensively in case Procore returns either.
        """
        # Get existing attachments from the RFI detail
        rfi_detail = await self._get(
            f"/rest/v1.0/projects/{project_id}/rfis/{rfi_id}"
        )

        existing_ids: list[int] = []
        seen: set[int] = set()

        def _collect(items):
            for att in items or []:
                att_id = att.get("id") if isinstance(att, dict) else None
                if isinstance(att_id, int) and att_id not in seen:
                    existing_ids.append(att_id)
                    seen.add(att_id)

        # Procore stores RFI attachments under the first question's
        # `attachments` array. Defensively also check a top-level field.
        questions = rfi_detail.get("questions") or []
        if questions:
            _collect((questions[0] or {}).get("attachments"))
        _collect(rfi_detail.get("attachments"))

        # Skip if already attached
        if prostore_file_id in seen:
            return

        all_ids = existing_ids + [prostore_file_id]

        await self._patch(
            f"/rest/v1.0/projects/{project_id}/rfis/{rfi_id}",
            {"rfi": {"prostore_file_ids": all_ids}},
        )

    async def create_rfi_reply(self, project_id: int, rfi_id: int, reply_data: dict) -> dict:
        """Create a reply on an RFI (e.g., the government response).

        Args:
            project_id: Procore project ID
            rfi_id: RFI ID
            reply_data: Reply fields including body text
        """
        return await self._post(
            f"/rest/v1.0/projects/{project_id}/rfis/{rfi_id}/replies",
            {"reply": reply_data},
        )

    # === Daily Log Methods ===

    async def get_manpower_logs(self, project_id: int, log_date: str | None = None) -> list[dict]:
        """Get manpower log entries, optionally filtered by date (YYYY-MM-DD)."""
        params = {"per_page": 300}
        if log_date:
            params["log_date"] = log_date
        return await self._get(
            f"/rest/v1.0/projects/{project_id}/manpower_logs",
            params=params,
        )

    async def create_manpower_log(self, project_id: int, data: dict) -> dict:
        """Create a manpower log entry."""
        return await self._post(
            f"/rest/v1.0/projects/{project_id}/manpower_logs",
            {"manpower_log": data},
        )

    async def get_equipment_logs(self, project_id: int, log_date: str | None = None) -> list[dict]:
        """Get equipment log entries, optionally filtered by date (YYYY-MM-DD)."""
        params = {"per_page": 300}
        if log_date:
            params["log_date"] = log_date
        return await self._get(
            f"/rest/v1.0/projects/{project_id}/equipment_logs",
            params=params,
        )

    async def create_equipment_log(self, project_id: int, data: dict) -> dict:
        """Create an equipment log entry."""
        return await self._post(
            f"/rest/v1.0/projects/{project_id}/equipment_logs",
            {"equipment_log": data},
        )

    async def get_notes_logs(self, project_id: int, log_date: str | None = None) -> list[dict]:
        """Get notes log entries, optionally filtered by date (YYYY-MM-DD)."""
        params = {"per_page": 300}
        if log_date:
            params["log_date"] = log_date
        return await self._get(
            f"/rest/v1.0/projects/{project_id}/notes_logs",
            params=params,
        )

    async def create_notes_log(self, project_id: int, data: dict) -> dict:
        """Create a notes log entry."""
        return await self._post(
            f"/rest/v1.0/projects/{project_id}/notes_logs",
            {"notes_log": data},
        )
