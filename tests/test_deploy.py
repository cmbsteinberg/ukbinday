"""
Docker Compose deployment smoke tests.

Verifies the containerised stack boots correctly — app starts, scrapers load,
and static files are served. Application logic is tested in test_frontend.py.

Usage:
    uv run pytest tests/test_deploy.py -v
"""

import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.docker

BASE_URL = "http://localhost:8000"
MAX_WAIT = 60  # seconds


@pytest.fixture(scope="session")
def docker_stack():
    """Build and start the Docker Compose stack, tear down on exit."""
    subprocess.run(
        ["docker", "compose", "up", "--build", "-d"],
        check=True,
        capture_output=True,
    )

    elapsed = 0
    while elapsed < MAX_WAIT:
        try:
            r = httpx.get(f"{BASE_URL}/api/v1/health", timeout=3)
            if r.status_code == 200:
                break
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
            pass
        time.sleep(2)
        elapsed += 2
    else:
        logs = subprocess.run(
            ["docker", "compose", "logs", "api", "--tail", "50"],
            capture_output=True,
            text=True,
        )
        pytest.fail(
            f"API not ready after {MAX_WAIT}s.\n\n--- container logs ---\n{logs.stdout}"
        )

    yield

    subprocess.run(
        ["docker", "compose", "down", "--volumes", "--remove-orphans"],
        capture_output=True,
    )


@pytest.fixture(scope="session")
def client(docker_stack):
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


def test_health(client):
    """App boots and connects to Redis."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_scrapers_loaded(client):
    """Scraper registry populated inside the container."""
    resp = client.get("/api/v1/councils")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    assert "id" in data[0] and "name" in data[0]


def test_static_files_served(client):
    """Static assets and templates render correctly."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
