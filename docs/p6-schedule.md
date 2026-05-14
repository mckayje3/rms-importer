# P6 Schedule Integration (Planned)

## Overview
Link Procore submittals to P6 schedule tasks using the `task_id` field on submittals.

## Data Sources
- **P6 Schedule File**: `P2#504840-U10r0 - Dobbins Air Reserve Base SFF - February 2026 Update.txt`
  - Primavera P6 XER-like text export
  - 385 activities including SUB.* submittal workflow activities

- **Trade Code Mapping**: `trade_code_mapping.csv`
  - Maps P6 trade codes to Procore Directory companies

## P6 Submittal Activities
SUB.* activities track submittal workflow phases:
- **Phase A**: D&S (Design & Submit)
- **Phase B**: R&A (Review & Approve)
- **Phase C**: Procure
- **Phase D**: Deliver

**Activity ID Pattern**: `SUB.{TradeCode}.{Sequence}.{Phase}`
Example: `SUB.STL.01.A` = Steel, first submittal, D&S phase

## Trade Code Mapping (Partial)
| Code | Trade | Company |
|------|-------|---------|
| PLUM | Plumbing | DC Mechanical, LLC |
| MECH | Mechanical | DC Mechanical, LLC |
| STL | Steel | Superior Rigging & Erecting Company |
| MASN | Masonry | Cruz Masonry |
| CONC | Concrete | Altis Concrete |
| ROOF | Roofing | Alpha Commercial Roofing |
| CVL | Civil | Phoenix Engineering |
| FS | Fire Sprinkler | International Fire Protection Inc. |
| GOVT | Government | U.S. Army Corps of Engineers Atlanta Resident Office |

**Still need mapping**: DRYW, ELEC, CARP, PNT, FLR, SPEC

## Procore Schedule API
- Submittals have a `task_id` field to link to schedule tasks
- Schedule tasks endpoint: `/rest/v1.0/projects/{id}/schedule/tasks`
- Script: `check_schedule_tasks.ps1` - verify schedule API access

## TODO
- [ ] Complete trade code mapping in `trade_code_mapping.csv`
- [ ] Parse P6 schedule file to extract SUB.* activities
- [ ] Match submittals to schedule tasks by spec section + trade code
- [ ] Script: `link_schedule_tasks.ps1` - update submittals with task_id
