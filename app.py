"""Vercel FastAPI entrypoint. Requires a migrated, persistent shared database."""
from fusewall.cloud import create_cloud_app

app = create_cloud_app()
