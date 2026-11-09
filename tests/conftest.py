import httpx
import pytest

from fake_gateway import FakeService


@pytest.fixture
def service() -> FakeService:
    return FakeService(
        {
            "agro.wheat": {"prod": "3", "challenger": "4"},
            "oil.brent": {"prod": "1"},
            "oil.demand_gasoline_rus": {"prod": "1"},
        },
    )


@pytest.fixture
def sent(service) -> list[httpx.Request]:
    return service.sent


@pytest.fixture
def transport(service) -> httpx.MockTransport:
    return httpx.MockTransport(service.handle)
