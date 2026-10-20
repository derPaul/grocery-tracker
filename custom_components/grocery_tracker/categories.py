"""Product categories and keyword rules.

Receipts print abbreviated, upper-case product names ("BIO H-MILCH 1,5%",
"KAROTTENKRUEST."). The rules below map them to a category by keyword. The
first matching keyword wins, so more specific keywords must come first
(e.g. "KOKOSMILCH" before "MILCH", "CHIPS" before "LINSEN").

Rules are not stored in the database: improving them re-categorizes past
purchases too. Manual and AI assignments are stored and take precedence.
"""

from __future__ import annotations

FRUIT_VEGETABLES = "fruit_vegetables"
DAIRY_EGGS = "dairy_eggs"
BAKERY = "bakery"
MEAT_FISH = "meat_fish"
PANTRY = "pantry"
FROZEN = "frozen"
SNACKS_SWEETS = "snacks_sweets"
BEVERAGES = "beverages"
DRUGSTORE_HOUSEHOLD = "drugstore_household"
DEPOSIT = "deposit"
OTHER = "other"

CATEGORIES: tuple[str, ...] = (
    FRUIT_VEGETABLES,
    DAIRY_EGGS,
    BAKERY,
    MEAT_FISH,
    PANTRY,
    FROZEN,
    SNACKS_SWEETS,
    BEVERAGES,
    DRUGSTORE_HOUSEHOLD,
    DEPOSIT,
    OTHER,
)

# Short descriptions for the AI prompt.
CATEGORY_DESCRIPTIONS: dict[str, str] = {
    FRUIT_VEGETABLES: "Obst, Gemüse, Salat, Kräuter",
    DAIRY_EGGS: "Milch, Joghurt, Quark, Käse, Butter, Sahne, Eier",
    BAKERY: "Brot, Brötchen, Brezeln, Toast, Kuchen, Zwieback",
    MEAT_FISH: "Fleisch, Wurst, Fisch, Tofu und Fleischersatz",
    PANTRY: "Nudeln, Reis, Mehl, Konserven, Öl, Gewürze, Müsli, Aufstriche",
    FROZEN: "Tiefkühlprodukte (Pizza, Gemüsepfannen, Pommes, Eis)",
    SNACKS_SWEETS: "Süßigkeiten, Schokolade, Kekse, Chips, Knabberzeug",
    BEVERAGES: "Getränke inkl. Tee, Kaffee, Säfte, Sirup",
    DRUGSTORE_HOUSEHOLD: "Drogerie, Körperpflege, Putzmittel, Papierwaren",
    DEPOSIT: "Pfand und Leergut",
    OTHER: "passt in keine andere Kategorie",
}

_RULES: tuple[tuple[str, str], ...] = (
    *((kw, DEPOSIT) for kw in ("PFAND", "LEERGUT")),
    *(
        (kw, DRUGSTORE_HOUSEHOLD)
        for kw in (
            "SEIFE",
            "ZEWA",
            "TASCHENTUECH",
            "SPUELMITTEL",
            "SHAMPOO",
            "DUSCH",
            "ZAHNPASTA",
            "ZAHNCREME",
            "WASCHMITTEL",
            "TOILETTENPAPIER",
            "KUECHENROLLE",
            "MUELLBEUTEL",
        )
    ),
    *(
        (kw, SNACKS_SWEETS)
        for kw in ("CHIPS", "SCHOKO", "UE-EI", "KEKS", "GUMMI", "RIEGEL", "BONBON", "FLIPS")
    ),
    *(
        (kw, MEAT_FISH)
        for kw in ("WURST", "WIENER", "SCHINKEN", "SALAMI", "HAEHNCHEN", "LACHS", "TOFU")
    ),
    *(
        (kw, BEVERAGES)
        for kw in (
            "TEE",
            "YOGI",
            "WASSER",
            "SAFT",
            "SCHORLE",
            "NEKTAR",
            "SMOOTHIE",
            "SIRUP",
            "KAFFEE",
            "COLA",
            "LIMO",
            "BIER",
        )
    ),
    *(
        (kw, BAKERY)
        for kw in (
            "BROT",
            "BROE",
            "BREZEL",
            "WECK",
            "KRUEST",
            "TOAST",
            "SANDWICH",
            "ZWIEBACK",
            "CROISSANT",
            "KUCHEN",
        )
    ),
    ("KOKOSMILCH", PANTRY),
    *(
        (kw, DAIRY_EGGS)
        for kw in (
            "MILCH",
            "BUTTER",
            "QUARK",
            "JOGHURT",
            "SAHNE",
            "KAESE",
            "MOZZAR",
            "GOUDA",
            "LEERDAMMER",
            "MEGGLE",
            "EIER",
        )
    ),
    *((kw, FROZEN) for kw in ("TIEFKUEHL", "PIZZA", "POMMES")),
    *(
        (kw, PANTRY)
        for kw in ("NUDEL", "FARFALLE", "SPAGHETTI", "PENNE", "LINSEN", "MEHL", "HONIG", "MUESLI")
    ),
    *(
        (kw, FRUIT_VEGETABLES)
        for kw in (
            "APFEL",
            "GRANATAP",
            "BANANE",
            "BEERE",
            "MANDARINE",
            "ORANGE",
            "ZITRONE",
            "MANGO",
            "TRAUBE",
            "BIRNE",
            "TOMATE",
            "RISPENTOM",
            "KAROTTE",
            "GURKE",
            "PAPRIKA",
            "ZWIEBEL",
            "KARTOFFEL",
            "SALAT",
            "AVOCADO",
        )
    ),
)


def categorize(name: str) -> str | None:
    """Return the category for a product name, or None if no rule matches."""
    upper = name.upper()
    for keyword, category in _RULES:
        if keyword in upper:
            return category
    return None


def resolve_category(name: str, assigned: dict[str, str]) -> str:
    """Return the stored (manual / AI) category, else the rule, else OTHER."""
    return assigned.get(name) or categorize(name) or OTHER
