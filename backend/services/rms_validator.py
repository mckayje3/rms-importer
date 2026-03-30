"""RMS file validation service - validates uploads before parsing."""
import io
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd


class FileType(Enum):
    """RMS file types."""
    SUBMITTAL_REGISTER = "submittal_register"
    SUBMITTAL_ASSIGNMENTS = "submittal_assignments"
    TRANSMITTAL_LOG = "transmittal_log"
    TRANSMITTAL_REPORT = "transmittal_report"


class Severity(Enum):
    """Validation issue severity."""
    ERROR = "error"      # Blocks import
    WARNING = "warning"  # Import can proceed but may have issues


@dataclass
class ValidationIssue:
    """A single validation issue."""
    severity: Severity
    message: str
    file_type: Optional[FileType] = None
    row: Optional[int] = None  # 1-indexed row number (as seen in Excel)
    column: Optional[str] = None
    suggestion: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "message": self.message,
            "file_type": self.file_type.value if self.file_type else None,
            "row": self.row,
            "column": self.column,
            "suggestion": self.suggestion,
        }


@dataclass
class ValidationResult:
    """Result of validating RMS files."""
    is_valid: bool  # True if no errors (warnings OK)
    issues: list[ValidationIssue] = field(default_factory=list)

    # Summary stats
    row_counts: dict[str, int] = field(default_factory=dict)
    column_info: dict[str, list[str]] = field(default_factory=dict)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
            "row_counts": self.row_counts,
            "column_info": self.column_info,
        }


