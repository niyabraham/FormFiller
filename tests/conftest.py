"""Shared fixtures. Browser tests need Playwright + a Chromium build; when
either is missing they are skipped (not failed), so the pure-Python suite
always runs. Point FORMFILL_CHROMIUM at a Chromium executable to override
Playwright's managed browser."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "web" / "fixtures"


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    exe = os.environ.get("FORMFILL_CHROMIUM") or None
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=exe)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium unavailable: {str(exc).splitlines()[0]}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    pg = context.new_page()
    pg.set_default_timeout(4000)
    yield pg
    context.close()


@pytest.fixture
def open_fixture(page):
    def _open(name: str):
        page.goto((FIXTURES / name).as_uri())
        return page

    return _open
