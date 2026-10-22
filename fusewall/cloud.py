"""Explicit environment-only cloud bootstrap. Never falls back to local storage."""

import os
import re

from .app import create_app


def store_from_environment():
    names = ("FUSEWALL_DATABASE_URL", "FUSEWALL_OWNER_TOKEN", "FUSEWALL_FINGERPRINT_KEY")
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing cloud configuration: " + ", ".join(missing))
    from .postgres import PostgresStore
    from psycopg.conninfo import conninfo_to_dict
    dsn = os.environ[names[0]]
    info = conninfo_to_dict(dsn)
    if info.get("host") not in ("127.0.0.1", "localhost", "::1") and info.get("sslmode") not in ("require", "verify-ca", "verify-full"):
        raise ValueError("Cloud database connections must explicitly require TLS")
    return PostgresStore(dsn, os.environ[names[1]], os.environ[names[2]], os.environ.get("FUSEWALL_DATABASE_SCHEMA", "fusewall"))


def create_cloud_app():
    hosts = set()
    for value in (os.environ.get("FUSEWALL_ALLOWED_HOSTS", "").split(",") +
                  [os.environ.get(name, "") for name in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL")]):
        value = value.strip().lower()
        if value:
            if not re.fullmatch(r"[a-z0-9.-]+", value):
                raise ValueError("Configured hosts must be explicit hostnames without URLs or wildcards")
            hosts.add(value)
    return create_app(store=store_from_environment(), allowed_hosts=hosts)
