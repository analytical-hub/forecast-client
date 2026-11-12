# forecast-client — клиент сервиса прогноза analytical-hub

forecast-client — Python-библиотека для прогнозов моделей analytical-hub на
свои сценарии факторов: узнать, какие модели доступны, взять базовый сценарий,
изменить его и получить прогноз.

Для работы нужен ключ доступа — его выдаёт владелец сервиса.

## Быстрый старт

```python
from forecast_client import DeskModel, desks

# 1. Какие дески доступны по вашему ключу
print(desks())  # ['agro', 'oil', ...]


# 2. Клиент деска — один раз на деск
class AgroModel(DeskModel):
    desk = "agro"


# 3. Модели деска
for info in AgroModel.available():
    print(info.commodity, info.version)  # wheat 4, ...

# 4. Модель и факторы, от которых зависит её прогноз
wheat = AgroModel("wheat")
print(wheat.info.factors)  # ['Brent', 'DXY', ...]

# 5. Базовый сценарий — значения факторов по месяцам прогноза — и свой:
# например, нефть на 10 % дороже базового
scenario = wheat.scenario()
scenario["Brent"] *= 1.1

# 6. Прогноз: таблица «месяц → прогноз»
forecast = wheat.predict(scenario)
print(forecast.to_frame())
```

## Установка

```bash
pip install https://github.com/analytical-hub/forecast-client/archive/refs/tags/v0.14.0.zip
```

Python 3.12+. Аккаунт GitHub и git не нужны; другая версия — другой тег в
адресе.

## Доступ

Адрес сервиса и ключ — у владельца сервиса. Ключ личный: не передавайте его и
не кладите в git. Задать их — в окружении или в `.env` рядом с кодом:

```bash
FORECAST_URL=http://<адрес сервиса>:<порт>
FORECAST_API_KEY=<ключ>
```

или прямо в коде: `AgroModel("wheat", host="http://…", api_key="…")`, так же
у `desks` и `available`.

## Что есть

- `desks()` — дески, модели которых отдаёт сервис.
- `class <Деск>Model(DeskModel): desk = "<деск>"` — клиент деска.
- `<Деск>Model.available()` — модели деска.
- `<Деск>Model("<товар>", alias="prod")` — модель; `alias="challenger"` —
  версия до выкатки.
- `model.info` — версия, частота (`M` или `Y`), первый период прогноза,
  факторы, границы факторов.
- `model.scenario()` — базовый сценарий: `DataFrame` факторов по периодам.
- `model.predict(factors, out_of_range="reject")` — прогноз; `to_frame()` —
  таблица со столбцом `forecast`.

## Сценарий

- Периоды — индекс или столбец `Date`: `2026-09` у помесячной модели, `2026`
  у годовой; подряд, с `model.info.first_period`.
- Столбцы — `model.info.factors`, числа без пропусков.
- Значения вне `model.info.bounds`: `reject` — ошибка, `clip` — считать при
  границе, `extrapolate` — считать как есть.

## Ошибки

Все — подклассы `ClientError`:

- `AuthError` — сервис не принял ключ;
- `RateLimitError` — превышен лимит запросов, повторить через `retry_after` с;
- `ModelNotFoundError` — нет такой модели или алиаса;
- `ForecastRequestError` — сервис отклонил сценарий, по пункту на ошибку;
- `ServiceUnavailableError` — сервис не ответил: адрес, порт, сеть.

## Без Python

Сервис — HTTP API с ключом в заголовке `X-API-Key`. Описание и песочница —
`http://<адрес сервиса>:<порт>/docs`, ключ — кнопкой Authorize.

## Лицензия

Исходный код открыт для ознакомления, использование — по ключу от
правообладателя: [LICENSE](LICENSE). Репозиторий — зеркало только для чтения:
issues и pull requests здесь не принимаются.
