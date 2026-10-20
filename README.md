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

Die Aktion `grocery_tracker.list_products` liefert alle gekauften Produkte mit Anzahl Käufe,
letztem Preis (pro Stück bzw. pro kg) und Datum des letzten Kaufs. Optional filtert `search`
nach einem Teil des Namens. Am einfachsten unter *Entwicklerwerkzeuge → Aktionen* ausführen.

```yaml
action: grocery_tracker.list_products
data:
  search: milch
```

## Sensoren

| Sensor | Beschreibung |
|---|---|
| Ausgaben diese Woche | Summe seit Montag |
| Ausgaben diesen Monat | Summe seit dem 1. des Monats |
| Ausgaben letzten Monat | Summe des Vormonats |
| Einkäufe diesen Monat | Anzahl Quittungen |
| Letzter Einkauf | Betrag der letzten Quittung, Attribute: Markt, Zeitpunkt, Anzahl Positionen |

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
