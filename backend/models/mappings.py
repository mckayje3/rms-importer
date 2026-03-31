"""Field mappings between RMS and Procore."""

# Status mapping mode: "qa_code" or "rms_status"
# QA Code -> Procore status with name and ID
# These are the Dobbins custom statuses configured in Procore Company Admin
QA_STATUS_MAP = {
    "a": {"name": "A - Approved as submitted", "id": 598134326473636},
    "b": {"name": "B - Approved, except as noted on drawings", "id": 598134326473637},
    "c": {"name": "C - Approved, except as noted; resubmission required", "id": 598134326473638},
    "d": {"name": "D - Returned by separate correspondence", "id": 598134326473639},
    "e": {"name": "E - Dissapproved (see attached)", "id": 598134326473640},
    "f": {"name": "F - Receipt acknowledged", "id": 598134326473641},
    "g": {"name": "G - Other (specify)", "id": 598134326473642},
    "x": {"name": "X - Receipt acknowledged, does not comply with requirements", "id": 598134326473643},
}

# RMS Status -> Procore status (legacy)
RMS_STATUS_MAP = {
    "outstanding": "Draft",
    "complete": "Closed",
    "in review": "Open",
}

# Type mapping: SD No -> Procore Type
SD_TYPE_MAP = {
    "01": "SD-01: PRECON SUBMTL",
    "02": "SD-02: SHOP DRAWINGS",
    "03": "SD-03: PRODUCT DATA",
    "04": "SD-04: SAMPLES",
    "05": "SD-05: DESIGN DATA",
    "06": "SD-06: TEST REPORTS",
    "07": "SD-07: CERTIFICATES",
    "08": "SD-08: MFRS INSTR",
    "09": "SD-09: MFRS FLD REPT",
    "10": "SD-10: O&M DATA",
    "11": "SD-11: CLOSEOUT SUBMTL",
}


def _resolve_status_entry(entry) -> dict | None:
    """Resolve a status map entry to a dict with 'name' and optionally 'id'.

    Handles both new format (dict with name/id) and legacy format (plain string).
    """
    if entry is None:
        return None
    if isinstance(entry, dict):
        return entry
    # Legacy plain string format (e.g., "open", "closed")
    return {"name": str(entry)}


def map_status(qa_code: str | None) -> str | None:
    """Map QA code to Procore status name (default/qa_code mode).

    Returns:
        Procore status name or None if no QA code
    """
    if not qa_code:
        return None

    normalized = qa_code.strip().lower()
    entry = QA_STATUS_MAP.get(normalized)
    return _resolve_status_entry(entry).get("name") if entry else None


def map_status_rms(rms_status: str | None) -> str | None:
    """Map RMS status to Procore status name (rms_status mode).

    Returns:
        Procore status name or None if no mapping
    """
    if not rms_status:
        return None

    normalized = rms_status.strip().lower()
    entry = RMS_STATUS_MAP.get(normalized, rms_status)
    resolved = _resolve_status_entry(entry)
    return resolved.get("name") if resolved else None


def map_status_for_config(
    qa_code: str | None,
    rms_status: str | None,
    config: dict | None = None,
) -> str | None:
    """Map status using the project's configured mode.

    Returns the status name string for storage/comparison.
    Use get_status_id_for_qa_code() to get the numeric ID for Procore API calls.
    """
    mode = "qa_code"
    status_map = QA_STATUS_MAP

    if config:
        mode = config.get("status_mode", "qa_code")
        if "status_map" in config:
            status_map = config["status_map"]

    if mode == "rms_status":
        if not rms_status:
            return None
        normalized = rms_status.strip().lower()
        entry = status_map.get(normalized, rms_status)
        resolved = _resolve_status_entry(entry)
        return resolved.get("name") if resolved else None
    else:
        # qa_code mode
        if not qa_code:
            return None
        normalized = qa_code.strip().lower()
        entry = status_map.get(normalized)
        return _resolve_status_entry(entry).get("name") if entry else None


def get_status_id(status_name: str | None, config: dict | None = None) -> int | None:
    """Look up the Procore status_id for a given status name.

    Searches the configured status map for a matching name and returns its ID.
    Used when building Procore API payloads that require status_id.
    """
    if not status_name:
        return None

    status_map = QA_STATUS_MAP
    if config and "status_map" in config:
        status_map = config["status_map"]

    for entry in status_map.values():
        resolved = _resolve_status_entry(entry)
        if resolved and resolved.get("name") == status_name and "id" in resolved:
            return resolved["id"]

    return None


def map_sd_to_type(sd_no: str | None) -> str | None:
    """Map SD number to Procore submittal type.

    Args:
        sd_no: SD number from RMS (e.g., "01", "02", "1", "2")

    Returns:
        Procore type (e.g., "SD-01: PRECON SUBMTL") or None if not found
    """
    if not sd_no:
        return None

    # Normalize: strip whitespace, remove ".0" suffix from Excel float parsing, pad to 2 digits
    normalized = sd_no.strip()
    if normalized.endswith(".0"):
        normalized = normalized[:-2]
    normalized = normalized.zfill(2)
    return SD_TYPE_MAP.get(normalized)


def get_status_map(config: dict | None = None) -> dict:
    """Get status mapping for the configured mode, using project config if available."""
    if config and "status_map" in config:
        return config["status_map"]
    mode = config.get("status_mode", "qa_code") if config else "qa_code"
    return QA_STATUS_MAP if mode == "qa_code" else RMS_STATUS_MAP


def get_sd_type_map(config: dict | None = None) -> dict:
    """Get SD type mapping, using project config if available."""
    if config and "sd_type_map" in config:
        return config["sd_type_map"]
    return SD_TYPE_MAP
