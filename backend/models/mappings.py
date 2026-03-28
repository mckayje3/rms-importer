"""Field mappings between RMS and Procore."""

# Status mapping mode: "qa_code" or "rms_status"
# QA Code -> Procore status (default)
QA_STATUS_MAP = {
    "a": "closed",
    "b": "closed",
    "c": "open",
    "d": "open",
    "e": "open",
    "f": "closed",
    "g": "open",
    "x": "closed",
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


def map_status(qa_code: str | None) -> str | None:
    """Map QA code to Procore status (default/qa_code mode).

    Args:
        qa_code: QA code from RMS (e.g., "A", "B", "C", "D", "E", "F", "G", "X")

    Returns:
        Procore status ("open" or "closed") or None if no QA code
    """
    if not qa_code:
        return None

    normalized = qa_code.strip().lower()
    return QA_STATUS_MAP.get(normalized)


def map_status_rms(rms_status: str | None) -> str | None:
    """Map RMS status to Procore status (rms_status mode).

    Args:
        rms_status: Status from RMS (e.g., "Outstanding", "Complete", "In Review")

    Returns:
        Procore status (e.g., "Draft", "Closed", "Open") or original if no mapping
    """
    if not rms_status:
        return None

    normalized = rms_status.strip().lower()
    return RMS_STATUS_MAP.get(normalized, rms_status)


def map_status_for_config(
    qa_code: str | None,
    rms_status: str | None,
    config: dict | None = None,
) -> str | None:
    """Map status using the project's configured mode.

    Args:
        qa_code: QA code from RMS
        rms_status: RMS status field
        config: Project config dict (with status_mode and status_map keys)

    Returns:
        Procore status or None if source value is missing
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
        return status_map.get(normalized, rms_status)
    else:
        # qa_code mode
        if not qa_code:
            return None
        normalized = qa_code.strip().lower()
        return status_map.get(normalized)


def map_sd_to_type(sd_no: str | None) -> str | None:
    """Map SD number to Procore submittal type.

    Args:
        sd_no: SD number from RMS (e.g., "01", "02", "1", "2")

    Returns:
        Procore type (e.g., "SD-01: PRECON SUBMTL") or None if not found
    """
    if not sd_no:
        return None

    # Normalize: remove spaces, pad to 2 digits
    normalized = sd_no.strip().zfill(2)
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
