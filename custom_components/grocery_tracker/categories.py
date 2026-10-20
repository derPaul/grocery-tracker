"""Product categories and keyword rules.

Receipts print abbreviated, upper-case product names ("BIO H-MILCH 1,5%",
"KAROTTENKRUEST."). The rules below map them to a category by keyword. The
first matching keyword wins, so more specific keywords must come first
(e.g. "KOKOSMILCH" before "MILCH", "CHIPS" before "LINSEN").

Rules are not stored in the database: improving them re-categorizes past
purchases too. Manual and AI assignments are stored; see CategoryResolver for
the order in which assignments, custom categories and rules apply.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class CustomCategory:
    """A category added by the user."""

    key: str
    name: str
    keywords: tuple[str, ...] = ()
    description: str = ""


def normalize_keyword(text: str) -> str:
    """Spell a keyword the way receipts print it: upper case, umlauts as AE/OE/UE."""
    text = text.strip().upper()
    for umlaut, replacement in (("Ä", "AE"), ("Ö", "OE"), ("Ü", "UE"), ("ẞ", "SS"), ("ß", "SS")):
        text = text.replace(umlaut, replacement)
    return text


def parse_keywords(text: str) -> tuple[str, ...]:
    """Split a comma separated keyword list."""
    return tuple(kw for part in text.split(",") if (kw := normalize_keyword(part)))


class CategoryResolver:
    """Decide the category of a product name.

    Order: manual assignment, keywords of custom categories, AI assignment,
    built-in keyword rules, OTHER. Assignments to categories that no longer
    exist (a removed custom category) are ignored.
    """

    def __init__(
        self,
        custom: Sequence[CustomCategory] = (),
        manual: Mapping[str, str] | None = None,
        ai: Mapping[str, str] | None = None,
    ) -> None:
        """Initialize the resolver."""
        self.custom = tuple(custom)
        self.keys: tuple[str, ...] = (*CATEGORIES, *(category.key for category in self.custom))
        self._manual = manual or {}
        self._ai = ai or {}

    def _custom_rule(self, name: str) -> str | None:
        upper = name.upper()
        for category in self.custom:
            if any(keyword in upper for keyword in category.keywords):
                return category.key
        return None

    def resolve(self, name: str) -> str:
        """Return the category key of a product."""
        if (category := self._manual.get(name)) in self.keys:
            return category
        if (category := self._custom_rule(name)) is not None:
            return category
        if (category := self._ai.get(name)) in self.keys:
            return category
        return categorize(name) or OTHER

    def is_unknown(self, name: str) -> bool:
        """Return True if nothing but the fallback OTHER applies to a product."""
        return (
            self._manual.get(name) not in self.keys
            and self._ai.get(name) not in self.keys
            and self._custom_rule(name) is None
            and categorize(name) is None
        )

    def lookup(self, value: str) -> str | None:
        """Return the key for a category key or custom category name, else None."""
        if value in self.keys:
            return value
        folded = value.strip().casefold()
        for category in self.custom:
            if category.name.casefold() == folded:
                return category.key
        return None

    def descriptions(self) -> dict[str, str]:
        """Return a description per category key, for the AI prompt."""
        return {
            **CATEGORY_DESCRIPTIONS,
            **{
                category.key: category.description
                or ", ".join([category.name, *category.keywords]).title()
                for category in self.custom
            },
        }
