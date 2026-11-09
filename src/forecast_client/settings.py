from dotenv import find_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClientSettings(BaseSettings):
    """
    Настройки клиента сервиса прогноза: окружение FORECAST_*, затем .env.
    """

    # Ядро Jupyter запускается в папке ноутбука: .env ищется от неё вверх,
    # до корня репозитория деска
    model_config = SettingsConfigDict(
        env_prefix="FORECAST_",
        env_file=find_dotenv(usecwd=True) or None,
        extra="ignore",
    )

    url: str = Field(
        default="http://localhost:5001",
        description="Адрес сервиса прогноза",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="Ключ клиента: заголовок X-API-Key",
    )
    timeout: float = Field(
        default=120,
        gt=0,
        description="Ожидание ответа сервиса, с",
    )
    retries: int = Field(
        default=2,
        ge=0,
        description="Повторы, если не удалось установить соединение",
    )
