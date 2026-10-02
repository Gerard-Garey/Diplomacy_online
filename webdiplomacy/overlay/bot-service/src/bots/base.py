from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import BotContext, OrderPayload


class DiplomacyBot(ABC):
    @abstractmethod
    def choose_orders(self, context: BotContext) -> list[OrderPayload]:
        """Retourne les ordres au format attendu par webDiplomacy."""
        raise NotImplementedError
