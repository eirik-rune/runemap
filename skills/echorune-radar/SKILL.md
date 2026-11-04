---
name: echorune-radar
description: "Reads live weather for any place on earth, including radar rendered as text characters instead of an image: current conditions and air quality, a short forecast, a 2-hour rain sparkline, a character radar map with the measured motion of the echo, and the next 24 hours and 5 days. Use when the user asks about weather, temperature or a forecast somewhere, whether it is raining, whether rain is coming, when it will start or stop, how far away a storm is or which way it is moving - and whenever answering well would otherwise mean looking at a radar picture."
---

```bash
curl echorune.net/tokyo       # or /清迈, /paris/zh, /osaka/ja, or bare for caller IP
curl echorune.net/139.7,35.7  # longitude first
curl echorune.net/help        # everything else
```

Example reply (map and forecast trimmed):

```
# Shanghai, Shanghai Municipality, Shanghai, CN weather scene
now: MODERATE_RAIN  17C  humidity 94%  wind 7km/h  precip 7.28mm/h
feels 17C  today 16~19C  wind SE 7km/h
AQI(CN) 21 excellent  sunrise 06:11  sunset 17:03
peak 7.28mm/h now  chance per 30min: 98% 100% 96% 80%
radar: obs            obs age: 4min ok  obs at: 01:51Z
~6km/char, [><]=Shanghai                    (4 of 24 rows)
     ░░░░░░░░░░░▒▒▒▒▒▓▒▒▓▓▓▒▒░▒▒▒▒▓▓▒▓▓▓▓▓▓▒▒░░░
░░░░░░░▒▒▒▒▒▒▒▒░▒▒▒▒▒▒▓▓><▒▒▒▒▒▓▓▒▓▓▒▓▓▓▓▓▓▓▒░░░
░░░░░▒▒▒▒▒▒▒▓▓▒▒▒▒░░▒▒▓▓▓▓▒░▒▒▓▓▓▓▒░░▒▓▓▒▒▒░░░░░
░░░░░░░░▒▒▒▒▒▒▒▒▒▓▓▒▒▒▓▓▓▒▒▒▓▓▓▓▓▓▒▒▒▒▓▓▓▒▒░░░░░
↘ SE ~17 km/h   echo motion, upstream forecast
legend: · drizzle  ░ light  ▒ moderate  ▓ heavy  █ storm  blank=no echo
next 24h (local time, every 3h):        (2 of 8 rows)
09:00   17C  MODERATE_RAIN        rain 99% 1.2mm/h  AQI 21
12:00   18C  HEAVY_RAIN           rain 80% 8.1mm/h  AQI 19
next 5 days (AQI: the day's highest):    (2 of 5 rows)
11-04 Wed  16~19C  MODERATE_RAIN      rain 70%  AQI 45 excellent
11-05 Thu  16~20C  CLOUDY                       AQI 102 lightly polluted
picture: https://echorune.net/shanghai.png
```

The last line before the source credit links the same weather as one
phone-width picture (`echorune.net/tokyo.png`, `/tokyo/zh.png`, `/tokyo/ja.png`).
It is for a person, not for you: hand them that link when they would rather see
it than read it. Its QR code reopens the latest picture for the same place.
