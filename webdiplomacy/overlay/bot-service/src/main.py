from __future__ import annotations

import logging
import sys
import time
from typing import Any

from src.bots.hold_bot import HoldBot
from src.config import Settings
from src.models import BotContext
from src.webdip import WebDiplomacyClient, WebDiplomacyError


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

LOGGER = logging.getLogger("bot-service")


def unwrap_data(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("data")

    if isinstance(nested, dict):
        return nested

    return payload


def find_int(data: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = data.get(key)

        if isinstance(value, int):
            return value

        if isinstance(value, str) and value.lstrip("-").isdigit():
            return int(value)

    return None


def find_string(
    data: dict[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        value = data.get(key)

        if isinstance(value, str) and value:
            return value

    return None


def get_turn_and_phase(
    game_data: dict[str, Any],
) -> tuple[int | None, str | None]:
    turn = find_int(
        game_data,
        "turn",
        "gameTurn",
    )

    phase = find_string(
        game_data,
        "phase",
        "gamePhase",
    )

    context_vars = game_data.get("contextVars")

    if isinstance(context_vars, dict):
        turn = turn if turn is not None else find_int(
            context_vars,
            "turn",
            "gameTurn",
        )

        phase = phase or find_string(
            context_vars,
            "phase",
            "gamePhase",
        )

    return turn, phase


def normalize_missing_orders(
    payload: Any,
) -> list[dict[str, int]]:
    if isinstance(payload, dict):
        nested = payload.get("data")

        if isinstance(nested, list):
            payload = nested

    if not isinstance(payload, list):
        LOGGER.warning(
            "Format players/missing_orders inattendu : %r",
            type(payload),
        )
        return []

    result: list[dict[str, int]] = []

    for item in payload:
        if not isinstance(item, dict):
            continue

        game_id = item.get("gameID")
        country_id = item.get("countryID")

        try:
            game_id = int(game_id)
            country_id = int(country_id)
        except (TypeError, ValueError):
            LOGGER.warning(
                "Entrée missing_orders invalide : %s",
                item,
            )
            continue

        if game_id > 0 and country_id > 0:
            result.append(
                {
                    "gameID": game_id,
                    "countryID": country_id,
                }
            )

    return result


def process_position(
    *,
    client: WebDiplomacyClient,
    api_key: str,
    game_id: int,
    country_id: int,
    bot: HoldBot,
    dry_run: bool,
) -> bool:
    raw_game_data = client.get_game_data(
        game_id=game_id,
        country_id=country_id,
    )

    game_data = unwrap_data(raw_game_data)
    turn, phase = get_turn_and_phase(game_data)

    if turn is None or phase is None:
        LOGGER.error(
            "[%s] turn ou phase introuvable pour gameID=%s countryID=%s",
            api_key,
            game_id,
            country_id,
        )
        return False

    context = BotContext(
        game_id=game_id,
        country_id=country_id,
        turn=turn,
        phase=phase,
        game_data=game_data,
    )

    orders = bot.choose_orders(context)

    if not orders:
        LOGGER.warning(
            "[%s] Aucun ordre généré pour gameID=%s countryID=%s",
            api_key,
            game_id,
            country_id,
        )
        return False

    LOGGER.info(
        "[%s] %d ordre(s) Hold calculé(s) pour gameID=%s "
        "countryID=%s turn=%s phase=%s",
        api_key,
        len(orders),
        game_id,
        country_id,
        turn,
        phase,
    )

    if dry_run:
        LOGGER.info(
            "[%s] Mode dry-run : aucun ordre envoyé.",
            api_key,
        )
        return True

    response = client.submit_orders(
        game_id=game_id,
        country_id=country_id,
        turn=turn,
        phase=phase,
        orders=orders,
        ready=True,
    )

    LOGGER.info(
        "[%s] Ordres acceptés pour gameID=%s countryID=%s : %s",
        api_key,
        game_id,
        country_id,
        response,
    )

    return True


def run_cycle(settings: Settings) -> int:
    bot = HoldBot()
    processed = 0

    for api_key in settings.api_keys:
        client = WebDiplomacyClient(
            api_url=settings.api_url,
            api_key=api_key,
        )

        try:
            missing_payload = client.missing_orders()
            positions = normalize_missing_orders(missing_payload)

            if not positions:
                LOGGER.debug(
                    "[%s] Aucun ordre manquant.",
                    api_key,
                )
                continue

            LOGGER.info(
                "[%s] %d position(s) nécessitent des ordres.",
                api_key,
                len(positions),
            )

            for position in positions:
                try:
                    success = process_position(
                        client=client,
                        api_key=api_key,
                        game_id=position["gameID"],
                        country_id=position["countryID"],
                        bot=bot,
                        dry_run=settings.dry_run,
                    )

                    if success:
                        processed += 1

                except WebDiplomacyError as exc:
                    LOGGER.error(
                        "[%s] Erreur API pour gameID=%s countryID=%s : %s",
                        api_key,
                        position["gameID"],
                        position["countryID"],
                        exc,
                    )

                except Exception:
                    LOGGER.exception(
                        "[%s] Erreur inattendue pour gameID=%s countryID=%s",
                        api_key,
                        position["gameID"],
                        position["countryID"],
                    )

        except WebDiplomacyError as exc:
            LOGGER.error(
                "[%s] Impossible de lire missing_orders : %s",
                api_key,
                exc,
            )

        except Exception:
            LOGGER.exception(
                "[%s] Erreur pendant l'interrogation.",
                api_key,
            )

    return processed


def main() -> int:
    settings = Settings.from_env()

    LOGGER.info(
        "Démarrage multibot : API=%s bots=%s dryRun=%s "
        "poll=%ss runOnce=%s",
        settings.api_url,
        ",".join(settings.api_keys),
        settings.dry_run,
        settings.poll_seconds,
        settings.run_once,
    )

    while True:
        started_at = time.monotonic()
        processed = run_cycle(settings)

        LOGGER.info(
            "Cycle terminé : %d position(s) traitée(s).",
            processed,
        )

        if settings.run_once:
            return 0

        elapsed = time.monotonic() - started_at
        sleep_seconds = max(
            1.0,
            settings.poll_seconds - elapsed,
        )

        time.sleep(sleep_seconds)


if __name__ == "__main__":
    sys.exit(main())
