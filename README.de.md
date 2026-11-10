# Speidel Braumeister Home Assistant Integration

[![hacs][hacs-badge]][hacs]
[![GitHub Release][release-badge]][release]
[![License][license-badge]][license]
[![Tests][tests-badge]][tests]

Eine Home Assistant Integration für Speidel Braumeister Brauanlagen über die My Speidel Cloud API. Diese Integration ermöglicht es Ihnen, Ihren Brauvorgang mit Echtzeitdaten und Rezeptinformationen zu überwachen. Noch funktioniert nicht jeder Braumeister, siehe [Geräteanforderungen](#geräteanforderungen).

## Funktionen

### Sensoren

| Sensor | Beschreibung |
|--------|-------------|
| Verbindungsstatus | Zeigt den Verbindungsstatus: `online`, `offline` oder `invalid_uuid` |
| Temperatur | Aktuelle Temperaturmessung vom Braumeister |
| Zieltemperatur | Die Zieltemperatur für die aktuelle Phase |
| Pumpenstatus | Aktueller Pumpenzustand (Ein/Aus) |
| Heizstatus | Aktueller Zustand des Heizelements (Ein/Aus) |
| Prozessstatus | Aktueller Brauprozessstatus: bereit, wartet auf Start (Rezept gewählt), läuft, beendet |
| Aktuelle Phase | Aktuelle Brauphase (Einmaischen, Rast, Kochen, etc.) |
| Verstrichene Phasenzeit | Vom Gerät gemeldete vergangene Rast- oder Kochzeit in Sekunden, auch während Hopfengaben; außerhalb zeitgesteuerter Phasen unbekannt |
| Verbleibende Zeit | Geschätzte verbleibende Zeit für die aktuelle Phase |
| Brauname | Name des aktuellen Braus/Rezepts |
| Gerätetyp | Braumeister-Modell (z. B. "Braumeister 20 Liter") |
| Gerätemodus | Aktueller Modus (Automatik, wartet, etc.) |
| Aktueller Schritt | Vollständiger Schrittname (z. B. "Stone IPA – Einmaischen") |
| Braufortschritt | Fortschrittsprozentsatz des aktuellen Brauvorgangs |
| Zuletzt online | Letzte Zeit, zu der das Gerät online war |
| Rezepte auf dem Gerät | Anzahl der Rezepte auf dem Braumeister; jedes Rezept (Einmaischen, Rasten, Kochzeit, Hopfengaben) steht im Attribut `recipes` |

Die RTC-Diagnose vergleicht die Geräteuhr mit der lokalen Home-Assistant-Zeit anhand frischer, fortschreitender Gerätezeitstempel. **RTC-Abweichung** zeigt Minuten mit Vorzeichen; **RTC prüfen** warnt bei mindestens 6 Minuten absoluter Abweichung über 3 Minuten. Fehlende oder veraltete Daten sind unbekannt, ausgeschaltete Geräte nicht verfügbar. Die Integration stellt die Geräteuhr nicht und versendet keine Benachrichtigungen.

### Binäre Sensoren

| Binärer Sensor | Beschreibung |
|-----------------|-------------|
| Alarm | Wird `an`, wenn der Braumeister einen Alarm zeigt und auf Sie wartet: Einmaischtemperatur erreicht, Rastende erreicht, Deckel entfernen, Hopfengabe oder Brauvorgang beendet. Das Attribut `alarm_type` zeigt, welcher |

#### Alarme

Der Alarm ist `an`, solange der Braumeister piept und auf Sie wartet – dieselbe Regel wie in der My-Speidel-Weboberfläche. Das Attribut `alarm_type` sagt, welcher:

| `alarm_type` | Braumeister zeigt |
|---|---|
| `mash_in_temperature_reached` | Einmaischtemperatur erreicht – Malz einfüllen |
| `rest_end_reached` | Rastende erreicht |
| `remove_lid` | Deckel entfernen (kurz vor dem Kochen) |
| `hop_addition` | Hopfen zugeben |
| `brew_finished` | Brauvorgang beendet |

Beispiel-Automation – eine Push-Nachricht bei jedem Alarm:

```yaml
automation:
  - alias: Braumeister-Alarm
    triggers:
      - trigger: state
        entity_id: binary_sensor.braumeister_alarm
        to: "on"
    actions:
      - action: notify.notify
        data:
          title: Braumeister
          message: "{{ state_attr('binary_sensor.braumeister_alarm', 'alarm_type') | replace('_', ' ') }}"
```

Kurze Alarme wie Hopfengaben können bei der standardmäßigen 30-Sekunden-Abfrage über die Weboberfläche untergehen. Mit der [Braumeister Bridge](#lokaler-modus-braumeister-bridge-optional) meldet sich das Gerät jede Sekunde.

### Rezeptinformationen

Der Sensor "Brauname" enthält zusätzliche Attribute:
- `recipe_slot` - Aus welchem Geräte-Slot (0-8) das Rezept geladen ist
- `recipe_matched` - Ob das Rezept in Ihrem Konto gefunden wurde
- `account_recipe_id` - Die Konto-Rezept-ID wenn gefunden
- `recipe_date` - Rezepterstellungsdatum

### Übersetzungen

Die Integration enthält Übersetzungen für:
- 🇬🇧 Englisch (Standard)
- 🇩🇪 Deutsch

Sensor-Namen werden automatisch in Ihrer Home Assistant-Sprache angezeigt.

## Installation

### Marktplatz (Home Assistant 2026.11 und neuer, empfohlen)

Seit Home Assistant 2026.11 ist HACS als **Marktplatz** fest eingebaut. Diese Integration steht nicht in seiner Standardliste, Sie fügen sie daher über einen Link hinzu:

1. Gehen Sie zu **Einstellungen** > **Marktplatz**
2. Wählen Sie oben rechts das Hinzufügen über einen Link (englisch *Add from link*)
3. Geben Sie `omphteliba/ha-speidel-braumeister` (oder die vollständige GitHub-Adresse) ein und bestätigen Sie. Fragt der Marktplatz nach dem Typ, wählen Sie **Integration**
4. Beim ersten Mal bittet der Marktplatz darum, GitHub zu verbinden: Weiter wählen, den Link öffnen, den angezeigten Code eingeben und bestätigen. Ein Passwort wird in Home Assistant nicht eingegeben
5. Öffnen Sie **Speidel Braumeister** und installieren Sie es (zweimal bestätigen)
6. Richten Sie es wie unter [Konfiguration](#konfiguration) beschrieben ein. Zeigt Home Assistant eine Reparaturmeldung mit der Bitte um einen Neustart, starten Sie zuerst neu

Updates erscheinen unter **Einstellungen** > **Updates**; starten Sie Home Assistant nach einem Update neu.

### HACS (Home Assistant 2026.10 und älter)

1. Öffnen Sie HACS, das ⋮-Menü oben rechts und dann **Benutzerdefinierte Repositories**
2. Geben Sie `https://github.com/omphteliba/ha-speidel-braumeister` ein, wählen Sie die Kategorie **Integration** und klicken Sie auf **Hinzufügen**
3. Suchen Sie nach "Speidel Braumeister", öffnen Sie es und klicken Sie auf **Herunterladen**
4. Starten Sie Home Assistant neu

### Manuelle Installation

1. Kopieren Sie das Verzeichnis `custom_components/speidel_braumeister` in Ihren Home Assistant `custom_components`-Ordner
2. Starten Sie Home Assistant neu

## Konfiguration

### Über die Benutzeroberfläche (Empfohlen)

1. Gehen Sie zu **Einstellungen** > **Geräte & Dienste**
2. Klicken Sie auf **Integration hinzufügen**
3. Suchen Sie nach "Speidel Braumeister"
4. Geben Sie Ihre My Speidel-Anmeldedaten ein:
   - **Benutzername**: Ihr My Speidel-Kontobenutzername
   - **Passwort**: Ihr My Speidel-Kontopasswort
5. Geben Sie die Geräteeinstellungen ein:
   - **Gerätename**: der Name des Geräts in Home Assistant, z. B. „Braumeister“
   - **Machine UUID**: siehe [Finden Ihrer Machine UUID](#finden-ihrer-machine-uuid)
   - **Aktualisierungsintervall**: wie oft Daten abgerufen werden, 10 bis 3600 Sekunden (Standard 30)

Schlägt die Anmeldung fehl, zeigt der Dialog, ob die Zugangsdaten falsch waren oder My Speidel nicht erreichbar war, und Sie können es erneut versuchen. Ein bereits eingerichteter Braumeister lässt sich nicht ein zweites Mal hinzufügen.

Das Aktualisierungsintervall ändern Sie später unter **Einstellungen** > **Geräte & Dienste** > **Speidel Braumeister** > **Konfigurieren**.

Ändern Sie Ihr My-Speidel-Passwort, fordert Home Assistant Sie unter **Einstellungen** > **Geräte & Dienste** auf, die Integration erneut zu authentifizieren. Geben Sie dort das neue Passwort ein; die Integration muss nicht gelöscht und neu eingerichtet werden.

### Integration entfernen

1. Gehen Sie zu **Einstellungen** > **Geräte & Dienste** > **Speidel Braumeister**
2. Klicken Sie auf das ⋮-Menü des Eintrags und wählen Sie **Löschen**
3. Optional: Entfernen Sie die Dateien: im Marktplatz **Speidel Braumeister** öffnen, ⋮ > Deinstallieren (bei älteren Versionen in HACS ⋮ > **Entfernen**), oder den Ordner `custom_components/speidel_braumeister` löschen, und starten Sie Home Assistant neu

Am Braumeister und in Ihrem My-Speidel-Konto ändert sich dadurch nichts. Wenn Sie die Braumeister Bridge nutzen, deinstallieren Sie die App unter **Einstellungen** > **Apps** und stellen Sie den DNS-Server in den WLAN-Einstellungen des Braumeisters wieder auf automatisch.

## Aktionen

### Rezepte hochladen (`speidel_braumeister.upload_recipes`)

Ersetzt **alle** Rezepte im Braumeister durch die übergebene Liste, ohne My Speidel. Nötig ist die [Braumeister Bridge](#lokaler-modus-braumeister-bridge-optional) mit eingeschalteter App-Option `recipe_write_enabled` (standardmäßig aus), und der Braumeister muss das Hauptmenü zeigen, Pumpe und Heizung aus.

| Feld | Bedeutung |
|---|---|
| `recipes` | 1 bis 9 Rezepte in der Reihenfolge der Geräteplätze |
| `config_entry_id` | Nur nötig, wenn Sie mehr als einen Braumeister haben |

Das Format ist dasselbe wie im Attribut `recipes` des Sensors **Rezepte auf dem Gerät**. Am einfachsten kopieren Sie diese Liste (Einstellungen > Entwicklerwerkzeuge > Zustände), ändern sie und laden sie hoch:

```yaml
action: speidel_braumeister.upload_recipes
data:
  recipes:
    - name: Weizen
      mash_in_temperature: 40
      rests:
        - {temperature: 44, minutes: 20}
        - {temperature: 63, minutes: 35}
        - {temperature: 78, minutes: 10}
      boil_minutes: 90
      hop_additions: [90, 15]
```

- `name`: Buchstaben, Ziffern und Satzzeichen ohne Umlaute; längere Namen werden auf 14 Zeichen gekürzt
- `mash_in_temperature` und Rasttemperaturen: 20 bis 80 °C; 1 bis 5 `rests` mit je 1 bis 180 Minuten
- `boil_minutes`: 1 bis 180; optional `boil_temperature`: 95 bis 105 °C (Standard 103)
- `hop_additions`: bis zu 6, in Minuten vor Kochende

Die Aktion wartet, bis der Braumeister jedes Rezept bestätigt hat (etwa 2 Sekunden pro Rezept), und meldet einen Fehler, wenn das ausbleibt. Bricht ein Upload mittendrin ab, enthält das Gerät nur die bis dahin geschriebenen Rezepte; laden Sie dann erneut hoch. Solange die Bridge an My Speidel weiterleitet, kann My Speidel die Liste später wieder durch die Rezepte Ihres Kontos ersetzen.

## Beispiel-Dashboard

[`examples/brewery-dashboard.yaml`](examples/brewery-dashboard.yaml) ist ein fertiges Brauerei-Dashboard: Temperatur-Tacho, Chips für Pumpe/Heizung/Restzeit, Fortschrittsbalken, ein pulsierendes Alarm-Banner mit dem Alarmtext, die Temperaturkurve mit Zielwert sowie das aktuelle Rezept und alle Rezepte auf dem Gerät. Die Texte im Dashboard sind englisch.

Benötigt werden diese Dashboard-Karten aus dem Marktplatz (oder HACS): **Mushroom**, **ApexCharts card**, **Bar Card** und **card-mod**.

1. Einstellungen → Dashboards → Dashboard hinzufügen → Neues Dashboard von Grund auf.
2. Öffnen, ⋮ → Dashboard bearbeiten → ⋮ → Rohkonfigurationseditor, und die Datei einfügen.
3. Die Datei nutzt die Entitäts-IDs einer englischen Installation mit dem Gerätenamen „Braumeister“ (z. B. `sensor.braumeister_temperature`). Heißen Ihre anders – deutsche Namen wie `sensor.braumeister_temperatur` oder ein Zusatz `_2` bei mehreren Geräten –, ersetzen Sie sie; die Liste steht am Anfang der Datei.

## Lokaler Modus: Braumeister Bridge (optional)

Der Braumeister schickt seinen Status etwa jede Sekunde per unverschlüsseltem HTTP an die My-Speidel-Cloud. Die App **Braumeister Bridge** empfängt diese Daten direkt in Home Assistant und reicht sie an My Speidel weiter – App und Weboberfläche funktionieren also weiter:

- Status jede Sekunde statt alle 30 s, kurze Alarme (Hopfengaben) gehen nicht verloren
- Temperatur, Pumpe, Heizung und Alarme funktionieren auch bei Cloud-Ausfall
- die Rezeptliste des Geräts bleibt erhalten, auch wenn es aus ist

**Einrichtung** (nur Home Assistant OS / Supervised):

1. Einstellungen → Apps → App-Store → ⋮ → Repositories → `https://github.com/omphteliba/ha-speidel-braumeister` hinzufügen
2. **Braumeister Bridge** installieren und starten.
3. In den WLAN-Einstellungen des Braumeisters den **DNS-Server** auf die IP Ihres Home Assistant setzen. Nur der Braumeister nutzt ihn.
4. Braumeister aus- und einschalten. Die Integration nutzt die Bridge automatisch (Debug-Log: `Got data via Braumeister Bridge`).

Der Braumeister verbindet sich immer auf Port 80. Nutzt auf Ihrem Home-Assistant-Host schon ein anderer Dienst Port 80 (z. B. `emulated_hue`), siehe die [Dokumentation der App](braumeister_bridge/DOCS.md). Details zum Protokoll: [docs/DEVICE_PROTOCOL.md](docs/DEVICE_PROTOCOL.md).

## Finden Ihrer Machine UUID

Die Machine UUID ist eine eindeutige Kennung für Ihren Braumeister. Die Speidel Cloud API verwendet ein kombiniertes Format.

### Methode 1: Aus dem My Speidel Web Interface HTML (Am zuverlässigsten)

1. Melden Sie sich bei [My Speidel](https://www.myspeidel.com) an
2. Gehen Sie zur Steuerungsseite Ihres Braumeisters
3. Klicken Sie mit der rechten Maustaste auf die Seite und wählen Sie "Seitenquelltext anzeigen" oder "Untersuchen"
4. Suchen Sie im HTML nach `data-machine=` oder `var-device=`
5. Die vollständige Maschinenkennung befindet sich in diesem Attribut

Wenn Sie beispielsweise finden:
```html
<li class="teaser-box-item online" id="device_123" data-machine="1234567890ABCDEF.123" ...>
```

Dann ist Ihre Machine UUID: **`1234567890ABCDEF.123`** (der vollständige `data-machine`-Wert)

### Methode 2: Aus der URL

1. Melden Sie sich bei [My Speidel](https://www.myspeidel.com) an
2. Navigieren Sie zur Steuerungsseite Ihres Braumeisters
3. Schauen Sie sich die URL in der Adressleiste Ihres Browsers an
4. Die Nummer am Ende ist die kurze ID

Beispiel:
```
https://www.myspeidel.com/braumeister/control/123
```

Die kurze ID ist `123`. **Dennoch** kann die API das vollständige kombinierte Format erfordern. Verwenden Sie Methode 1, um die vollständige Kennung zu erhalten.

### Welches UUID-Format soll verwendet werden?

Die Integration unterstützt mehrere UUID-Formate und versucht diese automatisch:
- **Kombiniertes Format** (empfohlen): `1234567890ABCDEF.123`
- **Kurze ID**: `123`
- **Lange UUID**: `1234567890ABCDEF`

**Wir empfehlen die Verwendung des kombinierten Formats** aus dem `data-machine` oder `var device` Attribut für beste Ergebnisse.

## Voraussetzungen

### My Speidel-Konto

Sie benötigen ein **My Speidel-Konto** mit Ihrem registrierten Braumeister. Die Integration verwendet XHR-Polling (die gleiche Methode wie die Weboberfläche), die für alle Benutzer ohne Abonnement funktioniert.

### Geräteanforderungen

- Bekannt funktionierend: Braumeister 20 L mit WLAN-Modul und Braumeister 20 L PLUS, beide mit Firmware V1.1.27. Bekannt noch nicht funktionierend: Braumeister PLUS 50 L mit Firmware 1.8.3 (#7). Andere Modelle und Firmware-Versionen sind ungetestet. Bitte melden Sie, was bei Ihrem Gerät funktioniert. Funktioniert es nicht? Siehe [Hilfe für neuere Braumeister-Modelle](docs/NEW_DEVICES.md) (Englisch): Ein Diagnose-Download genügt uns für den Anfang.
- Gerät mit Ihrem lokalen WLAN-Netzwerk verbunden
- Gerät beim My Speidel Cloud-Dienst registriert

## Funktionsweise

### Priorität der Datenabfrage

Die Integration verwendet mehrere Datenquellen für maximale Zuverlässigkeit:

1. **Braumeister Bridge (optional)** - Lokale Daten direkt vom Gerät, wenn die App installiert ist und Daten empfängt
2. **XHR-Polling** - Gleiche Methode wie vom My Speidel Web Interface verwendet
3. **Device Info JSON** - Zusätzliche Metadaten (Gerätetyp, Modus, Schritt, Fortschritt)
4. **Cloud API v1.0 Zeitreihen (Fallback)** - Nur lesend: Prozess-, Phasen-, Sensor- und Aktordaten, vermutlich nur für neuere Braumeister-Modelle (erfordert möglicherweise ein Abonnement). Die Zuordnung ist eine begründete Annahme, bis Besitzer solcher Geräte sie bestätigen, siehe [Hilfe für neuere Braumeister-Modelle](docs/NEW_DEVICES.md) (Englisch)

### XHR-Polling

Die Integration fragt die Web Interface Endpoints ab, um Echtzeitdaten zu erhalten:

- **Status-Endpoint**: `/braumeister/getDeviceStatusControl/{device_id}`
- **Geräteinfo**: `/braumeister/getDeviceStatus/{device_id}` (JSON mit Metadaten)
- **Rezepte**: `/braumeister/getDeviceRecipes/{machine_id}`
- **Konto-Rezepte**: `/recipes/index/my_recipes`

### Rezept-Abgleich

Die Integration gleicht automatisch auf Ihrem Braumeister-Gerät gespeicherte Rezepte (bis zu 9 Slots) mit Rezepten in Ihrem My Speidel-Konto ab:

1. **Exakter Treffer** - Rezeptnamen stimmen exakt überein (Groß-/Kleinschreibung nicht beachtet)
2. **Partieller Treffer** - Geräte-Rezeptname ist im Konto-Rezeptnamen enthalten (z. B. "Low Rider Pale" passt zu "Low Rider Pale Ale")

Dies ermöglicht es Ihnen, die Konto-Rezept-ID, das Erstellungsdatum und den Stil für das aktuell gebraute Rezept zu sehen.

## Fehlerbehebung

### Verbindungsstatus zeigt "invalid_uuid"

Dies bedeutet, dass die eingegebene Machine UUID nicht von der Speidel Cloud API erkannt wird.

1. Überprüfen Sie die UUID, indem Sie die Schritte im Abschnitt **Finden Ihrer Machine UUID** oben befolgen
2. Stellen Sie sicher, dass Sie das richtige Konto verwenden (dasselbe, in dem Sie Ihren Braumeister auf der My Speidel-Website sehen)

### Verbindungsstatus zeigt "offline"

Dies bedeutet:
- Der Braumeister existiert in Ihrem Konto, sendet aber derzeit keine Daten
- Das Gerät ist möglicherweise ausgeschaltet oder nicht aktiv am Brauen
- Das Gerät ist möglicherweise nicht mit WLAN verbunden

Überprüfen Sie Folgendes:
1. Ihr Braumeister ist eingeschaltet
2. Das Gerät ist mit WLAN verbunden
3. Sie können Live-Daten in der My Speidel App/Website sehen

### Sensoren zeigen "Unbekannt"

Wenn Sensoren nach der Einrichtung "Unbekannt" anzeigen:
1. Überprüfen Sie, ob Ihr Braumeister in der My Speidel App online ist
2. Stellen Sie sicher, dass Ihre Anmeldedaten korrekt sind
3. Überprüfen Sie die Home Assistant-Protokolle auf Fehler
4. Versuchen Sie, die Integration von Einstellungen > Geräte & Dienste neu zu laden

## Debug-Protokollierung

Um die Debug-Protokollierung für diese Integration zu aktivieren, fügen Sie Folgendes zu Ihrer `configuration.yaml` hinzu:

```yaml
logger:
  default: info
  logs:
    custom_components.speidel_braumeister: debug
```

## Unterstützung

Bei Problemen oder Fragen:
- Öffnen Sie ein [Issue im GitHub-Repository](https://github.com/omphteliba/ha-speidel-braumeister/issues)
- Besuchen Sie die [Dokumentation](https://github.com/omphteliba/ha-speidel-braumeister)

## Lizenz

Diese Integration ist unter der [MIT-Lizenz](LICENSE) lizenziert.

Dies ist ein inoffizielles Community-Projekt. Es steht in keiner Verbindung zur Speidel Tank- und Behälterbau GmbH und wird von ihr weder unterstützt noch empfohlen. „Speidel“ und „Braumeister“ sind Marken ihres Inhabers und werden hier nur verwendet, um die unterstützten Geräte zu benennen.

## Danksagung

Danke an die gesamte Home Assistant Community für die Unterstützung und Inspiration!

Dieses Projekt wurde mit KI-Unterstützung entwickelt: die erste Version (bis v2.0.3) mit GLM 5.3 von Z.AI, spätere Änderungen mit Claude von Anthropic. KI-unterstützte Commits sind mit einer `Assisted-by:`-Zeile gekennzeichnet.

[hacs-badge]: https://img.shields.io/badge/Marketplace%20%2F%20HACS-Custom-orange.svg
[hacs]: https://hacs.xyz
[release-badge]: https://img.shields.io/github/v/release/omphteliba/ha-speidel-braumeister?style=for-the-badge
[release]: https://github.com/omphteliba/ha-speidel-braumeister/releases
[license-badge]: https://img.shields.io/github/license/omphteliba/ha-speidel-braumeister?style=for-the-badge
[license]: LICENSE
[tests-badge]: https://github.com/omphteliba/ha-speidel-braumeister/actions/workflows/tests.yml/badge.svg
[tests]: https://github.com/omphteliba/ha-speidel-braumeister/actions/workflows/tests.yml
