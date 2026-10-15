"""Testler gerçek GitHub kimlik bilgisiyle uzak çağrı yapmasın."""

import pytest

_GITHUB_ENV = (
    "GITHUB_TOKEN",
    "GITHUB_OWNER",
    "GITHUB_REPO",
    "GITHUB_REPOSITORY",
    "GITHUB_API_BASE",
    "GITHUB_BASE_BRANCH",
)


@pytest.fixture(autouse=True)
def isolate_github_credentials(monkeypatch):
    # Boş değer, load_dotenv(override=False) dosyadan token yüklemesini engeller.
    for name in _GITHUB_ENV:
        monkeypatch.setenv(name, "")
