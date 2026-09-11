from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalog_watch.site import SiteConfig

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO


@pytest.fixture(scope="session")
def fixture_config() -> SiteConfig:
    return SiteConfig.load(REPO / "sites" / "fixture.json")


@pytest.fixture(scope="session")
def expected() -> dict:
    return json.loads(
        (REPO / "tests" / "expected_changes.json").read_text(encoding="utf-8")
    )
