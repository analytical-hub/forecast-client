import json

import httpx
import pandas as pd
import pytest

from fake_gateway import AgroModel
from forecast_client.exceptions import (
    AuthError,
    ForecastRequestError,
    ModelNotFoundError,
    RateLimitError,
    ServiceError,
    ServiceUnavailableError,
)
from forecast_client.model import DeskModel, Forecast
from forecast_client.schemas import OutOfRange

HOST = "http://service"


@pytest.fixture
def wheat(transport, sent) -> AgroModel:
    model = AgroModel(
        "wheat",
        host=HOST,
        transport=transport,
    )
    sent.clear()
    return model


def scenario_frame(**changes) -> pd.DataFrame:
    frame = pd.DataFrame(
        {"Brent": [70.0, 75.0], "Stocks-to-Use Ratio W": [0.3, 0.31]},
        index=pd.PeriodIndex(
            ["2026-09", "2026-10"],
            freq="M",
            name="month",
        ),
    )
    return frame.assign(**changes)


# Создание и деск


def test_create_loads_info(transport, sent) -> None:
    model = AgroModel(
        "wheat",
        host=HOST,
        transport=transport,
    )

    assert (model.info.desk, model.info.commodity) == ("agro", "wheat")
    assert (model.info.version, model.info.first_period) == ("3", "2026-09")
    assert model.info.factors == ["Brent", "Stocks-to-Use Ratio W"]
    assert [request.url.path for request in sent] == ["/models/agro/wheat"]
    assert repr(model) == "AgroModel(wheat v3 @prod, с 2026-09, факторов: 2)"


def test_unknown_commodity_lists_available(transport) -> None:
    with pytest.raises(
        ModelNotFoundError, match="Доступные товары: wheat"
    ) as error:
        AgroModel(
            "milk",
            host=HOST,
            transport=transport,
        )

    assert error.value.available == ["wheat"]


@pytest.mark.parametrize(
    "commodity",
    ["../metals/gold", "Wheat", "", "wheat/x", "wheat?alias=x", None],
)
def test_bad_commodity_rejected_before_request(
    transport,
    sent,
    commodity,
) -> None:
    with pytest.raises(ValueError, match="товар"):
        AgroModel(
            commodity,
            host=HOST,
            transport=transport,
        )

    assert sent == []


def test_requests_stay_in_agro_desk(wheat, sent) -> None:
    wheat.refresh()
    wheat.predict(wheat.scenario())

    paths = [request.url.path for request in sent]
    assert paths == [
        "/models/agro/wheat",
        "/models/agro/wheat/scenario",
        "/forecast/agro/wheat",
    ]


def test_available_only_agro(transport) -> None:
    models = AgroModel.available(host=HOST, transport=transport)

    assert [(model.desk, model.commodity) for model in models] == [
        ("agro", "wheat"),
    ]


def test_desk_from_subclass(transport, sent) -> None:
    class OilModel(DeskModel):
        desk = "oil"

    model = OilModel(
        "brent",
        host=HOST,
        transport=transport,
    )

    assert [request.url.path for request in sent] == ["/models/oil/brent"]
    assert repr(model) == "OilModel(brent v1 @prod, с 2026-09, факторов: 2)"


@pytest.mark.parametrize(
    "namespace",
    [{}, {"desk": "Agro"}, {"desk": "agro.wheat"}, {"desk": None}],
)
def test_bad_desk_rejected_at_class_definition(namespace) -> None:
    with pytest.raises(ValueError, match="деск"):
        type("BadModel", (DeskModel,), namespace)


def test_alias_sent_with_every_request(transport, sent) -> None:
    model = AgroModel(
        "wheat",
        host=HOST,
        alias="challenger",
        transport=transport,
    )
    result = model.predict(model.scenario())

    assert {request.url.params["alias"] for request in sent} == {"challenger"}
    assert (model.info.version, result.version) == ("4", "4")


