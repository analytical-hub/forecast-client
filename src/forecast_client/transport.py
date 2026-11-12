from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from forecast_client.exceptions import (
    AuthError,
    ForecastRequestError,
    ModelNotFoundError,
    RateLimitError,
    ServiceError,
    ServiceUnavailableError,
)
from forecast_client.settings import ClientSettings


def connect(
    host,
    api_key,
    transport,
) -> tuple[httpx.Client, int]:
    """
    HTTP-клиент к сервису и число повторов соединения из настроек.

    Ключ клиента уходит заголовком X-API-Key в каждом запросе.

    Parameters:
        - host: адрес сервиса; без него — из настроек клиента;
        - api_key: ключ клиента; без него — из настроек клиента;
        - transport: транспорт httpx, только для тестов.

    Raises:
        ValueError: адрес не вида http(s)://<host>:<port>.
    """

    settings = ClientSettings()
    url = httpx.URL(host or settings.url)
    if url.scheme not in {"http", "https"} or not url.host:
        msg = (
            f"адрес сервиса {str(url)!r} должен быть вида http://<host>:<port>"
        )
        raise ValueError(msg)
    if api_key is None and settings.api_key is not None:
        api_key = settings.api_key.get_secret_value()
    headers = {} if api_key is None else {"X-API-Key": api_key}
    http = httpx.Client(
        base_url=str(url).rstrip("/"),
        headers=headers,
        timeout=settings.timeout,
        transport=transport,
    )
    return http, settings.retries


def problems(detail, payload) -> list[str]:
    """
    Ошибки 422 по пункту на каждую; строки запроса названы периодами.
    """

    if isinstance(detail, str):
        return [detail]
    rows = (payload or {}).get("rows", [])
    found = []
    for item in detail:
        # loc: body, rows, номер строки, period или factors, имя фактора
        loc = list(item.get("loc", []))[1:]
        if loc[:1] == ["rows"] and len(loc) > 1 and loc[1] < len(rows):
            loc = [rows[loc[1]]["period"], *loc[3:]]
        found.append(f"{' · '.join(map(str, loc))}: {item.get('msg')}")
    return found


# Форма JSON-ответа зависит от ручки
def read(response, payload) -> Any:  # noqa: ANN401
    """
    Тело успешного ответа или типизированная ошибка.

    Raises:
        AuthError: 401;
        RateLimitError: 429;
        ModelNotFoundError: 404;
        ForecastRequestError: 422;
        ServiceError: другая ошибка или ответ не JSON.
    """

    if response.status_code == httpx.codes.UNAUTHORIZED:
        msg = (
            "Сервис прогноза не принял ключ. Проверьте api_key или "
            "FORECAST_API_KEY в окружении или .env"
        )
        raise AuthError(msg)
    try:
        body = response.json()
    except ValueError as error:
        raise ServiceError(response.status_code, response.text[:200]) from error
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        wait = response.headers.get("Retry-After", "")
        raise RateLimitError(detail, int(wait) if wait.isdigit() else None)
    if response.status_code == httpx.codes.NOT_FOUND:
        raise ModelNotFoundError(detail)
    if response.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
        raise ForecastRequestError(problems(detail, payload))
    if response.is_error:
        raise ServiceError(response.status_code, detail)
    return body


# Форма JSON-ответа зависит от ручки
def send(
    http,
    retries,
    method,
    path,
    payload=None,
    params=None,
) -> Any:  # noqa: ANN401
    """
    Запрос к сервису с повтором, если соединение не установилось.

    Raises:
        ServiceUnavailableError: сервис не ответил;
        AuthError, RateLimitError, ModelNotFoundError, ForecastRequestError,
            ServiceError: см. read.
    """

    error: httpx.TransportError | None = None
    for _ in range(retries + 1):
        try:
            response = http.request(
                method,
                path,
                json=payload,
                params=params,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as failure:
            # Соединения не было — запрос не дошёл до сервиса, повтор безопасен
            error = failure
            continue
        except httpx.TransportError as failure:
            error = failure
            break
        return read(response, payload)
    msg = (
        f"Сервис прогноза не отвечает по {http.base_url} ({error}). "
        "Проверьте адрес — host или FORECAST_URL — и что порт "
        f"{http.base_url.port} доступен с этой машины"
    )
    raise ServiceUnavailableError(msg) from error


def parse[T: BaseModel](schema: type[T], body) -> T:
    """
    Ответ сервиса по контракту forecast_client.schemas.

    Raises:
        ServiceError: ответ не по контракту.
    """

    try:
        return schema.model_validate(body)
    except ValidationError as error:
        text = f"ответ не по контракту {schema.__name__}: {error}"
        raise ServiceError(httpx.codes.OK, text) from error
