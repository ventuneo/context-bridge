# Vereinsplaner

Der Vereinsplaner organisiert Trainings, Anmeldungen und Mitgliederbeiträge eines Sportvereins.

## Ziele
- Mitglieder melden sich online für Trainings an.
- Beiträge werden jeden Monat automatisch abgerechnet.

## Regeln
- Personendaten bleiben auf Servern in der Schweiz.
- Keine Werbung und kein Tracking in der App.

## Nächste Schritte
- Anmeldeformular für Trainings fertigstellen.
- Zahlungsanbieter für die Beiträge auswählen.

# Arbeitsregeln

## Regeln
- Texte in der App immer in Schweizer Schreibweise ohne Eszett.
- Jede Änderung an Beiträgen braucht einen Test.

## Konventionen
- Funktionsnamen auf Englisch.

# Notizen

Ziel: Bis Saisonstart im August läuft die Anmeldung für alle Teams.
Status: Prototyp mit zwei Trainingsgruppen.
Nächster Schritt: Testlauf mit der Juniorenabteilung planen.

## Annahmen und Unsicheres
- Annahme: Alle Trainer haben ein Smartphone.
- Offen: ob der Kassier Rechnungen auf Papier braucht.
- Vielleicht kommt später ein Kalenderexport dazu.

## Offene Fragen
- Brauchen wir eine Warteliste für volle Trainings?

# PostgreSQL als Datenbank

## Entscheidung
- PostgreSQL speichert Mitglieder und Beiträge.

## Begründung
- Der Hoster bietet PostgreSQL in der Schweiz an.
