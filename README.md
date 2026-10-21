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

**Abruf prüfen und auslösen:** Jedes Postfach hat zwei Diagnose-Sensoren: *Letzter Abruf*
(Zeitpunkt, Attribute `new_messages`, `new_receipts`, `error`) und *Status* (`ok`,
`auth_failed`, `folder_not_found`, `unreachable`, `error`). Mit dem Button *Postfächer abrufen* oder
der Aktion `grocery_tracker.check_mailboxes` (liefert das Ergebnis je Postfach zurück) wird
sofort abgerufen. Im Protokoll steht bei jedem Abruf eine Zeile wie
`Mailbox … checked: 1 new messages, 1 new receipts` (Log-Level `info` für
`custom_components.grocery_tracker`).

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

## Statistik abfragen

Die Aktion `grocery_tracker.get_statistics` liefert für einen Zeitraum die Ausgaben, die Zahl der
Einkäufe, die Ausgaben je Warengruppe und die Top-Produkte – insgesamt und je Monat. Der Zeitraum
ist entweder `months` (der laufende und die vorherigen Monate, Standard 1) oder `start`/`end`
(Datum, `end` standardmäßig heute). `top` legt die Zahl der Top-Produkte fest (Standard 10),
`receipts: true` liefert zusätzlich alle Einkäufe im Zeitraum.

```yaml
action: grocery_tracker.get_statistics
data:
  months: 3
  receipts: true
```

Antwort (gekürzt):

```yaml
start: "2024-01-01"
end: "2024-03-20"
total: 31.9
receipts: 3
by_category: {fruit_vegetables: 4.47, dairy_eggs: 9.65, ...}
top_products:
  - {name: BIO H-MILCH 1,5%, category: dairy_eggs, amount: 3.67, purchases: 3}
months:
  - {month: "2024-01", amount: 10.6, receipts: 1, by_category: {...}}
  - ...
receipt_list:
  - {uid: ..., store: REWE, timestamp: "2024-03-19T18:23:00+01:00", total: 10.7, item_count: 7}
```

## Warengruppen

Jedes Produkt wird einer Warengruppe zugeordnet: Obst & Gemüse, Milchprodukte & Eier,
Brot & Backwaren, Fleisch/Fisch & Alternativen, Vorrat, Tiefkühl, Süßes & Snacks, Getränke,
Drogerie & Haushalt, Pfand und Sonstiges – plus beliebig viele **eigene Warengruppen**.
Die Zuordnung erfolgt in dieser Reihenfolge:

1. **Manuell** per Aktion `grocery_tracker.set_category` – hat immer Vorrang.
2. **Stichwörter eigener Warengruppen** (siehe unten).
3. **KI** per Aktion `grocery_tracker.categorize_products` – nutzt die
   [AI-Task-Integration](https://www.home-assistant.io/integrations/ai_task/) (z. B. mit
   Ollama, OpenAI oder Google Gemini) für alle Produkte, die keine Regel kennt. Jedes Produkt
   wird nur einmal angefragt. Läuft nur, wenn du die Aktion startest. Eigene Warengruppen
   kennt die KI auch.
4. **Eingebaute Regeln** nach Stichwörtern im Produktnamen (`categories.py`).

**Eigene Warengruppen** legst du unter *Einstellungen → Geräte & Dienste → Grocery Tracker →
Warengruppe hinzufügen* an: Name, optional Stichwörter (durch Komma getrennt, z. B.
`WINDEL, HIPP`; Umlaute als `UE` wie auf dem Bon oder als `ü`) und optional eine Beschreibung
für die KI. Jede eigene Gruppe bekommt einen Sensor „*Name* diesen Monat". Beim Umbenennen
bleiben Zuordnungen erhalten; wird eine Gruppe gelöscht, fallen ihre Produkte auf die übrigen
Regeln zurück. In `set_category` und `list_products` kannst du eigene Gruppen über ihren
Namen ansprechen.

Rabattzeilen zählen zur Warengruppe des Produkts direkt darüber.

```yaml
action: grocery_tracker.set_category
data:
  product: GEM PFAN TOSKANA
  category: frozen   # oder der Name einer eigenen Warengruppe, z. B. "Baby"
```

Tipp: Mit einer Automation auf das Event `grocery_tracker_receipt_imported` kannst du
`categorize_products` nach jedem Import automatisch ausführen lassen.

## Sensoren

| Sensor | Beschreibung |
|---|---|
| Ausgaben diese Woche | Summe seit Montag |
| Ausgaben diesen Monat | Summe seit dem 1. des Monats |
| Ausgaben letzten Monat | Summe des Vormonats |
| Ausgaben dieses Jahr | Summe seit dem 1. Januar, Attribut `last_12_months` mit Betrag und Anzahl Einkäufe je Monat |
| Einkäufe gesamt | Anzahl aller Quittungen in der Datenbank |
| Einkäufe diesen Monat | Anzahl Quittungen |
| Letzter Einkauf | Betrag der letzten Quittung, Attribute: Markt, Zeitpunkt, Anzahl Positionen |
| *Warengruppe* diesen Monat | Ausgaben pro Warengruppe seit dem 1. des Monats (ein Sensor je Gruppe) |
| Preis *Produkt* | Letzter Preis eines beobachteten Produkts (siehe unten) |

Einzelne Artikel bekommen bewusst **keine** eigenen Entitäten. Stattdessen:

- **Letzter Einkauf** hat das Attribut `items` mit allen Positionen (Name, Warengruppe, Menge,
  Einheit, Stück-/kg-Preis, Betrag).
- **Ausgaben diesen Monat** hat das Attribut `top_products` mit den 10 Produkten, für die
  diesen Monat am meisten ausgegeben wurde.
- **Ausgaben dieses Jahr** hat das Attribut `last_12_months` (Monat, Betrag, Anzahl Einkäufe).

Diese Listen werden nicht in der Recorder-Datenbank gespeichert.

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

**Produkte verfolgen und Warengruppen verwalten** (Entitäten-Karte): Produkt auswählen →
*Produkt verfolgen* legt den Preis-Sensor an, *Produkt nicht mehr verfolgen* entfernt ihn.
Produkt und Warengruppe auswählen → *Warengruppe zuordnen*. Name (und optional Stichwörter)
eintragen → *Warengruppe anlegen*. Fehlt eine Auswahl, zeigt Home Assistant einen Hinweis.

```yaml
type: entities
title: Produkte & Warengruppen
entities:
  - select.grocery_tracker_product
  - button.grocery_tracker_watch_product
  - button.grocery_tracker_stop_watching_product
  - select.grocery_tracker_category
  - button.grocery_tracker_assign_category
  - type: divider
  - text.grocery_tracker_new_category
  - text.grocery_tracker_keywords_for_new_category
  - button.grocery_tracker_create_category
```

Dieselben Funktionen gibt es als Aktionen für Skripte und Automationen:
`grocery_tracker.watch_product`, `grocery_tracker.unwatch_product` (`product`) und
`grocery_tracker.create_category` (`name`, optional `keywords`, `description`).

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

**Ausgaben der letzten 12 Monate** (Markdown-Karte):

```yaml
type: markdown
title: Ausgaben pro Monat
content: |
  | Monat | Einkäufe | Summe |
  |:--|--:|--:|
  {% for m in (state_attr('sensor.grocery_tracker_spending_this_year', 'last_12_months') or []) | reverse -%}
  | {{ m.month[5:] }}/{{ m.month[:4] }} | {{ m.receipts }} | {{ '%.2f' | format(m.amount) | replace('.', ',') }} € |
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
