---
name: echorune-radar
description: Reads live weather for any place on earth, including radar rendered as text characters instead of an image. Returns current conditions (temperature, humidity, wind), a short forecast, a 2-hour rain sparkline, and a character radar map with the measured motion of the echo. Use when the user asks about weather, temperature or a forecast for somewhere, whether it is raining, whether rain is coming, when rain will start or stop, how far away a storm is or which way it is moving - and whenever answering well would otherwise require looking at a radar picture. Requires outbound network access to echorune.net.
---

```bash
curl echorune.net/<place>        # e.g. /tokyo, /清迈, /paris/zh
curl echorune.net                # location inferred from caller IP
curl echorune.net/<lon>,<lat>    # longitude FIRST
curl echorune.net/help           # every option, including map width
curl echorune.net/status         # availability, sampled every minute
```

Example — `curl echorune.net/zurich` (map trimmed to 4 of 24 rows):

```
# Zürich, Bezirk Zürich, Zurich, CH weather scene
# updated 2026-08-16 09:07 UTC+2  (lon 8.55, lat 47.36667)
now: PARTLY_CLOUDY_DAY  22C  humidity 79%  wind 4km/h  precip 0.00mm/h

radar: obs            obs age: 0min ok
~6km/char, [><]=Zürich, Bezirk Zürich, Zurich, CH
                              ░▒▒▒█▓▓▒▓▓████░   
                             ·░▒▒▒█▓▓█████▒     
                   ····      ·  ▒ ·▓█████·      
         ▒▒     ·······     ·▒▒░▓▓██▓▓▓█▓       
legend: · drizzle  ░ light  ▒ moderate  ▓ heavy  █ storm  blank=no echo
```

Plain text, no key, nothing to install. Needs outbound HTTPS; where there is no
network, say so instead of guessing at the weather.

The response carries its own legend and labels its own frames. Two things it
cannot tell you about itself:

- **`?` is not clear sky.** It means outside radar coverage. Never average it in
  or report it as good weather — blind and dry are printed differently on
  purpose, and collapsing them gives a confident wrong answer.
- **If you reproduce the map, carry the `data:` and `radar-data:` lines with
  it.** Several of these sources are CC BY, where attribution is a condition of
  use rather than a courtesy.
