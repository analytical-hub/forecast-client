import json
from typing import Any

import httpx
import pandas as pd

from forecast_client.model import DeskModel

FACTORS = ["Brent", "Stocks-to-Use Ratio W"]
# Факторы годовых моделей спроса oil.demand_*
DEMAND_FACTORS = ["GDP", "POP"]


class AgroModel(DeskModel):
    """
    Клиент деска, как его объявляет репозиторий деска.
    """

    desk = "agro"


class FakeService:
    """
    Сервис прогноза в памяти: прогноз — сумма факторов модели.

    Модели oil.demand_* годовые, остальные помесячные. Ошибки — в форме
    FastAPI: 404 с detail-строкой, 422 со списком loc и msg.

    Parameters:
        - models: версии по алиасам для каждой модели {desk}.{commodity}.
    """

    def __init__(self, models) -> None:
        self.models = models
        self.sent: list[httpx.Request] = []
        # предупреждения шлюза о значениях вне границ в каждом прогнозе
        self.warnings: list[str] = []

    def handle(self, request) -> httpx.Response:
        self.sent.append(request)
        path = request.url.path.strip("/").split("/")
        if path == ["models"]:
            catalog = [self.info(name, "prod") for name in self.models]
            return httpx.Response(200, json=catalog)
        name, alias = ".".join(path[1:3]), request.url.params["alias"]
        info = self.info(name, alias)
        if info is None:
            detail = f"Модели {name}@{alias} нет в реестре"
            return httpx.Response(404, json={"detail": detail})
        if path[0] == "forecast":
            rows = json.loads(request.content)["rows"]
            return self.forecast(info, rows)
        if path[-1] == "scenario":
            scenario = (
                {
                    "2026": {"GDP": 6.0, "POP": 0.14},
                    "2027": {"GDP": 6.2, "POP": 0.14},
                }
                if info["frequency"] == "Y"
                else {
                    "2026-09": {"Brent": 70.0, "Stocks-to-Use Ratio W": 0.3},
                    "2026-10": {"Brent": 75.0, "Stocks-to-Use Ratio W": 0.31},
                }
            )
            body = [{"period": p, "factors": f} for p, f in scenario.items()]
            return httpx.Response(200, json={"rows": body})
        return httpx.Response(200, json=info)

    def info(self, name, alias) -> dict[str, Any] | None:
        versions = self.models.get(name, {})
        if alias not in versions:
            return None
        desk, commodity = name.split(".")
        found = {
            "model": name,
            "desk": desk,
            "commodity": commodity,
            "version": versions[alias],
            "alias": alias,
        }
        if commodity.startswith("demand_"):
            return found | {
                "frequency": "Y",
                "first_period": "2026",
                "factors": DEMAND_FACTORS,
            }
        return found | {
            "frequency": "M",
            "first_period": "2026-09",
            "factors": FACTORS,
        }

    def forecast(self, info, rows) -> httpx.Response:
        first = pd.Period(info["first_period"], freq=info["frequency"])
        factors = info["factors"]
        problems = []
        for number, row in enumerate(rows):
            expected = str(first + number)
            if row["period"] != expected:
                problems.append(
                    {
                        "loc": ["body", "rows", number, "period"],
                        "msg": f"Ожидался {expected}",
                    },
                )
            problems += [
                {
                    "loc": ["body", "rows", number, "factors", name],
                    "msg": "Field required",
                }
                for name in factors
                if name not in row["factors"]
            ]
        if problems:
            return httpx.Response(422, json={"detail": problems})
        used = set(factors)
        sent = {name for row in rows for name in row["factors"]}
        forecast = [
            {
                "period": row["period"],
                "value": sum(row["factors"][name] for name in factors),
            }
            for row in rows
        ]
        return httpx.Response(
            200,
            json={
                "model": info["model"],
                "version": info["version"],
                "alias": info["alias"],
                "forecast": forecast,
                "ignored_factors": sorted(sent - used),
                "warnings": self.warnings,
            },
        )
