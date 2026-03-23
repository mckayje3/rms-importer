"""Field mappings between RMS and Procore."""

# Status mapping: RMS -> Procore
STATUS_MAP = {
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


def map_status(rms_status: str | None) -> str | None:
    """Map RMS status to Procore status.

    Args:
        rms_status: Status from RMS (e.g., "Outstanding", "Complete", "In Review")

    Returns:
        Procore status (e.g., "Draft", "Closed", "Open") or original if no mapping
    """
    if not rms_status:
        return None

    normalized = rms_status.strip().lower()
    return STATUS_MAP.get(normalized, rms_status)


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
