"""Runs local checks without installing packages, using paid APIs, or hosting CI."""
import ast
import json
import os
import shutil
import subprocess
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
started = time.perf_counter()
for source in (ROOT/'fusewall').rglob('*.py'):
    ast.parse(source.read_text(encoding='utf8'),filename=str(source))
node = shutil.which('node')
if node:
    subprocess.run([node,'--check','fusewall/static/app.js'],check=True)
suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
summary = {'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
           'skipped':len(result.skipped),'passed':result.wasSuccessful(),
           'elapsed_seconds':round(time.perf_counter()-started,3),
           'javascript_syntax_checked':bool(node),'provider_network_calls':0,
           'postgres_integration_enabled':bool(os.environ.get('FUSEWALL_PG_TEST_URL')),
           'verified_at_utc':datetime.now(timezone.utc).isoformat(),
           'scope':'Native SQLite plus optional isolated loopback PostgreSQL, HTTP contracts, synthetic streaming, crash/leases, export/restore; not Supabase/Vercel/live-provider validation'}
(ROOT/'evidence').mkdir(exist_ok=True)
(ROOT/'evidence'/'automated-test-results.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
raise SystemExit(0 if result.wasSuccessful() else 1)
