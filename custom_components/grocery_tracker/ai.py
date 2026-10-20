"""Categorize products with Home Assistant's AI Task integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .categories import CATEGORIES, CATEGORY_DESCRIPTIONS

AI_TASK_DOMAIN = "ai_task"
AI_TASK_SERVICE = "generate_data"
BATCH_SIZE = 40

INSTRUCTIONS = """\
Ordne jedes Produkt eines deutschen Supermarkt-Kassenbons (REWE) einer Warengruppe zu.
Die Produktnamen sind vom Kassensystem abgekürzt, z. B. "KAROTTENKRUEST." =
Karottenkrüstchen (Brötchen), "ROMARISPENTOM." = Romana-Rispentomaten.

Warengruppen:
{categories}

Gib für jedes Feld die passende Warengruppe zurück. Nutze "other" nur, wenn wirklich
keine Gruppe passt."""


def ai_task_available(hass: HomeAssistant) -> bool:
    """Return True if the AI Task integration can be used."""
    return hass.services.has_service(AI_TASK_DOMAIN, AI_TASK_SERVICE)


async def async_categorize(
    hass: HomeAssistant, names: list[str], entity_id: str | None = None
) -> dict[str, str]:
    """Ask the AI for the category of each product name.

    Uses the given AI Task entity, or the preferred one from the AI Task
    settings. Names the AI returns no valid category for are left out.
    """
    instructions = INSTRUCTIONS.format(
        categories="\n".join(f"- {key}: {CATEGORY_DESCRIPTIONS[key]}" for key in CATEGORIES)
    )
    result: dict[str, str] = {}
    for offset in range(0, len(names), BATCH_SIZE):
        batch = names[offset : offset + BATCH_SIZE]
        # Field keys must be plain identifiers, the product name goes into the
        # field description.
        structure = {
            f"p{index}": {
                "description": name,
                "required": True,
                "selector": {"select": {"options": list(CATEGORIES)}},
            }
            for index, name in enumerate(batch)
        }
        data: dict[str, Any] = {
            "task_name": "Grocery Tracker: Warengruppen",
            "instructions": instructions,
            "structure": structure,
        }
        if entity_id is not None:
            data["entity_id"] = entity_id
        response = await hass.services.async_call(
            AI_TASK_DOMAIN, AI_TASK_SERVICE, data, blocking=True, return_response=True
        )
        answer = (response or {}).get("data") or {}
        for index, name in enumerate(batch):
            if (category := answer.get(f"p{index}")) in CATEGORIES:
                result[name] = category
    return result
