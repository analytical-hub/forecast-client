from forecast_client.settings import ClientSettings


def test_defaults(monkeypatch) -> None:
    monkeypatch.delenv("FORECAST_URL", raising=False)
    monkeypatch.delenv("FORECAST_API_KEY", raising=False)

    settings = ClientSettings(_env_file=None)

    assert settings.url == "http://localhost:5001"
    assert settings.api_key is None
    assert settings.timeout == 120
    assert settings.retries == 2


def test_api_key_hidden(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("FORECAST_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("FORECAST_API_KEY=secret-key\n")

    settings = ClientSettings(_env_file=env_file)

    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "secret-key"
    assert "secret-key" not in repr(settings)


def test_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("FORECAST_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("FORECAST_URL=http://forecast.internal:5001\n")

    assert (
        ClientSettings(_env_file=env_file).url
        == "http://forecast.internal:5001"
    )


def test_environment_overrides_env_file(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FORECAST_URL=http://forecast.internal:5001\n")
    monkeypatch.setenv("FORECAST_URL", "http://other:5001")

    assert ClientSettings(_env_file=env_file).url == "http://other:5001"
