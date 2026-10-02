from __future__ import annotations

import logging
from typing import Any

from src.bots.base import DiplomacyBot
from src.models import BotContext, OrderPayload


LOGGER = logging.getLogger(__name__)


class HoldBot(DiplomacyBot):
    """Bot de validation qui ordonne Hold à toutes ses unités."""

    def choose_orders(self, context: BotContext) -> list[OrderPayload]:
        game_data = self._unwrap_data(context.game_data)

        current_orders = game_data.get("currentOrders", [])
        units = game_data.get("units", {})

        if not isinstance(current_orders, list):
            LOGGER.warning(
                "currentOrders n'est pas une liste : %r",
                type(current_orders),
            )
            current_orders = []

        if not isinstance(units, dict):
            LOGGER.warning(
                "units n'est pas un dictionnaire : %r",
                type(units),
            )
            units = {}

        LOGGER.info(
            "La réponse contient %d ordre(s) candidat(s) et %d unité(s)",
            len(current_orders),
            len(units),
        )

        territory_by_unit_id: dict[str, Any] = {}

        for unit_key, unit in units.items():
            if not isinstance(unit, dict):
                continue

            unit_id = unit.get("id") or unit.get("unitID") or unit_key
            terr_id = unit.get("terrID")

            if unit_id is None or terr_id is None:
                continue

            territory_by_unit_id[str(unit_id)] = terr_id

        LOGGER.info(
            "Correspondance unitID -> terrID : %s",
            territory_by_unit_id,
        )

        result: list[OrderPayload] = []

        for raw_order in current_orders:
            if not isinstance(raw_order, dict):
                continue

            unit_id = raw_order.get("unitID")

            if unit_id is None:
                LOGGER.warning(
                    "Ordre ignoré car sans unitID : %s",
                    raw_order,
                )
                continue

            terr_id = raw_order.get("terrID")

            if terr_id is None:
                terr_id = territory_by_unit_id.get(str(unit_id))

            if terr_id is None:
                LOGGER.warning(
                    "Ordre ignoré : terrID introuvable pour unitID=%s. "
                    "Ordre brut=%s",
                    unit_id,
                    raw_order,
                )
                continue

            result.append(
                {
                    "id": raw_order.get("id"),
                    "unitID": unit_id,
                    "terrID": terr_id,
                    "countryID": raw_order.get(
                        "countryID",
                        str(context.country_id),
                    ),
                    "type": "Hold",
                    "toTerrID": None,
                    "fromTerrID": None,
                    "viaConvoy": None,
                }
            )

        return result

    @staticmethod
    def _unwrap_data(data: dict[str, Any]) -> dict[str, Any]:
        nested_data = data.get("data")

        if isinstance(nested_data, dict):
            return nested_data

        return data
