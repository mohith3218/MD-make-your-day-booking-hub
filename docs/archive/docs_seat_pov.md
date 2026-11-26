# Seat-to-Screen POV notes

The booking page now shows a live seat-to-screen viewer badge above the AR preview panel. It reads the selected/inspected seat id and computes:

- Row band name (Front bench / Prime center / Mid hall / Back overview) from seat letter
- Distance in meters derived from row index (6.5m + rowIndex * 1.4)
- FOV and Dolby Atmos score from distance

The badge is shown or hidden whenever a seat is hovered or clicked. It uses the same seat data-* attributes the rest of the page uses, so it stays consistent with the inspector card and AR preview.

Trailer modal now shows a status line while the YouTube iframe loads, with different text for a known trailer key vs. a search fallback.
