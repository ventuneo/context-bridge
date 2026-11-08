# Tide Tables

Tide Tables predicts high and low water for small harbours and works completely offline, so skippers can plan a departure even when the mobile network drops out at sea. The predictions come from published harmonic constants that ship with the app and are updated twice a year. Nothing about the boat or its position ever leaves the device.

## Goals

- A skipper sees the next two tides for the selected harbour within one second of opening the app.
- Every prediction shows its source and the date of the constants it was computed from.
- The app never needs an account, and it never sends a location to a server.

## Decisions

- Decision: predictions are computed on the device, because the network is unreliable on the water.
- The constants are stored as plain JSON files, so volunteers can review every change in a pull request.
- We support only harbours with official constants; interpolated stations were rejected after the pilot season.

## Next steps

1. Add the warning banner for spring tides above 4.5 metres.
2. Measure battery use during a twelve-hour passage with the screen dimmed.
3. Write the import check that rejects constant files with missing amplitudes or phases.

## Open questions

- Should the widget show heights in feet for visiting boats from the United Kingdom?
- Is a daily notification useful, or does it train people to ignore every alert?

## Assumptions

- Assumption: most users open the app less than five minutes before they cast off.
- Uncertain: whether the older tablets in the harbour office can render the tide curve smoothly.