@pytest.mark.parametrize("alias", ["prod&x=1", "a" * 65])
def test_bad_alias_rejected_before_request(
    transport,
    sent,
    alias,
) -> None:
    with pytest.raises(ValueError, match="алиас"):
        AgroModel(
            "wheat",
            host=HOST,
            alias=alias,
            transport=transport,
        )

    assert sent == []


# Хост и настройки


def test_explicit_host_beats_settings(
    transport,
    sent,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FORECAST_URL", "http://from-settings:5001")

    AgroModel(
        "wheat",
        host="http://explicit:5001/",
        transport=transport,
    )

    assert str(sent[0].url).startswith("http://explicit:5001/models/agro/wheat")


def test_host_from_settings(
    transport,
    sent,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FORECAST_URL", "http://from-settings:5001")

    AgroModel("wheat", transport=transport)

    assert sent[0].url.host == "from-settings"


@pytest.mark.parametrize("host", ["localhost", "localhost:5001", "ftp://x"])
def test_bad_host_rejected(
    transport,
    sent,
    host,
) -> None:
    with pytest.raises(ValueError, match="адрес сервиса"):
        AgroModel(
            "wheat",
            host=host,
            transport=transport,
        )

    assert sent == []


# Ключ клиента


def test_api_key_sent_with_every_request(
    transport,
    sent,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FORECAST_API_KEY", "secret-key")

    with AgroModel(
        "wheat",
        host=HOST,
        transport=transport,
    ) as model:
        model.predict(model.scenario())

    assert len(sent) == 3
    assert {request.headers["X-API-Key"] for request in sent} == {"secret-key"}


def test_no_api_key_no_header(transport, sent, monkeypatch) -> None:
    monkeypatch.delenv("FORECAST_API_KEY", raising=False)

    AgroModel.available(host=HOST, transport=transport)

    assert "X-API-Key" not in sent[0].headers


def test_rejected_key() -> None:
    response = httpx.Response(
        401,
        json={"detail": "Нужен действующий ключ в заголовке X-API-Key"},
        headers={"WWW-Authenticate": "ApiKey"},
    )
    transport = httpx.MockTransport(lambda _: response)

    with pytest.raises(AuthError, match="FORECAST_API_KEY"):
        AgroModel(
            "wheat",
            host=HOST,
            transport=transport,
        )


@pytest.mark.parametrize(("header", "wait"), [("17", 17), (None, None)])
def test_rate_limit(header, wait) -> None:
    detail = "Не больше 120 запросов в минуту, повторите через 17 с"
    response = httpx.Response(
        429,
        json={"detail": detail},
        headers={"Retry-After": header} if header else {},
    )
    transport = httpx.MockTransport(lambda _: response)

    with pytest.raises(RateLimitError, match="120 запросов") as error:
        AgroModel.available(host=HOST, transport=transport)

    assert error.value.retry_after == wait


# scenario и predict


def test_scenario_frame(wheat) -> None:
    base = wheat.scenario()

    assert list(base.columns) == ["Brent", "Stocks-to-Use Ratio W"]
    assert isinstance(base.index, pd.PeriodIndex)
    assert list(base.index.astype(str)) == ["2026-09", "2026-10"]


def test_predict_base_scenario(wheat) -> None:
    result = wheat.predict(wheat.scenario())

    assert isinstance(result, Forecast)
    assert (result.commodity, result.version, result.alias) == (
        "wheat",
        "3",
        "prod",
    )
    table = result.to_frame()
    assert list(table.columns) == ["forecast"]
    assert table["forecast"].tolist() == pytest.approx([70.3, 75.31])
    assert (
        repr(result) == "Forecast(wheat v3 @prod, 2026-09–2026-10, месяцев: 2)"
    )


def test_unknown_alias(transport) -> None:
    with pytest.raises(
        ModelNotFoundError, match="нет алиаса nonexistent"
    ) as error:
        AgroModel(
            "wheat",
            host=HOST,
            alias="nonexistent",
            transport=transport,
        )

    assert error.value.available == []


def test_stress_far_beyond_history(wheat) -> None:
    result = wheat.predict(scenario_frame(Brent=[10_000.0, 20_000.0]))

    assert result.points[1].value == pytest.approx(20_000.31)


def test_extra_factor_ignored_with_warning(wheat) -> None:
    with pytest.warns(UserWarning, match="Gold"):
        result = wheat.predict(scenario_frame(Gold=1.0))

    assert result.ignored_factors == ["Gold"]


# Границы факторов


@pytest.mark.parametrize(
    ("out_of_range", "sent_as"),
    [
        (None, "reject"),
        ("clip", "clip"),
        (OutOfRange.EXTRAPOLATE, "extrapolate"),
    ],
)
def test_out_of_range_sent(wheat, sent, out_of_range, sent_as) -> None:
    options = {} if out_of_range is None else {"out_of_range": out_of_range}

    wheat.predict(scenario_frame(), **options)

    assert json.loads(sent[-1].content)["out_of_range"] == sent_as


def test_unknown_out_of_range_rejected_before_request(wheat, sent) -> None:
    with pytest.raises(ValueError, match="ignore"):
        wheat.predict(scenario_frame(), out_of_range="ignore")

    assert sent == []


def test_out_of_range_warnings(wheat, service) -> None:
    line = "Brent: 150…150 вне границ [0, 120] в 2026-10 — обрезано до границ"
    service.warnings = [line]

    with pytest.warns(UserWarning, match="обрезано до границ"):
        result = wheat.predict(scenario_frame(), out_of_range="clip")

    assert result.warnings == (line,)


def test_no_bounds_by_default(wheat) -> None:
    assert wheat.info.bounds == {}


@pytest.mark.parametrize(
    "index",
    [
        ["2026-09", "2026-10"],
        pd.to_datetime(["2026-09-01", "2026-10-01"]),
        pd.PeriodIndex(["2026-09", "2026-10"], freq="M"),
    ],
)
def test_month_formats_give_same_request(
    wheat,
    sent,
    index,
) -> None:
    frame = scenario_frame()
    frame.index = index

    wheat.predict(frame)

    assert [row["period"] for row in sent_rows(sent)] == ["2026-09", "2026-10"]


def test_date_column(wheat, sent) -> None:
    frame = scenario_frame().reset_index(drop=True)
    frame.insert(
        0,
        "Date",
        ["2026-09-01", "2026-10-01"],
    )

    wheat.predict(frame)

    assert [row["period"] for row in sent_rows(sent)] == ["2026-09", "2026-10"]


@pytest.mark.parametrize(
    ("factors", "error", "match"),
    [
        ([[70.0]], TypeError, "DataFrame"),
        (pd.DataFrame(), ValueError, "пустая"),
        (
            pd.DataFrame({"Brent": ["много"]}, index=["2026-09"]),
            ValueError,
            "нечисловые",
        ),
        (
            pd.DataFrame({"Brent": [1.0]}, index=["сентябрь"]),
            ValueError,
            "периоды — индекс",
        ),
        (
            pd.DataFrame({"Brent": [1.0, 2.0]}, index=["2026-09", "2026-09"]),
            ValueError,
            "повторяются: 2026-09",
        ),
        (
            pd.DataFrame({"Brent": [float("nan")]}, index=["2026-09"]),
            ValueError,
            "2026-09 · Brent",
        ),
    ],
)
def test_bad_frame_rejected_before_request(
    wheat,
    sent,
    factors,
    error,
    match,
) -> None:
    with pytest.raises(error, match=match):
        wheat.predict(factors)

    assert sent == []


def test_service_rejection_named_by_month(wheat) -> None:
    frame = pd.DataFrame(
        {"Brent": [70.0, 75.0]},
        index=["2026-09", "2026-11"],
    )

    with pytest.raises(ForecastRequestError) as error:
        wheat.predict(frame)

    text = str(error.value)
    assert "2026-11: Ожидался 2026-10" in text
    assert "2026-09 · Stocks-to-Use Ratio W: Field required" in text


# Сеть и жизненный цикл


def failing(*errors) -> httpx.MockTransport:
    """
    Транспорт, который по очереди бросает errors, потом отвечает пустым списком.
    """

    queue = list(errors)

    def handle(request) -> httpx.Response:
        if queue:
            raise queue.pop(0)
        return httpx.Response(
            200,
            json=[],
            request=request,
        )

    return httpx.MockTransport(handle)


def test_unreachable_service() -> None:
    refused = httpx.ConnectError("refused")
    transport = failing(
        refused,
        refused,
        refused,
    )

    with pytest.raises(ServiceUnavailableError, match="порту 6001"):
        AgroModel.available(host="http://service:6001", transport=transport)


def test_read_timeout_not_retried() -> None:
    transport = failing(httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"))

    with pytest.raises(ServiceUnavailableError, match="slow"):
        AgroModel.available(host=HOST, transport=transport)


def test_connect_retried(monkeypatch) -> None:
    monkeypatch.setenv("FORECAST_RETRIES", "2")
    transport = failing(httpx.ConnectError("1"), httpx.ConnectTimeout("2"))

    assert AgroModel.available(host=HOST, transport=transport) == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"detail": "упал"}),
        httpx.Response(200, text="<html>не JSON</html>"),
        httpx.Response(200, json=[{"model": "agro.wheat", "desk": "agro"}]),
    ],
)
def test_bad_service_response(response) -> None:
    transport = httpx.MockTransport(lambda _: response)

    with pytest.raises(ServiceError):
        AgroModel.available(host=HOST, transport=transport)


