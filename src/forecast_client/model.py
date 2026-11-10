import math
import re
import warnings
from dataclasses import dataclass
from typing import Any, ClassVar, Self

import pandas as pd

from forecast_client.exceptions import ClientError, ModelNotFoundError
from forecast_client.schemas import (
    ALIAS_PATTERN,
    NAME_PATTERN,
    ForecastRequest,
    ForecastResponse,
    Frequency,
    ModelAlias,
    ModelInfo,
    OutOfRange,
    Point,
    Row,
)
from forecast_client.transport import connect, parse, send


def check(
    value,
    pattern,
    what,
) -> None:
    """
    Проверить имя до запроса: оно попадает в путь или query.

    Raises:
        ValueError: значение не строка или не подходит под pattern.
    """

    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        msg = f"{what} {value!r} не подходит под {pattern}"
        raise ValueError(msg)


def catalog(
    http,
    retries,
    desk,
) -> list[ModelInfo]:
    """
    Модели деска, по деску, который вернул сервис.
    """

    body = send(
        http,
        retries,
        "GET",
        "/models",
    )
    return [parse(ModelInfo, item) for item in body if item.get("desk") == desk]


def periods(index, frequency) -> pd.PeriodIndex:
    """
    Периоды из индекса: строки ГГГГ-ММ или ГГГГ, годы числом, даты, периоды.
    """

    return pd.PeriodIndex(pd.to_datetime(index.astype(str)), freq=frequency)


def index_name(frequency) -> str:
    """
    Имя индекса таблиц клиента: month или year.
    """

    return "month" if frequency == Frequency.MONTH else "year"


def rows(factors, frequency=Frequency.MONTH) -> list[dict[str, Any]]:
    """
    Строки запроса из таблицы факторов: периоды — индекс или столбец Date.

    Raises:
        TypeError: не DataFrame;
        ValueError: пустая таблица, нечисловые столбцы, периоды не
            разбираются или повторяются, NaN и бесконечности.
    """

    if not isinstance(factors, pd.DataFrame):
        msg = f"факторы — DataFrame, а не {type(factors).__name__}"
        raise TypeError(msg)
    if "Date" in factors.columns:
        factors = factors.set_index("Date")
    if factors.empty:
        msg = "таблица факторов пустая"
        raise ValueError(msg)
    text = [
        str(name)
        for name in factors.columns
        if not pd.api.types.is_numeric_dtype(factors[name])
    ]
    if text:
        msg = f"нечисловые столбцы: {', '.join(text)}"
        raise ValueError(msg)
    try:
        index = periods(factors.index, frequency)
    except (TypeError, ValueError) as error:
        msg = (
            "периоды — индекс или столбец Date: ГГГГ-ММ или ГГГГ, даты или "
            "периоды"
        )
        raise ValueError(msg) from error
    if index.has_duplicates:
        repeated = ", ".join(map(str, index[index.duplicated()]))
        msg = f"периоды повторяются: {repeated}"
        raise ValueError(msg)

    names = [str(name) for name in factors.columns]
    values = factors.to_numpy(dtype=float)
    bad = [
        f"{period} · {name}"
        for period, row in zip(index, values, strict=True)
        for name, value in zip(names, row, strict=True)
        if not math.isfinite(value)
    ]
    if bad:
        msg = f"NaN или бесконечность: {'; '.join(bad)}"
        raise ValueError(msg)
    return [
        Row(
            period=str(period),
            factors=dict(zip(names, row.tolist(), strict=True)),
        ).model_dump()
        for period, row in zip(index, values, strict=True)
    ]


@dataclass(frozen=True, repr=False)
class Forecast:
    """
    Прогноз модели по периодам сценария.
    """

    commodity: str
    version: str
    alias: str
    points: list[Point]
    ignored_factors: list[str]
    frequency: Frequency = Frequency.MONTH
    # значения вне границ модели: обрезаны или экстраполированы
    warnings: tuple[str, ...] = ()

    def __repr__(self) -> str:
        span = f"{self.points[0].period}–{self.points[-1].period}"
        unit = "месяцев" if self.frequency == Frequency.MONTH else "лет"
        return (
            f"Forecast({self.commodity} v{self.version} @{self.alias}, "
            f"{span}, {unit}: {len(self.points)})"
        )

    def to_frame(self) -> pd.DataFrame:
        """
        Таблица по периодам со столбцом forecast: индекс month или year.
        """

        index = pd.Index([point.period for point in self.points])
        table = pd.DataFrame(
            {"forecast": [point.value for point in self.points]},
            index=periods(index, self.frequency),
        )
        table.index.name = index_name(self.frequency)
        return table


