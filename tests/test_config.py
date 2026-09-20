from core.config import Config


def test_owner_user_id_is_required(monkeypatch):
    monkeypatch.delenv("OWNER_USER_ID", raising=False)

    config = Config()

    assert config.owner_user_id is None
    assert not config.validate()


def test_owner_user_id_is_loaded_as_integer(monkeypatch):
    monkeypatch.setenv("OWNER_USER_ID", "987654321")

    config = Config()

    assert config.owner_user_id == 987654321
