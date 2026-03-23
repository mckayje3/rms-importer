"""Application configuration."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App settings
    app_name: str = "RMS to Procore Importer"
    debug: bool = False

    # Procore OAuth
    procore_client_id: str
    procore_client_secret: str
    procore_base_url: str = "https://api.procore.com"
    procore_auth_url: str = "https://login.procore.com/oauth/token"
    procore_authorize_url: str = "https://login.procore.com/oauth/authorize"

    # Frontend URL (for CORS and redirects)
    frontend_url: str = "http://localhost:3000"

    # Backend URL (for OAuth redirect URI)
    backend_url: str = "http://localhost:8000"

    # Session secret for OAuth state
    session_secret: str = "change-me-in-production"

    # RMS Files folder (local path for file sync; leave empty to skip file scanning)
    rms_files_path: str = ""

    # Procore Documents folder ID for uploaded files (required for file uploads)
    procore_upload_folder_id: int = 0

    # Turso/libSQL database (leave empty to use local SQLite)
    turso_database_url: str = ""
    turso_auth_token: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
