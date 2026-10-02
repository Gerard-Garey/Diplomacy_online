from __future__ import annotations

import json
import logging
from typing import Any

import requests


LOGGER = logging.getLogger(__name__)


class WebDiplomacyError(RuntimeError):
    pass


class WebDiplomacyClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout: int = 30,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "webdip-bot-service/0.1",
            }
        )

    def _request(
        self,
        method: str,
        route: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        # Le dépôt webDiplomacy utilise normalement ?route=...
        query = dict(params or {})
        query["route"] = route

        LOGGER.debug(
            "%s %s route=%s params=%s",
            method,
            self.api_url,
            route,
            params,
        )

        response = self.session.request(
            method=method,
            url=self.api_url,
            params=query,
            json=payload,
            timeout=self.timeout,
        )

        if not response.ok:
            raise WebDiplomacyError(
                f"API HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise WebDiplomacyError(
                "La réponse de l'API n'est pas du JSON : "
                f"{response.text[:1000]}"
            ) from exc

        # Certaines routes peuvent envelopper les données dans data.
        if isinstance(result, dict) and result.get("success") is False:
            raise WebDiplomacyError(
                json.dumps(result, ensure_ascii=False)
            )

        return result

    def missing_orders(self) -> Any:
        return self._request(
            "GET",
            "players/missing_orders",
        )

    def get_game_data(
        self,
        game_id: int,
        country_id: int,
    ) -> dict[str, Any]:
        result = self._request(
            "GET",
            "game/data",
            params={
                "gameID": game_id,
                "countryID": country_id,
            },
        )

        if not isinstance(result, dict):
            raise WebDiplomacyError(
                f"Format game/data inattendu : {type(result)!r}"
            )

        return result

    def get_game_status(
        self,
        game_id: int,
        country_id: int,
    ) -> dict[str, Any]:
        result = self._request(
            "GET",
            "game/status",
            params={
                "gameID": game_id,
                "countryID": country_id,
            },
        )

        if not isinstance(result, dict):
            raise WebDiplomacyError(
                f"Format game/status inattendu : {type(result)!r}"
            )

        return result

    def submit_orders(
        self,
        *,
        game_id: int,
        country_id: int,
        turn: int,
        phase: str,
        orders: list[dict[str, Any]],
        ready: bool,
    ) -> Any:
        return self._request(
            "POST",
            "game/orders",
            payload={
                "gameID": game_id,
                "turn": turn,
                "phase": phase,
                "countryID": country_id,
                "orders": orders,
                "ready": "Yes" if ready else "No",
            },
        )
