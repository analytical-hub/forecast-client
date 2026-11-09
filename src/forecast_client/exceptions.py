class ClientError(Exception):
    """
    Ошибка обращения к сервису прогноза.
    """


class ServiceUnavailableError(ClientError):
    """
    Сервис не ответил: нет туннеля, закрыт порт, таймаут или неверный адрес.
    """


class AuthError(ClientError):
    """
    Сервис не принял ключ: нет или неверный FORECAST_API_KEY.
    """


class RateLimitError(ClientError):
    """
    Превышен лимит запросов клиента в минуту.

    Parameters:
        - message: ответ сервиса;
        - retry_after: через сколько секунд повторить, если сервис сообщил.
    """

    def __init__(self, message, retry_after=None) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class ModelNotFoundError(ClientError):
    """
    Модели или алиаса нет в реестре деска.

    Parameters:
        - message: что не найдено;
        - available: товары деска, которые есть на сервисе.
    """

    def __init__(self, message, available=()) -> None:
        self.available = list(available)
        if self.available:
            message = (
                f"{message}. Доступные товары: {', '.join(self.available)}"
            )
        super().__init__(message)


class ForecastRequestError(ClientError):
    """
    Сервис отклонил сценарий.

    Parameters:
        - problems: что не так, по пункту на ошибку, с месяцем.
    """

    def __init__(self, problems) -> None:
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


class ServiceError(ClientError):
    """
    Сервис ответил ошибкой или не по контракту.

    Parameters:
        - status: HTTP-статус ответа;
        - text: тело или описание ответа.
    """

    def __init__(self, status, text) -> None:
        self.status = status
        self.text = text
        super().__init__(f"HTTP {status}: {text}")
