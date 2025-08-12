from __future__ import annotations

import os
import time
from typing import Any, Dict

import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def wait_for_service(url: str, timeout: float = 30.0) -> None:
    start = time.time()
    last_err: Exception | None = None
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=2.0)
            if r.status_code == 200:
                return
        except Exception as e:  # pragma: no cover
            last_err = e
        time.sleep(0.5)
    if last_err:
        raise last_err
    raise RuntimeError(f"Service {url} not ready in {timeout}s")


def test_root_ok():
    wait_for_service(f"{BASE_URL}/")
    r = requests.get(f"{BASE_URL}/", timeout=5.0)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_providers_returns_list():
    params = {"drg": "470", "zip": "10001", "radius_km": 40}
    r = requests.get(f"{BASE_URL}/providers", params=params, timeout=30.0)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if data:
        first = data[0]
        assert "provider_id" in first and "ms_drg_definition" in first


def test_ask_returns_answer():
    body: Dict[str, Any] = {"question": "Who is cheapest for DRG 470 within 25 miles of 10001?"}
    r = requests.post(f"{BASE_URL}/ask", json=body, timeout=30.0)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("answer"), str)


