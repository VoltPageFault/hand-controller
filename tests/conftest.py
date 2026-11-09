import pytest


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path, monkeypatch):
    """I test non devono mai leggere o scrivere le impostazioni reali dell'utente."""
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("HAND_CONTROLLER_CONFIG", str(path))
    return path
