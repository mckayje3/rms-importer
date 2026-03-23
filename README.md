# RMS Importer

A Procore Marketplace app for importing submittal data from USACE RMS (Resident Management System) to Procore.

## Project Structure

```
rms-importer/
├── backend/           # Python FastAPI backend
│   ├── main.py        # FastAPI application entry
│   ├── config.py      # Environment configuration
│   ├── models/        # Pydantic data models
│   ├── routers/       # API route handlers
│   ├── services/      # Business logic
│   ├── requirements.txt
│   └── .env           # Environment variables (not in git)
├── frontend/          # Next.js React frontend
│   ├── src/
│   │   ├── app/       # Next.js app router pages
│   │   ├── components/# React components
│   │   ├── lib/       # API client
│   │   └── types/     # TypeScript types
│   └── .env.local     # Frontend environment (not in git)
└── start_dev.ps1      # Development startup script
```

## Prerequisites

- Python 3.12+
- Node.js 20+
- Procore API credentials (OAuth client)

## Setup

### Backend

```powershell
cd backend
pip install -r requirements.txt
# Copy .env.example to .env and fill in your Procore credentials
python -m uvicorn main:app --reload --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

### Quick Start (Both)

```powershell
.\start_dev.ps1
```

This opens two terminal windows - one for each server.

## Environment Variables

### Backend (.env)

```
PROCORE_CLIENT_ID=your_client_id
PROCORE_CLIENT_SECRET=your_client_secret
FRONTEND_URL=http://localhost:3000
SESSION_SECRET=your-session-secret
```

### Frontend (.env.local)

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/auth/login` | GET | Start Procore OAuth flow |
| `/auth/callback` | GET | OAuth callback |
| `/projects/companies` | GET | List user's companies |
| `/projects/companies/{id}/projects` | GET | List company projects |
| `/rms/validate` | POST | Validate RMS files (check before upload) |
| `/rms/upload` | POST | Upload RMS Excel files (validates first) |
| `/rms/session/{id}/spec-sections` | GET | List spec sections from RMS |
| `/rms/session/{id}/contractor-template` | GET | Download contractor mapping CSV |
| `/rms/session/{id}/contractor-mapping` | POST | Upload filled contractor mapping |
| `/rms/session/{id}/contractor-mapping` | GET | Get current contractor mapping |
| `/rms/session/{id}/match-contractors` | POST | Match contractors to Procore Directory |
| `/rms/session/{id}/confirm-match` | POST | Confirm/override a vendor match |
| `/rms/session/{id}/vendors` | GET | List Procore Directory vendors |
| `/submittals/projects/{id}/check-specs` | POST | Check spec section availability |
| `/submittals/projects/{id}/analyze` | POST | Analyze RMS vs Procore |
| `/submittals/projects/{id}/import` | POST | Import submittals |
| `/qaqc/upload` | POST | Upload QAQC Deficiencies Excel file |
| `/qaqc/session/{id}/deficiencies` | GET | List parsed deficiencies |
| `/qaqc/session/{id}/match-locations` | POST | Match locations to Procore |
| `/qaqc/session/{id}/observation-types` | GET | Get available observation types |
| `/qaqc/session/{id}/import` | POST | Import deficiencies as Observations |

## Import Modes

1. **Full Migration** - Create all RMS submittals in empty Procore project
2. **Sync from RMS** - Update existing and create new from RMS (RMS is source of truth)
3. **Reconcile** - Manual review and merge of both systems

## RMS Files Required

### Submittals
Export these from RMS:
1. **Submittal Register** - Main submittal list with status/dates
2. **Submittal Assignments** - Activity assignments
3. **Transmittal Log** - Revision history

### QAQC Deficiencies
Export from RMS QAQC module:
1. **Deficiency Items Issued** - List of QA deficiencies with status

QAQC deficiencies are imported as Procore **Observations** with:
- Item Number → Observation title prefix (e.g., "QA-00001: ...")
- Description → Observation description
- Location → Procore Location (auto-created if missing)
- Status → Mapped to open/ready_for_review/closed