def test_model_removed_after_create(wheat, service) -> None:
    service.models.clear()

    with pytest.raises(ModelNotFoundError, match=r"agro\.wheat@prod"):
        wheat.predict(wheat.scenario())


def test_context_manager_closes(transport) -> None:
    with AgroModel(
        "wheat",
        host=HOST,
        transport=transport,
    ) as model:
        pass

    assert model.http.is_closed


def sent_rows(sent) -> list[dict]:
    """
    Строки последнего POST-запроса прогноза.
    """

    [request] = [request for request in sent if request.method == "POST"]
    return httpx.Response(200, content=request.content).json()["rows"]


# Годовая модель


class OilModel(DeskModel):
    desk = "oil"


@pytest.fixture
def demand(transport, sent) -> OilModel:
    model = OilModel(
        "demand_gasoline_rus",
        host=HOST,
        transport=transport,
    )
    sent.clear()
    return model


def test_annual_info(demand) -> None:
    assert (demand.info.frequency, demand.info.first_period) == ("Y", "2026")
    assert repr(demand) == (
        "OilModel(demand_gasoline_rus v1 @prod, с 2026, факторов: 2)"
    )


def test_annual_scenario_by_years(demand) -> None:
    base = demand.scenario()

    assert base.index.name == "year"
    assert list(base.index) == list(pd.period_range("2026", "2027", freq="Y"))
    assert list(base.columns) == ["GDP", "POP"]


