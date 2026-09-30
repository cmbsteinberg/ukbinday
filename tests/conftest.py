"""Test-time environment defaults, set before any app code is imported."""

import atexit
import os
import shutil
import tempfile

os.environ.setdefault("CORS_ORIGINS", "https://bins.lovesguinness.com")
os.environ.setdefault("LOG_FORMAT", "text")
os.environ.setdefault("RUN_REFRESH_JOB", "0")
# Fresh ICS cache per session, so a live run never reads a previous run's data
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="bins-test-data-"))
os.environ.setdefault("ADDRESS_API_URL", "https://www.midsuffolk.gov.uk/api/jsonws/invoke")
os.environ.setdefault("ADDRESS_API_COMPANY_ID", "1486681")

atexit.register(shutil.rmtree, os.environ["DATA_DIR"], ignore_errors=True)
