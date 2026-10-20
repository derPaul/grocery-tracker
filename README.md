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

## eBons aus dem E-Mail-Postfach

Grocery Tracker kann eBons direkt aus einem IMAP-Postfach holen: alle 15 Minuten werden Mails
vom eingestellten Absender durchsucht und PDF-Anhänge importiert. Beim ersten Mal werden alle
eBons ab dem gewählten Datum nachgeladen. Das Postfach wird **nur gelesen** – keine Mail wird
als gelesen markiert, verschoben oder gelöscht. Nicht lesbare Anhänge landen im `failed/`-Ordner.

**Einrichtung mit Gmail:**

1. **App-Passwort erstellen:** Google-Konto → Sicherheit → Bestätigung in zwei Schritten
   (muss aktiv sein) → [App-Passwörter](https://myaccount.google.com/apppasswords), z. B.
   „Home Assistant". Das normale Google-Passwort funktioniert nicht.
2. **Filter anlegen (empfohlen):** In Gmail nach `from:ebon@mailing.rewe.de` suchen → Filter
   erstellen → Label „REWE" anwenden, Haken bei „Filter auch auf übereinstimmende Konversationen
   anwenden". Das Label ohne Umlaute benennen.
3. **Postfach hinzufügen:** *Einstellungen → Geräte & Dienste → Grocery Tracker →
   Postfach hinzufügen*: Server `imap.gmail.com`, Port `993`, deine Gmail-Adresse, das
   App-Passwort, Ordner `REWE`, Absender `ebon@mailing.rewe.de` und das Startdatum.

Ohne Filter geht auch Ordner `INBOX` – dann aber nur für Mails, die noch im Posteingang liegen.
Schlägt die Anmeldung später fehl (z. B. App-Passwort widerrufen), erscheint ein Hinweis unter
*Einstellungen → Reparaturen*; über „Postfach ändern" trägst du das neue Passwort ein.

Andere Anbieter funktionieren genauso (z. B. GMX: `imap.gmx.net`, IMAP muss dort in den
Einstellungen aktiviert sein). Es können mehrere Postfächer eingerichtet werden. Das Passwort
wird wie bei der IMAP-Integration von Home Assistant in der Konfiguration gespeichert.

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
| Preis *Produkt* | Letzter Preis eines beobachteten Produkts (siehe unten) |

Einzelne Artikel bekommen bewusst **keine** eigenen Entitäten. Stattdessen:

- **Letzter Einkauf** hat das Attribut `items` mit allen Positionen (Name, Warengruppe, Menge,
  Einheit, Stück-/kg-Preis, Betrag).
- **Ausgaben diesen Monat** hat das Attribut `top_products` mit den 10 Produkten, für die
  diesen Monat am meisten ausgegeben wurde.

Beide Listen werden nicht in der Recorder-Datenbank gespeichert.

## Beobachtete Produkte und Preisverlauf

Unter *Einstellungen → Geräte & Dienste → Grocery Tracker → Konfigurieren* wählst du Produkte
aus, deren Preis du verfolgen willst. Jedes bekommt einen Sensor „Preis *Produkt*" mit dem
letzten Preis (pro Stück bzw. pro kg) und den Attributen `previous_price`, `change_percent`,
`min_price`, `max_price`, `average_price`, `purchases` und `last_seen`. Der Verlauf in Home
Assistant beginnt ab dem Zeitpunkt, an dem du das Produkt auswählst.

Bei jedem Import, der den Preis eines Produkts ändert, wird das Event
`grocery_tracker_price_changed` gefeuert (`product`, `category`, `old_price`, `new_price`,
`change_percent`, `unit`) – für **alle** Produkte, nicht nur beobachtete.

```yaml
# Automation: Benachrichtigung bei Preisänderung ab 10 %
triggers:
  - trigger: event
    event_type: grocery_tracker_price_changed
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.change_percent | abs >= 10 }}"
actions:
  - action: notify.notify
    data:
      message: >
        {{ trigger.event.data.product }}: {{ trigger.event.data.old_price }} € →
        {{ trigger.event.data.new_price }} € ({{ trigger.event.data.change_percent }} %)
```

## Dashboard-Beispiele

Die Entity-IDs können bei dir abweichen – sie stehen unter *Einstellungen → Geräte & Dienste →
Grocery Tracker → Entitäten*.

**Letzter Einkauf mit allen Positionen** (Markdown-Karte):

```yaml
type: markdown
title: Letzter Einkauf
content: |
  {% set bon = 'sensor.grocery_tracker_last_receipt' %}
  **{{ state_attr(bon, 'store') }}** · {{ as_timestamp(state_attr(bon, 'timestamp')) | timestamp_custom('%d.%m.%Y %H:%M') }} · **{{ states(bon) | replace('.', ',') }} €**

  | Artikel | Menge | Preis |
  |:--|--:|--:|
  {% for i in state_attr(bon, 'items') or [] -%}
  | {{ i.name }} | {{ '' if i.total < 0 else (i.quantity | string | replace('.', ',')) ~ ' kg' if i.unit == 'kg' else (i.quantity | int) ~ '×' }} | {{ '%.2f' | format(i.total) | replace('.', ',') }} € |
  {% endfor %}
```

**Top-Produkte diesen Monat** (Markdown-Karte):

```yaml
type: markdown
title: Top-Produkte diesen Monat
content: |
  | Produkt | Käufe | Summe |
  |:--|--:|--:|
  {% for p in state_attr('sensor.grocery_tracker_spending_this_month', 'top_products') or [] -%}
  | {{ p.name }} | {{ p.purchases }} | {{ '%.2f' | format(p.amount) | replace('.', ',') }} € |
  {% endfor %}
```

**Preisverlauf beobachteter Produkte** (Statistik-Diagramm):

```yaml
type: statistics-graph
title: Preisverlauf
chart_type: line
period: day
stat_types: [mean]
entities:
  - sensor.grocery_tracker_price_feine_butter
  - sensor.grocery_tracker_price_fr_weidemilch
```

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
