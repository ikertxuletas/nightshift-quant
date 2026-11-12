from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class Order:
    client_id: str
    strategy_id: int
    instrument: str
    side: int
    units: float
    stop: Optional[float]
    target: Optional[float]


@dataclass(frozen=True)
class Position:
    strategy_id: int
    instrument: str
    side: int
    units: float
    entry_price: float
    stop: Optional[float]
    target: Optional[float]


@dataclass(frozen=True)
class Fill:
    client_id: str
    price: float
    ts: str
    costs: float


class Broker(Protocol):
    name: str

    def is_demo(self) -> bool: ...
    def positions(self) -> list[Position]: ...
    def send(self, order: Order) -> Fill: ...
    def close(self, strategy_id: int, client_id: str) -> Fill: ...
    def advance(self, now) -> list[Fill]: ...
