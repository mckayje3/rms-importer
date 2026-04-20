"""RMS to Procore Importer - FastAPI Backend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from routers import auth, projects, submittals, rms_upload, health, qaqc, sync, setup, rfi, daily_logs

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Import RMS submittal data into Procore",
    version="0.1.0",
)

# CORS middleware for frontend (includes Procore for embedded app context)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:3000",
        "https://app.procore.com",
        "https://us02.procore.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(projects.router, prefix="/projects", tags=["Projects"])
app.include_router(submittals.router, prefix="/submittals", tags=["Submittals"])
app.include_router(rms_upload.router, prefix="/rms", tags=["RMS Upload"])
app.include_router(qaqc.router, prefix="/qaqc", tags=["QAQC Deficiencies"])
app.include_router(sync.router, prefix="/sync", tags=["Sync"])
app.include_router(setup.router, prefix="/setup", tags=["Setup"])
app.include_router(rfi.router, prefix="/rfi", tags=["RFI"])
app.include_router(daily_logs.router, prefix="/daily-logs", tags=["Daily Logs"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
    }
