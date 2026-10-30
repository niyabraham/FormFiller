"""Shared fixtures. Browser tests need Playwright + a Chromium build. Point FORMFILL_CHROMIUM at a Chromium executable to
override Playwright's managed browser.

Locally, when Playwright or Chromium is missing, browser tests are skipped (not failed), so the pure-Python suite always runs.
With FORMFILL_REQUIRE_BROWSER=1 (set in CI) that is an error instead: a missing package or a browser that fails to launch fails
the run with the reason, and any browser test that would have been skipped is reported as a failure. Expected failures
(xfail) are unaffected."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "web" / "fixtures"
STRICT = os.environ.get("FORMFILL_REQUIRE_BROWSER") == "1"
_BROWSER_FIXTURES = {"browser", "page", "open_fixture"}


@pytest.fixture(scope="session")
def browser():
    if STRICT:
        import playwright.sync_api as sync_api  # an ImportError fails the run: required browser tests must not skip
    else:
        sync_api = pytest.importorskip("playwright.sync_api")
    exe = os.environ.get("FORMFILL_CHROMIUM") or None
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=exe)
        except Exception as exc:  # noqa: BLE001
            reason = f"Chromium unavailable: {str(exc).splitlines()[0]}"
            if STRICT:
                pytest.fail(f"{reason} (FORMFILL_REQUIRE_BROWSER=1: browser tests are required)", pytrace=False)
            pytest.skip(reason)
        yield b
        b.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if not STRICT or not report.skipped or hasattr(report, "wasxfail"):
        return
    if item.get_closest_marker("browser") or _BROWSER_FIXTURES & set(getattr(item, "fixturenames", ())):
        report.outcome = "failed"
        report.longrepr = f"browser test skipped while FORMFILL_REQUIRE_BROWSER=1: {report.longrepr}"


def pytest_report_header(config):
    return f"FormFiller browser tests: {'REQUIRED (FORMFILL_REQUIRE_BROWSER=1)' if STRICT else 'skipped if Chromium is unavailable'}"


@pytest.fixture
def page(browser):
    context = browser.new_context()
    pg = context.new_page()
    pg.set_default_timeout(4000)
    yield pg
    context.close()


@pytest.fixture
def open_fixture(page):
    from formfill.web.pipeline import release_wizard_network_guard

    def _open(name: str):
        release_wizard_network_guard(page)
        page.goto((FIXTURES / name).as_uri())
        return page

    return _open
