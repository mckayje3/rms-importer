"""Sync service for comparing RMS data with baseline and generating sync plans."""
from typing import Optional
from datetime import date

from models.rms import RMSParseResult, RMSSubmittal, TransmittalReportEntry
from services.date_lookup import DateLookup
from models.mappings import map_status, map_status_for_config
from models.sync import (
    SyncMode,
    SyncPlan,
    CreateAction,
    UpdateAction,
    FlagAction,
    FileUploadAction,
    FieldChange,
    StoredSubmittal,
    BaselineData,
    BaselineInfo,
)
from database import baseline_store


# Fields to track for updates
TRACKED_FIELDS = [
    "title",
    "type",
    "status",
    "paragraph",
    "qa_code",
    "qc_code",
    "info",
    "government_received",
    "government_returned",
]


class SyncService:
    """Service for syncing RMS data to Procore."""

    def __init__(self, project_id: str, company_id: str, config: dict | None = None):
        self.project_id = project_id
        self.company_id = company_id
        self.config = config

    def get_baseline_info(self) -> BaselineInfo:
        """Get info about stored baseline."""
        baseline = baseline_store.get_baseline(self.project_id)

        if baseline:
            return BaselineInfo(
                has_baseline=True,
                last_sync=baseline["last_sync"],
                submittal_count=baseline["submittal_count"],
                file_count=baseline["file_count"],
            )
        else:
            return BaselineInfo(has_baseline=False)

    def analyze(
        self,
        rms_data: RMSParseResult,
        new_files: list[str] = None,
    ) -> SyncPlan:
        """
        Analyze RMS data against baseline and generate sync plan.

        If no baseline exists, returns a Full Migration plan.
        If baseline exists, returns an Incremental sync plan with only changes.
        """
        baseline = baseline_store.get_baseline(self.project_id)

        if not baseline:
            # No baseline - full migration
            return self._plan_full_migration(rms_data, new_files or [])
        else:
            # Has baseline - incremental sync
            baseline_data = self._parse_baseline_data(baseline["data"])
            return self._plan_incremental_sync(rms_data, baseline_data, new_files or [])

    def _plan_full_migration(
        self,
        rms_data: RMSParseResult,
        new_files: list[str],
    ) -> SyncPlan:
        """Create a plan to import everything (no baseline exists)."""
        plan = SyncPlan(mode=SyncMode.FULL_MIGRATION)

        # Build lookups from Transmittal Report
        date_lookup = DateLookup(rms_data.transmittal_report)
        info_lookup = self._build_info_lookup(rms_data)
        qa_lookup = self._build_qa_code_lookup(rms_data.transmittal_report)

        # All submittals need to be created
        for submittal in rms_data.submittals:
            key = f"{submittal.section}|{submittal.item_no}|0"
            info_key = f"{submittal.section}|{submittal.item_no}"
            qa_code = qa_lookup.get(key, submittal.qa_code)
            status = map_status_for_config(qa_code, submittal.status, self.config)

            plan.creates.append(CreateAction(
                key=key,
                section=submittal.section,
                item_no=submittal.item_no,
                revision=0,
                title=submittal.description,
                type=submittal.procore_type,
                paragraph=submittal.paragraph,
                info=info_lookup.get(info_key),
                qa_code=qa_code,
                status=status,
            ))

        # Add revisions from Transmittal Report
        # Group report entries by (section, item_no, revision) to deduplicate
        seen_revisions = set()
        for entry in rms_data.transmittal_report:
            if entry.revision > 0:
                rev_key = (entry.section, entry.item_no, entry.revision)
                if rev_key in seen_revisions:
                    continue
                seen_revisions.add(rev_key)

                orig = next(
                    (s for s in rms_data.submittals
                     if s.section == entry.section and s.item_no == entry.item_no),
                    None
                )
                if orig:
                    key = f"{entry.section}|{entry.item_no}|{entry.revision}"
                    info_key = f"{entry.section}|{entry.item_no}"
                    rev_qa = qa_lookup.get(key)
                    rev_status = map_status_for_config(rev_qa, None, self.config)
                    plan.creates.append(CreateAction(
                        key=key,
                        section=entry.section,
                        item_no=entry.item_no,
                        revision=entry.revision,
                        title=orig.description,
                        type=orig.procore_type,
                        paragraph=None,
                        info=info_lookup.get(info_key),
                        qa_code=rev_qa,
                        status=rev_status,
                    ))

        # All files need to be uploaded
        file_to_keys = self.map_files_to_submittals(new_files, rms_data)
        for filename, keys in file_to_keys.items():
            plan.file_uploads.append(FileUploadAction(
                filename=filename,
                submittal_keys=keys,
            ))

        return plan

    def _plan_incremental_sync(
        self,
        rms_data: RMSParseResult,
        baseline: BaselineData,
        new_files: list[str],
    ) -> SyncPlan:
        """Create a plan for incremental sync (baseline exists)."""
        plan = SyncPlan(mode=SyncMode.INCREMENTAL)

        # Build lookups
        date_lookup = DateLookup(rms_data.transmittal_report)
        info_lookup = self._build_info_lookup(rms_data)

        # Convert new RMS data to comparable format
        new_submittals = self._rms_to_stored_format(rms_data, date_lookup, info_lookup)

        baseline_keys = set(baseline.submittals.keys())
        new_keys = set(new_submittals.keys())

        # New submittals (in new but not baseline)
        for key in new_keys - baseline_keys:
            sub = new_submittals[key]
            plan.creates.append(CreateAction(
                key=key,
                section=sub.section,
                item_no=sub.item_no,
                revision=sub.revision,
                title=sub.title,
                type=sub.type,
                paragraph=sub.paragraph,
                info=sub.info,
                qa_code=sub.qa_code,
                status=sub.status,
            ))

        # Existing submittals - check for changes or missing Procore IDs
        for key in new_keys & baseline_keys:
            old = baseline.submittals[key]
            new = new_submittals[key]

            if not old.procore_id:
                # In baseline but never created in Procore — treat as create
                plan.creates.append(CreateAction(
                    key=key,
                    section=new.section,
                    item_no=new.item_no,
                    revision=new.revision,
                    title=new.title,
                    type=new.type,
                    paragraph=new.paragraph,
                    info=new.info,
                    qa_code=new.qa_code,
                    status=new.status,
                ))
                continue

            changes = self._diff_fields(old, new)
            if changes:
                plan.updates.append(UpdateAction(
                    key=key,
                    procore_id=old.procore_id,
                    changes=changes,
                ))

        # Deleted submittals (in baseline but not new) - flag for review
        for key in baseline_keys - new_keys:
            old = baseline.submittals[key]
            if old.procore_id:
                plan.flags.append(FlagAction(
                    key=key,
                    procore_id=old.procore_id,
                    reason="Removed from RMS export",
                ))

        # Files
        baseline_files = set(baseline.files.keys())
        new_file_set = set(new_files)

        # New files to upload
        file_to_keys = self.map_files_to_submittals(
            list(new_file_set - baseline_files),
            rms_data
        )
        for filename, keys in file_to_keys.items():
            plan.file_uploads.append(FileUploadAction(
                filename=filename,
                submittal_keys=keys,
            ))

        plan.files_already_uploaded = len(new_file_set & baseline_files)

        return plan

    def _diff_fields(
        self,
        old: StoredSubmittal,
        new: StoredSubmittal,
    ) -> list[FieldChange]:
        """Compare two submittals and return list of field changes."""
        changes = []

        for field in TRACKED_FIELDS:
            old_val = getattr(old, field, None)
            new_val = getattr(new, field, None)

            # Normalize for comparison
            old_str = self._normalize_value(old_val)
            new_str = self._normalize_value(new_val)

            if old_str != new_str:
                # Skip status changes when new value is None (no QA code = leave unchanged)
                if field == "status" and new_val is None:
                    continue
                changes.append(FieldChange(
                    field=field,
                    old_value=old_val,
                    new_value=new_val,
                ))

        return changes

    def _normalize_value(self, val) -> Optional[str]:
        """Normalize a value for comparison."""
        if val is None:
            return None
        if isinstance(val, date):
            return val.isoformat()
        return str(val).strip() if str(val).strip() else None

    def _build_info_lookup(self, rms_data: RMSParseResult) -> dict[str, str]:
        """Build lookup for Info field from assignments."""
        lookup = {}
        for assignment in rms_data.assignments:
            key = f"{assignment.section}|{assignment.item_no}"
            if assignment.info_only:
                lookup[key] = assignment.info_only
        return lookup

    def _build_qa_code_lookup(
        self,
        report_entries: list[TransmittalReportEntry],
    ) -> dict[str, str]:
        """Build lookup from submittal key to QA code from Transmittal Report."""
        lookup = {}
        for entry in report_entries:
            if entry.qa_code:
                lookup[entry.match_key] = entry.qa_code
        return lookup

    def _rms_to_stored_format(
        self,
        rms_data: RMSParseResult,
        date_lookup: DateLookup,
        info_lookup: dict[str, str],
    ) -> dict[str, StoredSubmittal]:
        """Convert RMS parsed data to StoredSubmittal format."""
        result = {}

        # Build QA code lookup from Transmittal Report (authoritative source)
        qa_lookup = self._build_qa_code_lookup(rms_data.transmittal_report)

        # Base submittals (revision 0)
        for sub in rms_data.submittals:
            key = f"{sub.section}|{sub.item_no}|0"
            info_key = f"{sub.section}|{sub.item_no}"

            dates = date_lookup.get(key)
            qa_code = qa_lookup.get(key, sub.qa_code)

            result[key] = StoredSubmittal(
                section=sub.section,
                item_no=sub.item_no,
                revision=0,
                title=sub.description,
                type=sub.procore_type,
                paragraph=sub.paragraph,
                qa_code=qa_code,
                qc_code=sub.qc_code,
                info=info_lookup.get(info_key),
                status=map_status_for_config(qa_code, sub.status, self.config),
                government_received=dates.government_received.isoformat() if dates and dates.government_received else None,
                government_returned=dates.government_returned.isoformat() if dates and dates.government_returned else None,
            )

        # Revisions from Transmittal Report
        seen_revisions = set()
        for entry in rms_data.transmittal_report:
            if entry.revision > 0:
                rev_key = (entry.section, entry.item_no, entry.revision)
                if rev_key in seen_revisions:
                    continue
                seen_revisions.add(rev_key)

                key = f"{entry.section}|{entry.item_no}|{entry.revision}"
                info_key = f"{entry.section}|{entry.item_no}"

                orig = next(
                    (s for s in rms_data.submittals
                     if s.section == entry.section and s.item_no == entry.item_no),
                    None
                )

                if orig:
                    dates = date_lookup.get(key)
                    rev_qa = qa_lookup.get(key)
                    result[key] = StoredSubmittal(
                        section=entry.section,
                        item_no=entry.item_no,
                        revision=entry.revision,
                        title=orig.description,
                        type=orig.procore_type,
                        paragraph=None,
                        qa_code=rev_qa,
                        qc_code=None,
                        info=info_lookup.get(info_key),
                        status=map_status_for_config(rev_qa, None, self.config),
                        government_received=dates.government_received.isoformat() if dates and dates.government_received else None,
                        government_returned=dates.government_returned.isoformat() if dates and dates.government_returned else None,
                    )

        return result

    def map_files_to_submittals(
        self,
        filenames: list[str],
        rms_data: RMSParseResult,
    ) -> dict[str, list[str]]:
        """Map filenames to submittal keys based on naming convention."""
        import re

        result = {}

        # Build transmittal number to item numbers lookup from Report
        # Key: "section-transNum" or "section-transNum.rev" -> list of item numbers
        trans_lookup: dict[str, list[int]] = {}
        for entry in rms_data.transmittal_report:
            if entry.revision > 0:
                full_key = f"{entry.section}-{entry.transmittal_no}.{entry.revision}"
            else:
                full_key = f"{entry.section}-{entry.transmittal_no}"
            if full_key not in trans_lookup:
                trans_lookup[full_key] = []
            if entry.item_no not in trans_lookup[full_key]:
                trans_lookup[full_key].append(entry.item_no)

        for filename in filenames:
            # Pattern: Transmittal {Section}-{TransNum}.{Rev} - {Description}.pdf
            match = re.match(
                r"^Transmittal\s+(.+?)-(\d+)(?:\.(\d+))?\s*-\s*",
                filename
            )
            if match:
                section = match.group(1).strip()
                trans_num = match.group(2)
                revision = int(match.group(3)) if match.group(3) else 0

                if revision > 0:
                    full_trans_num = f"{section}-{trans_num}.{revision}"
                else:
                    full_trans_num = f"{section}-{trans_num}"

                item_numbers = trans_lookup.get(full_trans_num)
                if item_numbers:
                    keys = [
                        f"{section}|{item}|{revision}"
                        for item in item_numbers
                    ]
                    result[filename] = keys
                else:
                    # Fallback: assume trans_num is the item number
                    key = f"{section}|{trans_num}|{revision}"
                    result[filename] = [key]

        return result

    def _parse_baseline_data(self, data: dict) -> BaselineData:
        """Parse baseline data from stored JSON."""
        submittals = {}
        for key, sub_dict in data.get("submittals", {}).items():
            submittals[key] = StoredSubmittal(**sub_dict)

        files = {}
        for key, file_dict in data.get("files", {}).items():
            from models.sync import StoredFile
            files[key] = StoredFile(**file_dict)

        return BaselineData(submittals=submittals, files=files)

    def save_baseline(
        self,
        rms_data: RMSParseResult,
        procore_ids: dict[str, int],
        uploaded_files: dict[str, int],
    ) -> None:
        """Save a new baseline after successful sync."""
        date_lookup = DateLookup(rms_data.transmittal_report)
        info_lookup = self._build_info_lookup(rms_data)

        submittals = self._rms_to_stored_format(rms_data, date_lookup, info_lookup)

        # Add Procore IDs
        for key, procore_id in procore_ids.items():
            if key in submittals:
                submittals[key].procore_id = procore_id

        # Convert to dict for storage
        data = {
            "submittals": {k: v.model_dump() for k, v in submittals.items()},
            "files": {
                filename: {
                    "filename": filename,
                    "submittal_key": "",  # TODO: track which submittal
                    "uploaded": True,
                    "procore_file_id": file_id,
                }
                for filename, file_id in uploaded_files.items()
            },
        }

        baseline_store.save_baseline(
            self.project_id,
            self.company_id,
            data,
        )

    def update_baseline_with_results(
        self,
        rms_data: RMSParseResult,
        creates: dict[str, int],  # key -> procore_id
        updates: list[str],  # keys that were updated
        uploaded_files: dict[str, int],  # filename -> file_id
    ) -> None:
        """Update existing baseline after incremental sync."""
        baseline = baseline_store.get_baseline(self.project_id)
        if not baseline:
            return

        data = baseline["data"]

        # Build full submittal data from RMS for new creates
        date_lookup = DateLookup(rms_data.transmittal_report)
        info_lookup = self._build_info_lookup(rms_data)
        new_submittals = self._rms_to_stored_format(rms_data, date_lookup, info_lookup)

        # Add new submittals with their Procore IDs
        for key, procore_id in creates.items():
            if key in new_submittals:
                sub = new_submittals[key]
                sub.procore_id = procore_id
                data["submittals"][key] = sub.model_dump()
            elif key not in data["submittals"]:
                # Fallback: minimal data
                parts = key.split("|")
                data["submittals"][key] = {
                    "section": parts[0],
                    "item_no": int(parts[1]),
                    "revision": int(parts[2]),
                    "title": "",
                    "procore_id": procore_id,
                }
            else:
                data["submittals"][key]["procore_id"] = procore_id

        # Update existing submittals with new field values
        for key in updates:
            if key in new_submittals and key in data["submittals"]:
                sub = new_submittals[key]
                sub.procore_id = data["submittals"][key].get("procore_id")
                data["submittals"][key] = sub.model_dump()

        # Add uploaded files
        for filename, file_id in uploaded_files.items():
            data["files"][filename] = {
                "filename": filename,
                "uploaded": True,
                "procore_file_id": file_id,
            }

        baseline_store.save_baseline(
            self.project_id,
            self.company_id,
            data,
        )
