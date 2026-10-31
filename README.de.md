# Speidel Braumeister Home Assistant Integration

[![hacs][hacs-badge]][hacs]
[![GitHub Release][release-badge]][release]
[![License][license-badge]][license]
[![Tests][tests-badge]][tests]

Eine Home Assistant Integration für Speidel Braumeister Brauanlagen über die My Speidel Cloud API. Diese Integration ermöglicht es Ihnen, Ihren Brauvorgang mit Echtzeitdaten und Rezeptinformationen zu überwachen.

## Funktionen

### Sensoren

| Sensor | Beschreibung |
|--------|-------------|
| Verbindungsstatus | Zeigt den Verbindungsstatus: `online`, `offline` oder `invalid_uuid` |
| Temperatur | Aktuelle Temperaturmessung vom Braumeister |
| Zieltemperatur | Die Zieltemperatur für die aktuelle Phase |
| Pumpenstatus | Aktueller Pumpenzustand (Ein/Aus) |
| Heizstatus | Aktueller Zustand des Heizelements (Ein/Aus) |
| Prozessstatus | Aktueller Brauprozessstatus (läuft, wartet, etc.) |
| Aktuelle Phase | Aktuelle Brauphase (Einmaischen, Rast, Kochen, etc.) |
| Verbleibende Zeit | Geschätzte verbleibende Zeit für die aktuelle Phase |
| Brauname | Name des aktuellen Braus/Rezepts |
| Gerätetyp | Braumeister-Modell (z. B. "Braumeister 20 Liter") |
| Gerätemodus | Aktueller Modus (Automatik, wartet, etc.) |
| Aktueller Schritt | Vollständiger Schrittname (z. B. "Stone IPA – Einmaischen") |
| Braufortschritt | Fortschrittsprozentsatz des aktuellen Brauvorgangs |
| Zuletzt online | Letzte Zeit, zu der das Gerät online war |

### Binäre Sensoren

| Binärer Sensor | Beschreibung |
|-----------------|-------------|
| Alarm | Wird `an`, wenn der Braumeister einen Alarm zeigt und auf Sie wartet: Einmaischtemperatur erreicht, Rastende erreicht, Deckel entfernen oder Brauvorgang beendet. Das Attribut `alarm_type` zeigt, welcher |

### Rezeptinformationen

Der Sensor "Brauname" enthält zusätzliche Attribute:
- `recipe_slot` - Welcher Geräte-Slot (0-4) das Rezept geladen ist
- `recipe_matched` - Ob das Rezept in Ihrem Konto gefunden wurde
- `account_recipe_id` - Die Konto-Rezept-ID wenn gefunden
- `recipe_date` - Rezepterstellungsdatum

### Übersetzungen

Die Integration enthält Übersetzungen für:
- 🇬🇧 Englisch (Standard)
- 🇩🇪 Deutsch

Sensor-Namen werden automatisch in Ihrer Home Assistant-Sprache angezeigt.

## Installation

### HACS (Empfohlen)
Da diese Integration nicht im Standard-HACS-Store enthalten ist, müssen Sie sie als benutzerdefiniertes Repository hinzufügen:

1. Öffnen Sie HACS in Home Assistant
2. Gehen Sie zu Integrationen
3. Klicken Sie auf das ⋮-Menü (drei Punkte) in der oberen rechten Ecke
4. Wählen Sie Benutzerdefinierte Repositories
5. Fügen Sie im Repository-Feld ein: https://github.com/omphteliba/ha-speidel-braumeister
6. Wählen Sie im Dropdown-Menü Kategorie: Integration
7. Klicken Sie auf Hinzufügen
8. Suchen Sie nun nach "Speidel Braumeister" und klicken Sie darauf
9. Klicken Sie auf Herunterladen
10. Starten Sie Home Assistant neu

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
5. Geben Sie Ihre Machine UUID ein (siehe unten, wie Sie diese finden)

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

- Speidel Braumeister (jedes Modell mit WiFi-Fähigkeit)
- Gerät mit Ihrem lokalen WLAN-Netzwerk verbunden
- Gerät beim My Speidel Cloud-Dienst registriert

## Funktionsweise

### Priorität der Datenabfrage

Die Integration verwendet mehrere Datenquellen für maximale Zuverlässigkeit:

1. **XHR-Polling (Primär)** - Gleiche Methode wie vom My Speidel Web Interface verwendet
2. **Device Info JSON** - Zusätzliche Metadaten (Gerätetyp, Modus, Schritt, Fortschritt)
3. **Cloud API (Fallback)** - Historische Daten (erfordert möglicherweise Abonnement)

### XHR-Polling

Die Integration fragt die Web Interface Endpoints ab, um Echtzeitdaten zu erhalten:

- **Status-Endpoint**: `/braumeister/getDeviceStatusControl/{device_id}`
- **Geräteinfo**: `/braumeister/getDeviceStatus/{device_id}` (JSON mit Metadaten)
- **Rezepte**: `/braumeister/getDeviceRecipes/{machine_id}`
- **Konto-Rezepte**: `/recipes/index/my_recipes`

### Rezept-Abgleich

Die Integration gleicht automatisch auf Ihrem Braumeister-Gerät gespeicherte Rezepte (Slots 0-4) mit Rezepten in Ihrem My Speidel-Konto ab:

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

## Danksagung

Danke an die gesamte Home Assistant Community für die Unterstützung und Inspiration!

Dieses Projekt wurde mit KI-Unterstützung entwickelt: die erste Version (bis v2.0.3) mit GLM 5.3 von Z.AI, spätere Änderungen mit Claude von Anthropic. KI-unterstützte Commits sind mit einer `Assisted-by:`-Zeile gekennzeichnet.

[hacs-badge]: https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge
[hacs]: https://hacs.xyz
[release-badge]: https://img.shields.io/github/v/release/omphteliba/ha-speidel-braumeister?style=for-the-badge
[release]: https://github.com/omphteliba/ha-speidel-braumeister/releases
[license-badge]: https://img.shields.io/github/license/omphteliba/ha-speidel-braumeister?style=for-the-badge
[license]: LICENSE
[tests-badge]: https://github.com/omphteliba/ha-speidel-braumeister/actions/workflows/tests.yml/badge.svg
[tests]: https://github.com/omphteliba/ha-speidel-braumeister/actions/workflows/tests.yml
