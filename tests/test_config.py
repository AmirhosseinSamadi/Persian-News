import pytest

from news_similarity.config import ConfigurationError, Settings


def test_defaults_allow_database_commands_without_credentials(tmp_path):
    settings = Settings.load(tmp_path / "absent.env", environ={})
    assert settings.database_url == "sqlite:///./data/news.db"
    assert settings.telegram_session_name == "telegram_news"
    with pytest.raises(ConfigurationError, match="Set TELEGRAM_API_ID"):
        settings.require_telegram()


def test_env_file_loading_and_environment_precedence(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_API_ID=100\nTELEGRAM_API_HASH=" + "b" * 32 + "\nLOG_LEVEL=debug\n",
        encoding="utf-8",
    )
    settings = Settings.load(env_file, environ={"TELEGRAM_API_ID": "200"})
    assert settings.require_telegram() == (200, "b" * 32)
    assert settings.log_level == "DEBUG"
    assert "b" * 32 not in repr(settings)
    assert "telegram_api_id" not in repr(settings)


@pytest.mark.parametrize("value", ["0", "-4", "not-a-number"])
def test_invalid_api_id(tmp_path, value):
    with pytest.raises(ConfigurationError, match="positive integer"):
        Settings.load(tmp_path / "absent", environ={"TELEGRAM_API_ID": value})


@pytest.mark.parametrize("hash_value", ["invalid", "z" * 32, "a" * 31])
def test_invalid_hash(hash_value):
    with pytest.raises(ConfigurationError, match="32 hexadecimal"):
        Settings(telegram_api_hash=hash_value)


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "postgresql://localhost/news",
        "sqlite://",
        "sqlite:///",
        "sqlite://remote/news.db",
        "sqlite:///news.db?uri=true",
    ],
)
def test_only_local_sqlite_is_supported(url):
    with pytest.raises(ConfigurationError, match="SQLite|sqlite"):
        Settings(database_url=url)


@pytest.mark.parametrize(
    "values",
    [
        {"log_level": "verbose"},
        {"telegram_session_name": " "},
        {"telegram_session_name": ":memory:"},
    ],
)
def test_other_invalid_settings(values):
    with pytest.raises(ConfigurationError):
        Settings(**values)


def test_session_path_from_dotenv_and_environment(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_SESSION_NAME=data/local_login\n", encoding="utf-8")
    assert (
        Settings.load(env_file, environ={}).telegram_session_name == "data/local_login"
    )
    settings = Settings.load(
        env_file, environ={"TELEGRAM_SESSION_NAME": "data/other_login"}
    )
    assert settings.telegram_session_name == "data/other_login"
