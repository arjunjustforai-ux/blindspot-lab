"""Test configuration. Environment is set before the application is imported.

Unit tests need no services. Integration tests need PostgreSQL with pgvector and a test database
(default postgresql+psycopg://blindspot:blindspot@localhost:5432/blindspot_test, override with
TEST_DATABASE_URL); they are skipped automatically when it is unreachable.
"""

from __future__ import annotations

import os
import tempfile

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://blindspot:blindspot@localhost:5432/blindspot_test"
)
os.environ["JWT_SECRET"] = "test-secret-not-used-anywhere-else-0123456789"
os.environ["LOCAL_STORAGE_DIR"] = tempfile.mkdtemp(prefix="blindspot-test-storage-")
os.environ["RUN_WORKER_IN_PROCESS"] = "false"
os.environ["LLM_PROVIDER"] = "local"
os.environ.pop("OPENAI_API_KEY", None)
