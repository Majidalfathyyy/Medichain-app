"""Keep integration tests isolated from the developer's configured database."""
import os
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DATA = PROJECT_ROOT / ".task-temp" / "pytest-e2e" / uuid4().hex
TEST_DATA.mkdir(parents=True, exist_ok=True)
TEST_DATA_RELATIVE = TEST_DATA.relative_to(PROJECT_ROOT).as_posix()

os.environ.update(
    APP_ENV="test",
    DATABASE_URL=f"sqlite:///./{TEST_DATA_RELATIVE}/medichain.db",
    MOCK_CHAIN_FILE=f"./{TEST_DATA_RELATIVE}/mockchain.json",
    ENABLE_TAMPER_SIM="true",
    ENABLE_EMAIL_OTP_REGISTRATION="false",
    SEED_PASSWORD="Demo-Medichain-2026",
    JWT_SECRET="test-only-secret-key-for-isolated-e2e-tests-32-bytes",
)
