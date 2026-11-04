"""Pytest fixtures for scenario tests."""

# Reuse the PostgreSQL fixtures of the integration suite. Importing them registers them for this directory;
# `pytest_plugins` is not allowed in a non-root conftest (pytest 8+), which stopped collection of the whole suite.
from tests.integration.conftest import (  # noqa: F401
    admin_engine,
    count_queries,
    db,
    engine,
    migrated_url,
)
