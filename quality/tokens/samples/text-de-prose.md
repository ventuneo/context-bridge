# Leihbox

Leihbox ist eine Web-App, mit der Nachbarinnen und Nachbarn Werkzeuge, Leitern und Gartengeräte ausleihen können, ohne dass jemand eine Liste auf Papier führen muss. Die App läuft auf einem kleinen Server im Gemeinschaftsraum und funktioniert auch dann, wenn die Internetverbindung ausfällt. Jede Bewegung eines Geräts wird mit Datum, Uhrzeit und Zustand festgehalten.

## Ziele

- Jede Ausleihe ist nachvollziehbar: wer, was, wann und in welchem Zustand.
- Die Rückgabe dauert höchstens eine Minute, auch für ältere Menschen ohne Smartphone.
- Beschädigte Geräte werden sofort gesperrt, bis jemand aus der Hauswartung sie geprüft hat.

## Entscheidungen

- Entscheidung: Wir speichern alles in SQLite, weil der Server keine Wartung braucht und Sicherungen einfach bleiben.
- Die Anmeldung erfolgt mit einer vierstelligen PIN statt mit einem Passwort, weil das Tablet am Eingang gemeinsam genutzt wird.
- Erinnerungen verschicken wir per E-Mail und nicht per SMS, weil das keine laufenden Kosten verursacht.

## Nächste Schritte

1. Die Übersicht der überfälligen Ausleihen für die Hauswartung fertigstellen.
2. Den Import der bestehenden Inventarliste aus der Tabellenkalkulation mit echten Spaltennamen testen.
3. Die Schriftgrösse auf dem Tablet vergrössern und mit drei Personen aus dem Erdgeschoss ausprobieren.

## Offene Fragen

- Brauchen wir eine Kaution für teure Geräte wie die Bohrmaschine oder den Hochdruckreiniger?
- Soll die Verwaltung Zugriff auf die Statistik erhalten, oder verletzt das die Privatsphäre der Bewohnerinnen und Bewohner?

## Annahmen und Unsicheres

- Annahme: Die meisten Ausleihen dauern weniger als eine Woche.
- Unsicher: ob das WLAN im Keller für den Barcode-Scanner zuverlässig genug ist.
- Annahme: Die Gemeinschaftskasse übernimmt Ersatzteile bis zu einem Betrag von 50 Franken pro Monat.
