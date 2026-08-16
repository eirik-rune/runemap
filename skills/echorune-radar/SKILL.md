---
name: echorune-radar
description: "Reads live weather for any place on earth, including radar rendered as text characters instead of an image: current conditions, a short forecast, a 2-hour rain sparkline, and a character radar map with the measured motion of the echo. Use when the user asks about weather, temperature or a forecast somewhere, whether it is raining, whether rain is coming, when it will start or stop, how far away a storm is or which way it is moving - and whenever answering well would otherwise mean looking at a radar picture."
---

```bash
curl echorune.net/tokyo       # or /清迈, /paris/zh, or bare for caller IP
curl echorune.net/139.7,35.7  # longitude first
curl echorune.net/help        # everything else
```

Example reply (map trimmed):

```
# Zürich, Bezirk Zürich, Zurich, CH weather scene
now: PARTLY_CLOUDY_DAY  22C  humidity 79%  wind 4km/h  precip 0.00mm/h
radar: obs            obs age: 0min ok
~6km/char, [><]=Zürich                      (4 of 24 rows)
                              ░▒▒▒█▓▓▒▓▓████░
                             ·░▒▒▒█▓▓█████▒
                   ····      ·  ▒ ·▓█████·
         ▒▒     ·······     ·▒▒░▓▓██▓▓▓█▓
legend: · drizzle  ░ light  ▒ moderate  ▓ heavy  █ storm  blank=no echo
```
