"""
Shared test setup.

- Tests need an AUTH_SECRET_KEY; a random one is used if the environment has none
  (a value from the real environment / .env still takes precedence).
- `override_auth` lets API tests of the agents run as a signed-in test manager.
"""
import os
import secrets

os.environ.setdefault("AUTH_SECRET_KEY", secrets.token_urlsafe(48))

import pytest  # noqa: E402


@pytest.fixture
def override_auth():
    from app.api.routes.auth import get_current_manager
    from app.main import app
    from app.schemas.auth import ManagerProfile

    app.dependency_overrides[get_current_manager] = lambda: ManagerProfile(
        manager_id="PYTEST_MANAGER", manager_type="Production Manager", email="pytest@example.com")
    yield
    app.dependency_overrides.pop(get_current_manager, None)