@pytest.mark.parametrize(
    "index",
    [
        pd.Index([2026, 2027]),
        pd.Index(["2026", "2027"]),
        pd.to_datetime(["2026-01-01", "2027-01-01"]),
        pd.period_range("2026", periods=2, freq="Y"),
    ],
)
def test_year_formats_give_same_request(demand, sent, index) -> None:
    frame = demand.scenario()
    frame.index = index

    demand.predict(frame)

    rows = sent_rows(sent)
    assert [row["period"] for row in rows] == ["2026", "2027"]
    assert all(set(row) == {"period", "factors"} for row in rows)


def test_annual_forecast_frame(demand) -> None:
    forecast = demand.predict(demand.scenario())

    table = forecast.to_frame()
    assert table.index.name == "year"
    assert list(table.index) == list(pd.period_range("2026", "2027", freq="Y"))
    assert table.forecast.tolist() == pytest.approx([6.14, 6.34])
    assert repr(forecast) == (
        "Forecast(demand_gasoline_rus v1 @prod, 2026–2027, лет: 2)"
    )


def test_annual_years_repeat_rejected(demand) -> None:
    frame = demand.scenario()
    frame.index = pd.Index(["2026", "2026"])

    with pytest.raises(ValueError, match="повторяются: 2026"):
        demand.predict(frame)
