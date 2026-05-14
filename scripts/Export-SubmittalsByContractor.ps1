# Export-SubmittalsByContractor.ps1
# Filters "Enhanced Register" sheet by each Contractor and exports filtered view as PDF

param(
    [switch]$SkipExisting  # Skip contractors that already have a PDF
)

$folder = Split-Path -Parent $MyInvocation.MyCommand.Path
$workbookPath = Join-Path $folder "1 - Submittal Report.xlsx"

if (-not (Test-Path $workbookPath)) {
    Write-Error "Workbook not found: $workbookPath"
    exit 1
}

# Kill orphaned Excel processes
Stop-Process -Name Excel -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$excel = $null
$wb = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $wb = $excel.Workbooks.Open($workbookPath)
    $ws = $wb.Worksheets.Item("Enhanced Register")

    # Find header row and Contractor column
    $headerRow = 7
    $contractorCol = 14  # Column N

    # Unhide all rows first (hidden rows cause End(xlUp) to stop early)
    $ws.Rows.Hidden = $false

    # Find last data row using UsedRange (reliable even if rows were hidden)
    $ur = $ws.UsedRange
    $lastRow = $ur.Row + $ur.Rows.Count - 1
    Write-Host "Data range: rows $($headerRow+1) to $lastRow" -ForegroundColor Cyan

    # Get unique contractor values (split MULTIPLE entries into individual names)
    $contractors = @{}
    for ($r = $headerRow + 1; $r -le $lastRow; $r++) {
        $val = $ws.Cells($r, $contractorCol).Value2
        if ($val -and $val.ToString().Trim() -ne "") {
            $cellVal = $val.ToString().Trim()
            if ($cellVal -match '^MULTIPLE:\s*(.+)$') {
                $names = $Matches[1] -split ',' | ForEach-Object { $_.Trim() }
                foreach ($name in $names) {
                    if ($name -ne "") { $contractors[$name] = $true }
                }
            } else {
                $contractors[$cellVal] = $true
            }
        }
    }

    $sorted = $contractors.Keys | Sort-Object
    Write-Host "Found $($sorted.Count) contractors" -ForegroundColor Cyan

    $exported = 0
    $skipped = 0

    foreach ($contractor in $sorted) {
        # Build safe filename (replace characters not allowed in filenames)
        $safeName = $contractor -replace '[\\/:*?"<>|]', '_'
        # Trim trailing dots/spaces (Windows doesn't like them)
        $safeName = $safeName.TrimEnd('. ')
        $pdfName = "1 - Submittal Report - $safeName.pdf"
        $pdfPath = Join-Path $folder $pdfName

        if ($SkipExisting -and (Test-Path $pdfPath)) {
            Write-Host "  SKIP (exists): $pdfName" -ForegroundColor DarkGray
            $skipped++
            continue
        }

        Write-Host "  Exporting: $contractor ..." -NoNewline

        # Apply AutoFilter on the Contractor column for this value
        # If AutoFilter is already on, turn it off first
        if ($ws.AutoFilterMode) {
            $ws.AutoFilterMode = $false
        }

        # Apply filter: Field is relative to the filter range starting column
        # Range starts at column B (2), so Contractor (col 14) is field 13
        # Use wildcard to also match MULTIPLE entries containing this contractor
        $filterRange = $ws.Range($ws.Cells($headerRow, 2), $ws.Cells($lastRow, $contractorCol))
        $filterRange.AutoFilter(13, "=*$contractor*")

        # Export filtered sheet to PDF
        # xlTypePDF = 0, xlQualityStandard = 0
        $ws.ExportAsFixedFormat(0, $pdfPath, 0)

        Write-Host " done" -ForegroundColor Green
        $exported++
    }

    # Clear filter
    if ($ws.AutoFilterMode) {
        $ws.AutoFilterMode = $false
    }

    Write-Host "`nComplete: $exported exported, $skipped skipped" -ForegroundColor Cyan

} catch {
    Write-Error "Error: $_"
} finally {
    if ($wb) {
        $wb.Close($false)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wb) | Out-Null
    }
    if ($excel) {
        $excel.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
