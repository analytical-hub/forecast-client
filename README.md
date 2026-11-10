# forecast-client

Клиент сервиса прогноза и контракт его API: всё, что нужно, чтобы получить
прогноз опубликованной модели. Обучать и публиковать модели — `forecast-sdk`.

| Модуль | Что это |
|---|---|
| `forecast_client.schemas` | контракт API: запросы, ответы, описания моделей |
| `forecast_client.model` | `DeskModel` — клиент моделей деска |
| `forecast_client.exceptions` | ошибки клиента |
| `forecast_client.settings` | адрес сервиса, ключ, таймаут и повторы |

Код живёт в `client/` репозитория `forecast-platform`. Репозиторий
`forecast-client` — его зеркало только для чтения: CI выкладывает туда
`client/` на каждый тег релиза с тем же тегом. Правки в зеркале руками
остановят следующую выкладку.

## Установка в репозитории деска

`pyproject.toml` деска:

```toml
[project]
dependencies = ["forecast-client"]

[dependency-groups]
# Разработчику моделей: протокол обучения, publish и forecast env
models = ["forecast-sdk"]

[tool.uv]
# forecast-sdk из платформы тянет клиента из её workspace: переопределение
# берёт его из источника ниже и для аналитика, и для разработчика
override-dependencies = ["forecast-client"]

[tool.uv.sources]
forecast-client = { git = "https://github.com/analytical-hub/forecast-client", tag = "v0.10.0" }
forecast-sdk = { git = "https://github.com/analytical-hub/forecast-platform", tag = "v0.10.0", subdirectory = "sdk" }
```

- Аналитик: `uv sync` — нужен доступ к репозиторию деска и к `forecast-client`.
- Разработчик моделей: `uv sync --group models`, затем
  `uv run forecast env <окружение>` — нужен ещё доступ к `forecast-platform`.

Группа не называется `dev`: её uv ставит по умолчанию. Обновить клиент и SDK —
сменить оба тега, они всегда одинаковые, затем `uv lock`.

## Клиент деска

Деск объявляет свой клиент один раз — в запросы подставляется только товар:

```python
from forecast_client.model import DeskModel


class AgroModel(DeskModel):
    desk = "agro"
```

```python
AgroModel.available()  # модели деска под prod

with AgroModel("wheat") as model:
    base = model.scenario()  # базовый сценарий факторов
    result = model.predict(base)
    result.to_frame()
```

Другой алиас — `AgroModel("wheat", alias="challenger")`. Имя деска — латиница,
цифры и подчёркивание: проверяется при объявлении класса.

## Границы факторов

У модели могут быть границы факторов — `model.info.bounds`, например
`{"BRENT_REAL": (0.0, 120.0)}`: за ними у модели нет данных. Что делать со
значением вне границ, решает запрос:

| `out_of_range` | Что делает сервис |
|---|---|
| `"reject"` (по умолчанию) | отклоняет сценарий: `ForecastRequestError` с периодом, фактором и значением |
| `"clip"` | считает при границе: 150 при границах [0, 120] — как 120 |
| `"extrapolate"` | считает как есть: модель продолжает зависимость за данные |

```python
result = model.predict(stress, out_of_range="clip")
result.warnings  # что обрезано или экстраполировано, по факторам и периодам
```

Предупреждения сервиса приходят и через `warnings.warn`. Сценарий внутри
границ считается одинаково при любом `out_of_range`.

## Настройки

Переменные окружения или `.env` — он ищется от папки ноутбука вверх, обычно в
корне репозитория деска:

| Переменная | По умолчанию | Что это |
|---|---|---|
| `FORECAST_URL` | `http://localhost:5001` | адрес сервиса прогноза |
| `FORECAST_API_KEY` | — | ключ клиента, выдаёт администратор сервиса |
| `FORECAST_TIMEOUT` | `120` | ожидание ответа, с |
| `FORECAST_RETRIES` | `2` | повторы, если соединение не установилось |

```bash
FORECAST_URL=http://<сервер>:5001
FORECAST_API_KEY=<ключ>
```

Ключ уходит заголовком `X-API-Key` в каждом запросе. Ошибки — подклассы
`ClientError`:

| Ошибка | Когда |
|---|---|
| `AuthError` | сервис не принял ключ |
| `RateLimitError` | больше запросов в минуту, чем разрешено ключу; через сколько секунд повторить — `retry_after` |
| `ModelNotFoundError` | такой модели или алиаса нет на сервисе |
| `ForecastRequestError` | сервис отклонил сценарий: по пункту на каждую ошибку, в том числе значения вне границ |
| `ServiceUnavailableError` | сервис не ответил |
| `ServiceError` | другая ошибка сервиса или ответ не по контракту |

## Совместимость со шлюзом

Клиент и шлюз связаны контрактом `forecast_client.schemas`. Шлюз выкатывается
на сервер раньше, чем дески переходят на новый тег клиента: клиент работает со
шлюзом своего релиза и новее.
