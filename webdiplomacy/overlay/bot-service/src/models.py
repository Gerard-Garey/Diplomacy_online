from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BotContext:
    game_id: int
    country_id: int
    turn: int
    phase: str
    game_data: dict[str, Any]


OrderPayload = dict[str, Any]
