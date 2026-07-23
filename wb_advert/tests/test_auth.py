"""Tests for portal session auth on wb_advert."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


def _client_with_secret(monkeypatch, secret: str) -> TestClient:
    monkeypatch.setenv("PORTAL_SESSION_SECRET", secret)
    import wb_advert.config as config

    importlib.reload(config)
    import wb_advert.middleware as middleware

    importlib.reload(middleware)
    import wb_advert.app as advert_app

    importlib.reload(advert_app)
    return TestClient(advert_app.create_app())


def test_protected_paths():
    from wb_advert.auth import is_protected_path

    assert is_protected_path("/advert")
    assert is_protected_path("/advert/decisions")
    assert is_protected_path("/api/advert/dashboard")
    assert not is_protected_path("/api/advert/health")
    assert not is_protected_path("/static/advert.css")


def test_health_open_without_session(monkeypatch):
    client = _client_with_secret(monkeypatch, "test-secret-key")
    response = client.get("/api/advert/health")
    assert response.status_code == 200


def test_api_requires_session(monkeypatch):
    client = _client_with_secret(monkeypatch, "test-secret-key")
    response = client.get("/api/advert/dashboard")
    assert response.status_code == 401
    assert response.json()["detail"] == "unauthorized"


def test_advert_page_redirects_to_login(monkeypatch):
    client = _client_with_secret(monkeypatch, "test-secret-key")
    response = client.get("/advert", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")
