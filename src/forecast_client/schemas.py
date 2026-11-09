from enum import StrEnum
from typing import Final

from pydantic import BaseModel, Field

# Деск и товар попадают в путь и в имя модели {desk}.{commodity}: латиница,
# цифры, подчёркивание, до 64
NAME_PATTERN: Final = r"^[a-z0-9_]{1,64}$"
ALIAS_PATTERN: Final = r"^[a-z0-9_-]{1,64}$"


class ModelAlias(StrEnum):
    """
    Алиасы версий модели в реестре: выкаченная и кандидат на выкатку.
    """

    PROD = "prod"
    CHALLENGER = "challenger"


class RegistryTag(StrEnum):
    """
    Теги зарегистрированной модели: деск, товар и что это за запись.
    """

    DESK = "desk"
    COMMODITY = "commodity"
    KIND = "kind"


class VersionTag(StrEnum):
    """
    Теги версии модели: где её исполнять и каким SDK она опубликована.

    У весов foundation — sha256 файла.
    """

    RUNTIME = "runtime"
    SDK_VERSION = "sdk_version"
    SHA256 = "sha256"


class ModelKind(StrEnum):
    """
    Записи реестра.

    model и ensemble — товары, которые отдаёт шлюз; member — участник
    ансамбля, его MLServer исполняет только в составе ансамбля; foundation —
    веса, на которые ссылаются модели.
    """

    MODEL = "model"
    ENSEMBLE = "ensemble"
    MEMBER = "member"
    FOUNDATION = "foundation"


class Frequency(StrEnum):
    """
    Частота ряда модели: значение — частота периода pandas.
    """

    MONTH = "M"
    YEAR = "Y"


class Row(BaseModel):
    """
    Период прогноза и значения факторов на него.

    Период — ГГГГ-ММ у помесячной модели, ГГГГ у годовой.
    """

    period: str = Field(
        pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$",
        examples=["2026-09"],
    )
    factors: dict[str, float] = Field(examples=[{"Brent": 107.7}])


class ForecastRequest(BaseModel):
    """
    Периоды прогноза подряд с первого периода после истории модели.
    """

    rows: list[Row] = Field(min_length=1, max_length=240)


class Point(BaseModel):
    """
    Прогноз модели на период.
    """

    period: str
    value: float


class ForecastResponse(BaseModel):
    """
    Прогноз модели {desk}.{commodity} с указанием версии.
    """

    model: str
    version: str
    alias: str
    forecast: list[Point]
    ignored_factors: list[str] = Field(
        description="Факторы запроса, которые модель не использует",
    )


class ModelInfo(BaseModel):
    """
    Загруженная модель и требования к запросу.
    """

    model: str = Field(description="Имя в реестре, {desk}.{commodity}")
    desk: str = Field(pattern=NAME_PATTERN)
    commodity: str = Field(pattern=NAME_PATTERN)
    version: str
    alias: str
    frequency: Frequency = Frequency.MONTH
    first_period: str
    factors: list[str]
