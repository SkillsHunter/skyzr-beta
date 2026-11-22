"""Shared test setup: every test starts with an empty server-wide AI cache."""

import pytest

import ai


@pytest.fixture(autouse=True)
def _empty_ai_cache():
    ai.SHARED_CACHE.clear()
    yield
    ai.SHARED_CACHE.clear()
