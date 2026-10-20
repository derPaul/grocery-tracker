# Grocery Tracker für Home Assistant

Custom Integration, die Supermarkt-Einkäufe aus Quittungen erfasst und als
Sensoren in Home Assistant bereitstellt. Aktuell unterstützt: **REWE eBon (PDF)**.

## Installation

1. Ordner `custom_components/grocery_tracker` nach `/config/custom_components/` kopieren
   (oder das Repo als benutzerdefiniertes HACS-Repository hinzufügen).
2. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Grocery Tracker*.
   Als Eingangsordner ist `/config/grocery_tracker/inbox` vorbelegt.

## Quittungen importieren

- **Eingangsordner:** PDFs in den Eingangsordner legen (z. B. per Samba, File Editor
  oder einer Automation). Alle 5 Minuten werden neue Dateien eingelesen und danach nach
  `archive/` verschoben. Nicht lesbare Dateien landen in `failed/`.
- **Aktion `grocery_tracker.import_receipt`:** importiert eine einzelne Datei sofort und
  liefert das Ergebnis als Response zurück.

```yaml
action: grocery_tracker.import_receipt
data:
  path: /config/grocery_tracker/ebon.pdf
```

Bereits importierte Quittungen (gleicher Markt, gleiche Uhrzeit, gleiche Bon-Nr.) werden
erkannt und nicht doppelt gezählt.

## Produkte auflisten

Die Aktion `grocery_tracker.list_products` liefert alle gekauften Produkte mit Warengruppe,
Anzahl Käufe, letztem Preis (pro Stück bzw. pro kg) und Datum des letzten Kaufs. Optional
filtert `search` nach einem Teil des Namens und `category` nach Warengruppe – z. B.
`category: other` für alle noch nicht eingeordneten Produkte. Am einfachsten unter *Entwicklerwerkzeuge → Aktionen* ausführen.

```yaml
action: grocery_tracker.list_products
data:
  search: milch
```

## Warengruppen

Jedes Produkt wird einer Warengruppe zugeordnet: Obst & Gemüse, Milchprodukte & Eier,
Brot & Backwaren, Fleisch/Fisch & Alternativen, Vorrat, Tiefkühl, Süßes & Snacks, Getränke,
Drogerie & Haushalt, Pfand und Sonstiges. Die Zuordnung erfolgt in dieser Reihenfolge:

1. **Manuell** per Aktion `grocery_tracker.set_category` – hat immer Vorrang.
2. **KI** per Aktion `grocery_tracker.categorize_products` – nutzt die
   [AI-Task-Integration](https://www.home-assistant.io/integrations/ai_task/) (z. B. mit
   Ollama, OpenAI oder Google Gemini) für alle Produkte, die keine Regel kennt. Jedes Produkt
   wird nur einmal angefragt. Läuft nur, wenn du die Aktion startest.
3. **Regeln** nach Stichwörtern im Produktnamen (`categories.py`).

Rabattzeilen zählen zur Warengruppe des Produkts direkt darüber.

```yaml
action: grocery_tracker.set_category
data:
  product: GEM PFAN TOSKANA
  category: frozen
```

Tipp: Mit einer Automation auf das Event `grocery_tracker_receipt_imported` kannst du
`categorize_products` nach jedem Import automatisch ausführen lassen.

## Sensoren

| Sensor | Beschreibung |
|---|---|
| Ausgaben diese Woche | Summe seit Montag |
| Ausgaben diesen Monat | Summe seit dem 1. des Monats |
| Ausgaben letzten Monat | Summe des Vormonats |
| Einkäufe diesen Monat | Anzahl Quittungen |
| Letzter Einkauf | Betrag der letzten Quittung, Attribute: Markt, Zeitpunkt, Anzahl Positionen |
| *Warengruppe* diesen Monat | Ausgaben pro Warengruppe seit dem 1. des Monats (ein Sensor je Gruppe) |

## Event

Nach jedem neuen Import wird `grocery_tracker_receipt_imported` gefeuert
(`uid`, `store`, `timestamp`, `total`, `item_count`), z. B. für Benachrichtigungen.

## Daten

Alle Quittungen inkl. Einzelpositionen liegen in `/config/grocery_tracker.db` (SQLite),
Beträge in Cent. Damit lassen sich später Preisverläufe und Auswertungen pro Produkt bauen.

## Entwicklung

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

Ein neuer Markt braucht einen Parser in `parsers/`, der Text → `Receipt` umwandelt, und
einen Eintrag in `parsers/__init__.py`.