class RMSValidator:
    """
    Validates RMS export files before parsing.

    Provides detailed, actionable error messages to help users
    fix issues with their exports.
    """

    # Expected columns for each file type
    # Format: (column_name, required, description)
    REGISTER_SCHEMA = [
        ("section", True, "Spec section number (e.g., '03 30 00')"),
        ("item no", True, "Submittal item number"),
        ("sd no", True, "SD type number (01-11)"),
        ("description", True, "Submittal description/title"),
        ("date in", False, "Date submittal received"),
        ("qc code", False, "QC review code (A/B/C/D)"),
        ("date out", False, "Date submittal returned"),
        ("qa code", False, "QA review code (A-G, X)"),
        ("status", False, "Submittal status"),
    ]

    ASSIGNMENTS_SCHEMA = [
        ("section", True, "Spec section number"),
        ("item no", True, "Submittal item number"),
        ("description", True, "Submittal description"),
        ("sd no", False, "SD type number"),
        ("info only", False, "Info type (GA/FIO/S)"),
        ("required for activity", False, "P6 activity code"),
    ]

    TRANSMITTAL_SCHEMA = [
        ("section", True, "Spec section number"),
        ("transmittal number", True, "Transmittal ID with optional revision (.1, .2)"),
        ("submittal items included on transmittal", True, "Item numbers (comma-separated)"),
        ("contractor prepared", False, "Date contractor prepared"),
        ("government received", False, "Date government received"),
        ("government returned", False, "Date government returned"),
        ("contractor received", False, "Date contractor received"),
    ]

    # Common column name variations/typos and their corrections
    COLUMN_ALIASES = {
        # Submittal Register
        "spec section": "section",
        "spec_section": "section",
        "specification": "section",
        "item": "item no",
        "item_no": "item no",
        "item number": "item no",
        "itemnumber": "item no",
        "sd": "sd no",
        "sd_no": "sd no",
        "sd number": "sd no",
        "sdno": "sd no",
        "title": "description",
        "name": "description",
        "submittal description": "description",
        "qc": "qc code",
        "qccode": "qc code",
        "qc_code": "qc code",
        "qa": "qa code",
        "qacode": "qa code",
        "qa_code": "qa code",

        # Transmittal Log
        "transmittal": "transmittal number",
        "transmittal no": "transmittal number",
        "transmittal_number": "transmittal number",
        "items": "submittal items included on transmittal",
        "submittal items": "submittal items included on transmittal",
        "item numbers": "submittal items included on transmittal",
        "contractor prep": "contractor prepared",
        "govt received": "government received",
        "gov received": "government received",
        "govt returned": "government returned",
        "gov returned": "government returned",
        "contractor recv": "contractor received",

        # Assignments
        "info": "info only",
        "info_only": "info only",
        "activity": "required for activity",
        "activity code": "required for activity",
    }

    # Valid values for enum-like fields
    VALID_QC_CODES = {"A", "B", "C", "D", ""}
    VALID_QA_CODES = {"A", "B", "C", "D", "E", "F", "G", "X", ""}
    VALID_INFO_CODES = {"GA", "FIO", "S", "DA/CR", ""}

    def validate_all(
        self,
        register_bytes: bytes,
        assignments_bytes: Optional[bytes] = None,
        transmittal_bytes: Optional[bytes] = None,
        transmittal_report_bytes: Optional[bytes] = None,
    ) -> ValidationResult:
        """
        Validate all RMS files.

        Only register_bytes is required. Other files are optional.
        Returns ValidationResult with is_valid=True if no errors.
        """
        issues = []
        row_counts = {}
        column_info = {}

        # Validate register (required)
        reg_issues, reg_df = self._validate_file(
            register_bytes, FileType.SUBMITTAL_REGISTER, self.REGISTER_SCHEMA
        )
        issues.extend(reg_issues)
        if reg_df is not None:
            row_counts["submittal_register"] = len(reg_df)
            column_info["submittal_register"] = list(reg_df.columns)
            # Additional register-specific validation
            issues.extend(self._validate_register_data(reg_df))

        # Validate assignments (optional)
        assign_df = None
        if assignments_bytes:
            assign_issues, assign_df = self._validate_file(
                assignments_bytes, FileType.SUBMITTAL_ASSIGNMENTS, self.ASSIGNMENTS_SCHEMA
            )
            issues.extend(assign_issues)
            if assign_df is not None:
                row_counts["submittal_assignments"] = len(assign_df)
                column_info["submittal_assignments"] = list(assign_df.columns)
                # Additional assignments-specific validation
                issues.extend(self._validate_assignments_data(assign_df))

        # Validate transmittal log (optional)
        trans_df = None
        if transmittal_bytes:
            trans_issues, trans_df = self._validate_file(
                transmittal_bytes, FileType.TRANSMITTAL_LOG, self.TRANSMITTAL_SCHEMA
            )
            issues.extend(trans_issues)
            if trans_df is not None:
                row_counts["transmittal_log"] = len(trans_df)
                column_info["transmittal_log"] = list(trans_df.columns)
                # Additional transmittal-specific validation
                issues.extend(self._validate_transmittal_data(trans_df))

        # Validate Transmittal Report (optional)
        if transmittal_report_bytes:
            report_issues, report_count = self._validate_transmittal_report(
                transmittal_report_bytes
            )
            issues.extend(report_issues)
            if report_count is not None:
                row_counts["transmittal_report"] = report_count

        # Cross-file validation (only if we have at least register + one other file)
        if reg_df is not None:
            issues.extend(self._validate_cross_references(reg_df, assign_df, trans_df))

        # Determine overall validity (no errors = valid)
        is_valid = not any(i.severity == Severity.ERROR for i in issues)

        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            row_counts=row_counts,
            column_info=column_info,
        )

    def _validate_file(
        self,
        file_bytes: bytes,
        file_type: FileType,
        schema: list[tuple[str, bool, str]],
    ) -> tuple[list[ValidationIssue], Optional[pd.DataFrame]]:
        """
        Validate a single file's format and columns.

        Returns (issues, dataframe) - dataframe is None if file couldn't be read.
        """
        issues = []
        file_name = file_type.value.replace("_", " ").title()

        # Try to read the file
        try:
            df = pd.read_excel(io.BytesIO(file_bytes))
        except Exception as e:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Cannot read {file_name} file: {str(e)}",
                file_type=file_type,
                suggestion="Ensure the file is a valid Excel file (.xlsx or .xls)",
            ))
            return issues, None

        # Check if file is empty
        if df.empty:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"{file_name} file is empty",
                file_type=file_type,
                suggestion="Export data from RMS and try again",
            ))
            return issues, None

        # Normalize column names
        original_columns = list(df.columns)
        df.columns = [str(c).lower().strip() for c in df.columns]

        # Apply column aliases
        column_mapping = {}
        for i, col in enumerate(df.columns):
            if col in self.COLUMN_ALIASES:
                column_mapping[col] = self.COLUMN_ALIASES[col]

        if column_mapping:
            df = df.rename(columns=column_mapping)
            for old, new in column_mapping.items():
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    message=f"Column '{old}' interpreted as '{new}'",
                    file_type=file_type,
                    column=old,
                ))

        # Check required columns
        required_cols = [col for col, req, _ in schema if req]
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            # Try to suggest corrections
            for missing in missing_cols:
                suggestion = self._suggest_column(missing, df.columns)
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Missing required column: '{missing}'",
                    file_type=file_type,
                    column=missing,
                    suggestion=suggestion,
                ))
            return issues, None

        # Check optional columns (warnings only)
        optional_cols = [col for col, req, desc in schema if not req]
        missing_optional = [col for col in optional_cols if col not in df.columns]

        for col in missing_optional:
            desc = next((d for c, _, d in schema if c == col), "")
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"Optional column not found: '{col}'",
                file_type=file_type,
                column=col,
                suggestion=f"This column provides: {desc}. Data will be imported without it.",
            ))

        # Check for unrecognized columns (informational)
        expected_cols = [col for col, _, _ in schema]
        extra_cols = [col for col in df.columns if col not in expected_cols]
        if extra_cols:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"Unrecognized columns will be ignored: {', '.join(extra_cols)}",
                file_type=file_type,
            ))

        return issues, df

    def _validate_register_data(self, df: pd.DataFrame) -> list[ValidationIssue]:
        """Validate Submittal Register data quality."""
        issues = []

        # Check for empty required fields
        for col in ["section", "item no", "description"]:
            if col in df.columns:
                empty_rows = df[df[col].isna() | (df[col].astype(str).str.strip() == "")]
                if len(empty_rows) > 0:
                    row_nums = [i + 2 for i in empty_rows.index[:5]]  # Excel is 1-indexed + header
                    more = f" (and {len(empty_rows) - 5} more)" if len(empty_rows) > 5 else ""
                    issues.append(ValidationIssue(
                        severity=Severity.WARNING,
                        message=f"Empty '{col}' in {len(empty_rows)} rows: {row_nums}{more}",
                        file_type=FileType.SUBMITTAL_REGISTER,
                        column=col,
                    ))

        # Validate QC codes
        if "qc code" in df.columns:
            invalid_qc = df[~df["qc code"].fillna("").astype(str).str.upper().str.strip().isin(self.VALID_QC_CODES)]
            if len(invalid_qc) > 0:
                bad_values = invalid_qc["qc code"].unique()[:5]
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    message=f"Invalid QC codes found: {list(bad_values)}",
                    file_type=FileType.SUBMITTAL_REGISTER,
                    column="qc code",
                    suggestion="Valid QC codes are: A, B, C, D",
                ))

        # Validate QA codes
        if "qa code" in df.columns:
            invalid_qa = df[~df["qa code"].fillna("").astype(str).str.upper().str.strip().isin(self.VALID_QA_CODES)]
            if len(invalid_qa) > 0:
                bad_values = invalid_qa["qa code"].unique()[:5]
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    message=f"Invalid QA codes found: {list(bad_values)}",
                    file_type=FileType.SUBMITTAL_REGISTER,
                    column="qa code",
                    suggestion="Valid QA codes are: A, B, C, D, E, F, G, X",
                ))

        # Check item numbers are numeric
        if "item no" in df.columns:
            non_numeric = df[pd.to_numeric(df["item no"], errors="coerce").isna() & df["item no"].notna()]
            if len(non_numeric) > 0:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Non-numeric item numbers in {len(non_numeric)} rows",
                    file_type=FileType.SUBMITTAL_REGISTER,
                    column="item no",
                    suggestion="Item numbers must be integers",
                ))

        return issues

    def _validate_assignments_data(self, df: pd.DataFrame) -> list[ValidationIssue]:
        """Validate Submittal Assignments data quality."""
        issues = []

        # Validate Info codes
        if "info only" in df.columns:
            invalid_info = df[~df["info only"].fillna("").astype(str).str.upper().str.strip().isin(self.VALID_INFO_CODES)]
            if len(invalid_info) > 0:
                bad_values = invalid_info["info only"].unique()[:5]
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    message=f"Invalid Info codes found: {list(bad_values)}",
                    file_type=FileType.SUBMITTAL_ASSIGNMENTS,
                    column="info only",
                    suggestion="Valid Info codes are: GA, FIO, S",
                ))

        return issues

    def _validate_transmittal_data(self, df: pd.DataFrame) -> list[ValidationIssue]:
        """Validate Transmittal Log data quality."""
        issues = []
        items_col = "submittal items included on transmittal"

        # Check item numbers format
        if items_col in df.columns:
            for idx, row in df.iterrows():
                items_str = str(row.get(items_col, ""))
                if items_str and items_str.lower() != "nan":
                    # Should be comma-separated integers
                    parts = [p.strip() for p in items_str.split(",")]
                    non_numeric = [p for p in parts if p and not p.isdigit()]
                    if non_numeric:
                        issues.append(ValidationIssue(
                            severity=Severity.WARNING,
                            message=f"Non-numeric item numbers: {non_numeric}",
                            file_type=FileType.TRANSMITTAL_LOG,
                            row=idx + 2,
                            column=items_col,
                            suggestion="Item numbers should be comma-separated integers (e.g., '1,2,3')",
                        ))
                        break  # Only report first occurrence

        # Check transmittal number format
        if "transmittal number" in df.columns:
            import re
            for idx, row in df.iterrows():
                trans_num = str(row.get("transmittal number", ""))
                if trans_num and trans_num.lower() != "nan":
                    # Should match pattern like "01 50 00-1" or "01 50 00-1.2"
                    if not re.match(r"[\d\s\.]+-\d+(\.\d+)?$", trans_num):
                        issues.append(ValidationIssue(
                            severity=Severity.WARNING,
                            message=f"Unexpected transmittal number format: '{trans_num}'",
                            file_type=FileType.TRANSMITTAL_LOG,
                            row=idx + 2,
                            column="transmittal number",
                            suggestion="Expected format: 'XX XX XX-N' or 'XX XX XX-N.R' for revisions",
                        ))
                        break  # Only report first occurrence

        return issues

    def _validate_transmittal_report(
        self,
        file_bytes: bytes,
    ) -> tuple[list[ValidationIssue], Optional[int]]:
        """
        Validate Transmittal Report file (CSV or Excel).

        The report has a hierarchical format with transmittal header rows
        and item data rows. Validates structure and content.

        Returns (issues, entry_count).
        """
        import re

        issues = []
        file_type = FileType.TRANSMITTAL_REPORT
        header_re = re.compile(
            r"^Transmittal No\s+(.+?)-(\d+)(?:\.(\d+))?\s"
        )

        # Detect format: try CSV first, then Excel
        is_csv = False
        try:
            text = file_bytes.decode("utf-8-sig", errors="replace")  # utf-8-sig strips BOM
            if text.lstrip().startswith("Transmittal Log") or "Transmittal No " in text[:2000]:
                is_csv = True
        except Exception:
            pass

        if is_csv:
            return self._validate_transmittal_report_csv(text, header_re)
        else:
            return self._validate_transmittal_report_xlsx(file_bytes, header_re)

    # Expected CSV column headers for Transmittal Report (row 5)
    TRANSMITTAL_REPORT_COLUMNS = [
        "item no.", "description of submittal", "type of submittal",
        "office", "reviewer", "classification", "qa code",
    ]

    def _validate_transmittal_report_csv(
        self,
        text: str,
        header_re,
    ) -> tuple[list[ValidationIssue], Optional[int]]:
        """
        Validate CSV-format Transmittal Report.

        Expected structure:
          Row 1: "Transmittal Log,{date}"
          Row 2: Project description
          Row 3: Organization
          Row 4: Project code
          Row 5: Column headers (Item No., Description of Submittal, Type of Submittal,
                                  Office, Reviewer, Classification, QA Code)
          Row 6+: Alternating transmittal headers and item data rows
            - Header: "Transmittal No {Section}-{Num}[.{Rev}]  Date In: ...  Review Date: ...  Date Out: ..."
            - Item: item_no, description, type, office, reviewer, classification, qa_code
              (6 columns if QA code is blank, 7 if present)
        """
        import csv

        issues = []
        file_type = FileType.TRANSMITTAL_REPORT
        entry_count = 0
        transmittal_count = 0
        invalid_qa_codes = []
        invalid_classifications = []

        try:
            reader = csv.reader(text.splitlines())
            rows = list(reader)
        except Exception as e:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Cannot read Transmittal Report CSV: {str(e)}",
                file_type=file_type,
                suggestion="Ensure the file is a valid CSV file",
            ))
            return issues, None

        if len(rows) < 6:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="Transmittal Report is too short (expected at least 6 rows: header info + column names + data)",
                file_type=file_type,
                suggestion="Export the Transmittal Report from RMS and try again",
            ))
            return issues, None

        # Validate row 1: should start with "Transmittal Log"
        if not rows[0] or not rows[0][0].strip().startswith("Transmittal Log"):
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"Row 1 should start with 'Transmittal Log', found: '{rows[0][0].strip() if rows[0] else '(empty)' }'",
                file_type=file_type,
                row=1,
                suggestion="This may not be a valid Transmittal Report CSV export from RMS",
            ))

        # Validate row 5: column headers
        if len(rows) >= 5 and rows[4]:
            actual_headers = [c.strip().lower() for c in rows[4]]
            expected = self.TRANSMITTAL_REPORT_COLUMNS
            if len(actual_headers) < 6:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Column header row (row 5) has {len(actual_headers)} columns, expected 7: {', '.join(expected)}",
                    file_type=file_type,
                    row=5,
                    suggestion="Ensure the file has the standard Transmittal Report columns",
                ))
            else:
                # Check that key columns match
                mismatches = []
                for i, exp in enumerate(expected):
                    if i < len(actual_headers) and actual_headers[i] != exp:
                        mismatches.append(f"column {i+1}: expected '{exp}', got '{actual_headers[i]}'")
                if mismatches:
                    issues.append(ValidationIssue(
                        severity=Severity.WARNING,
                        message=f"Column header mismatches: {'; '.join(mismatches)}",
                        file_type=file_type,
                        row=5,
                        suggestion=f"Expected columns: {', '.join(expected)}",
                    ))

        # Scan data rows (starting from row 6)
        current_section = None
        for row_idx, row in enumerate(rows[5:], start=6):
            if not row:
                continue

            col1 = row[0].strip()
            header_match = header_re.match(col1)

            if header_match:
                transmittal_count += 1
                current_section = header_match.group(1).strip()
                continue

            # Item data row: starts with a number, under a transmittal header
            if col1.isdigit() and current_section is not None:
                entry_count += 1

                # Validate column count (6 = no QA code, 7 = with QA code)
                if len(row) < 6:
                    issues.append(ValidationIssue(
                        severity=Severity.WARNING,
                        message=f"Row {row_idx} has only {len(row)} columns (expected 6-7)",
                        file_type=file_type,
                        row=row_idx,
                    ))
                    continue

                # Validate Classification (column 5)
                if len(row) > 5 and row[5].strip():
                    classification = row[5].strip().upper()
                    if classification not in self.VALID_INFO_CODES:
                        invalid_classifications.append((row_idx, classification))

                # Validate QA code (column 6)
                if len(row) > 6 and row[6].strip():
                    qa = row[6].strip().upper()
                    if qa not in self.VALID_QA_CODES:
                        invalid_qa_codes.append((row_idx, qa))

        # Report invalid QA codes (show up to 5)
        if invalid_qa_codes:
            examples = ", ".join(f"'{v}' (row {r})" for r, v in invalid_qa_codes[:5])
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"Found {len(invalid_qa_codes)} invalid QA code(s): {examples}",
                file_type=file_type,
                column="qa_code",
                suggestion="Valid QA codes are: A, B, C, D, E, F, G, X",
            ))

        # Report invalid classifications (show up to 5)
        if invalid_classifications:
            examples = ", ".join(f"'{v}' (row {r})" for r, v in invalid_classifications[:5])
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"Found {len(invalid_classifications)} invalid classification(s): {examples}",
                file_type=file_type,
                column="classification",
                suggestion="Valid classifications are: GA, FIO, S",
            ))

        if transmittal_count == 0:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="No transmittal headers found (expected 'Transmittal No ...')",
                file_type=file_type,
                suggestion="This doesn't appear to be a Transmittal Report. Check that you exported the correct report from RMS.",
            ))
            return issues, None

        if entry_count == 0:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"Found {transmittal_count} transmittal headers but no item data rows",
                file_type=file_type,
            ))

        return issues, entry_count

    def _validate_transmittal_report_xlsx(
        self,
        file_bytes: bytes,
        header_re,
    ) -> tuple[list[ValidationIssue], Optional[int]]:
        """Validate Excel-format Transmittal Report (legacy format)."""
        import openpyxl

        issues = []
        file_type = FileType.TRANSMITTAL_REPORT
        entry_count = 0
        transmittal_count = 0

        # Warn that CSV is the expected format
        issues.append(ValidationIssue(
            severity=Severity.WARNING,
            message="Transmittal Report is in Excel format. The expected format is CSV.",
            file_type=file_type,
            suggestion="Export the Transmittal Report from RMS as CSV (7 columns: Item No., Description, Type, Office, Reviewer, Classification, QA Code)",
        ))

        try:
            wb = openpyxl.load_workbook(
                io.BytesIO(file_bytes), read_only=True, data_only=True
            )
            ws = wb.active
        except Exception as e:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Cannot read Transmittal Report file: {str(e)}",
                file_type=file_type,
                suggestion="Ensure the file is a valid Excel file (.xlsx or .xls)",
            ))
            return issues, None

        current_section = None
        for row in ws.iter_rows(min_row=13, max_col=14, values_only=True):
            col1 = str(row[0]).strip() if row[0] else ""
            if not col1:
                continue

            header_match = header_re.match(col1)
            if header_match:
                transmittal_count += 1
                current_section = header_match.group(1).strip()
                continue

            if col1.isdigit() and current_section is not None:
                entry_count += 1
                # Validate QA code (column 14, index 13)
                if row[13]:
                    qa = str(row[13]).strip().upper()
                    if qa and qa != "NONE" and qa not in self.VALID_QA_CODES:
                        issues.append(ValidationIssue(
                            severity=Severity.WARNING,
                            message=f"Invalid QA code '{qa}' in Transmittal Report",
                            file_type=file_type,
                            column="qa_code",
                            suggestion="Valid QA codes are: A, B, C, D, E, F, G, X",
                        ))
                        break  # Only report first

                # Validate Classification (column 13, index 12)
                if row[12]:
                    classification = str(row[12]).strip().upper()
                    if classification and classification != "NONE" and classification not in self.VALID_INFO_CODES:
                        issues.append(ValidationIssue(
                            severity=Severity.WARNING,
                            message=f"Invalid Classification '{classification}' in Transmittal Report",
                            file_type=file_type,
                            column="classification",
                            suggestion="Valid classifications are: GA, FIO, S",
                        ))
                        break  # Only report first

        wb.close()

        if transmittal_count == 0:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="No transmittal headers found (expected 'Transmittal No ...')",
                file_type=file_type,
                suggestion="This doesn't appear to be a Transmittal Report. Check that you exported the correct report from RMS.",
            ))
            return issues, None

        if entry_count == 0:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"Found {transmittal_count} transmittal headers but no item data rows",
                file_type=file_type,
            ))

        return issues, entry_count

    def _validate_cross_references(
        self,
        register_df: pd.DataFrame,
        assignments_df: Optional[pd.DataFrame],
        transmittal_df: Optional[pd.DataFrame],
    ) -> list[ValidationIssue]:
        """Validate cross-references between files."""
        issues = []

        # Get unique section-item pairs from register
        if "section" in register_df.columns and "item no" in register_df.columns:
            register_keys = set()
            for _, row in register_df.iterrows():
                section = str(row.get("section", "")).strip()
                item = str(row.get("item no", "")).strip()
                if section and item:
                    register_keys.add(f"{section}-{item}")

            # Check assignments reference valid submittals (only if assignments provided)
            if assignments_df is not None and "section" in assignments_df.columns and "item no" in assignments_df.columns:
                orphan_count = 0
                for _, row in assignments_df.iterrows():
                    section = str(row.get("section", "")).strip()
                    item = str(row.get("item no", "")).strip()
                    if section and item:
                        key = f"{section}-{item}"
                        if key not in register_keys:
                            orphan_count += 1

                if orphan_count > 0:
                    issues.append(ValidationIssue(
                        severity=Severity.WARNING,
                        message=f"{orphan_count} assignments reference submittals not in register",
                        file_type=FileType.SUBMITTAL_ASSIGNMENTS,
                        suggestion="These assignments will be ignored during import",
                    ))

        return issues

    def _suggest_column(self, missing: str, available: list[str]) -> Optional[str]:
        """Suggest a column name correction based on available columns."""
        # Check if any available column is similar
        missing_lower = missing.lower()
        for col in available:
            col_lower = col.lower()
            # Check for partial match
            if missing_lower in col_lower or col_lower in missing_lower:
                return f"Did you mean '{col}'?"
            # Check for similar words
            missing_words = set(missing_lower.split())
            col_words = set(col_lower.split())
            if missing_words & col_words:
                return f"Did you mean '{col}'?"

        return None