class DeskModel:
    """
    Модель деска на сервисе прогноза.

    Деск задаёт подкласс в репозитории деска (`desk = "agro"`): в запросы
    подставляется только товар. Модель проверяется на сервисе при создании.

    Parameters:
        - commodity: товар, например wheat;
        - host: адрес сервиса; без него — из настроек клиента;
        - alias: версия модели по алиасу;
        - transport: транспорт httpx, только для тестов.

    Raises:
        ValueError: товар, алиас или адрес не по формату;
        ModelNotFoundError: модели нет на сервисе;
        ServiceUnavailableError: сервис не ответил.
    """

    desk: ClassVar[str]

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        check(
            getattr(cls, "desk", None),
            NAME_PATTERN,
            "деск",
        )

    def __init__(
        self,
        commodity,
        host=None,
        alias=ModelAlias.PROD,
        transport=None,
    ) -> None:
        check(
            commodity,
            NAME_PATTERN,
            "товар",
        )
        check(
            alias,
            ALIAS_PATTERN,
            "алиас",
        )
        self.commodity = commodity
        self.alias = alias
        self.http, self.retries = connect(host, transport)
        try:
            self.info = self.refresh()
        except ClientError:
            self.http.close()
            raise

    @classmethod
    def available(cls, host=None, transport=None) -> list[ModelInfo]:
        """
        Модели деска, которые сейчас отдаёт сервис.

        Parameters:
            - host: адрес сервиса; без него — из настроек клиента;
            - transport: транспорт httpx, только для тестов.

        Returns:
            Описания моделей с основным алиасом сервиса.
        """

        http, retries = connect(host, transport)
        with http:
            return catalog(
                http,
                retries,
                cls.desk,
            )

    # Форма JSON-ответа зависит от ручки
    def request(
        self,
        method,
        path,
        payload=None,
    ) -> Any:  # noqa: ANN401
        """
        Запрос к сервису по алиасу модели.
        """

        return send(
            self.http,
            self.retries,
            method,
            path,
            payload,
            params={"alias": self.alias},
        )

    def refresh(self) -> ModelInfo:
        """
        Обновить описание модели: на сервисе могла выйти новая версия.

        Raises:
            ModelNotFoundError: модели или её алиаса нет на сервисе.
        """

        name = f"{self.desk}.{self.commodity}@{self.alias}"
        try:
            info = parse(
                ModelInfo,
                self.request("GET", f"/models/{self.desk}/{self.commodity}"),
            )
        except ModelNotFoundError as error:
            available = catalog(
                self.http,
                self.retries,
                self.desk,
            )
            commodities = [model.commodity for model in available]
            if self.commodity in commodities:
                model = f"{self.desk}.{self.commodity}"
                msg = f"У модели {model} нет алиаса {self.alias}"
                raise ModelNotFoundError(msg) from error
            msg = f"Модели {name} нет на сервисе"
            raise ModelNotFoundError(msg, commodities) from error
        self.info = info
        return info

    def scenario(self) -> pd.DataFrame:
        """
        Базовый сценарий модели: прогнозы факторов из её постановки.

        Returns:
            Факторы по периодам — готовый вход для predict.
        """

        body = parse(
            ForecastRequest,
            self.request(
                "GET", f"/models/{self.desk}/{self.commodity}/scenario"
            ),
        )
        index = pd.Index([row.period for row in body.rows])
        table = pd.DataFrame(
            [row.factors for row in body.rows],
            index=periods(index, self.info.frequency),
        )
        table.index.name = index_name(self.info.frequency)
        return table

    def predict(self, factors, out_of_range=OutOfRange.REJECT) -> Forecast:
        """
        Прогноз на сценарий факторов.

        Parameters:
            - factors: факторы по периодам — индекс или столбец Date;
            - out_of_range: значения вне границ модели (info.bounds) —
                reject: отклонить, clip: считать при границе, extrapolate:
                считать как есть.

        Returns:
            Прогноз, версия модели, неиспользованные факторы и предупреждения
                о значениях вне границ.

        Raises:
            TypeError, ValueError: таблица не годится для запроса,
                out_of_range не из OutOfRange;
            ForecastRequestError: сервис отклонил сценарий.
        """

        body = parse(
            ForecastResponse,
            self.request(
                "POST",
                f"/forecast/{self.desk}/{self.commodity}",
                {
                    "rows": rows(factors, self.info.frequency),
                    "out_of_range": OutOfRange(out_of_range).value,
                },
            ),
        )
        if body.ignored_factors:
            warnings.warn(
                f"{body.model} не использует факторы: "
                f"{', '.join(body.ignored_factors)}",
                stacklevel=2,
            )
        if body.warnings:
            warnings.warn(
                f"{body.model}: {'; '.join(body.warnings)}",
                stacklevel=2,
            )
        return Forecast(
            commodity=self.commodity,
            version=body.version,
            alias=body.alias,
            points=body.forecast,
            ignored_factors=body.ignored_factors,
            frequency=self.info.frequency,
            warnings=tuple(body.warnings),
        )

    def close(self) -> None:
        """
        Закрыть соединения с сервисом.
        """

        self.http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        info = self.info
        return (
            f"{type(self).__name__}({self.commodity} v{info.version} "
            f"@{self.alias}, с {info.first_period}, "
            f"факторов: {len(info.factors)})"
        )
