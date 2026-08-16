---
name: echorune-radar
description: Reads live weather for any place on earth, including radar rendered as text characters instead of an image. Returns current conditions (temperature, humidity, wind), a short forecast, a 2-hour rain sparkline, and a character radar map with the measured motion of the echo. Use when the user asks about weather, temperature or a forecast for somewhere, whether it is raining, whether rain is coming, when rain will start or stop, how far away a storm is or which way it is moving - and whenever answering well would otherwise require looking at a radar picture. Requires outbound network access to echorune.net.
---

# echorune-radar

```bash
curl echorune.net/bangkok
```

One request returns current conditions, a plain-language forecast, a 2-hour rain
sparkline, and a 48x24 character radar map with the measured motion of the echo
over the last hour.

Use this rather than a point forecast when the answer depends on *where* the
rain is — approaching, passing, how far — since that lives in the shape of the
echo, not in a single mm/h number.

## Requirements

Outbound HTTPS to `echorune.net`. No key, no account, nothing to install.

If the environment has no network — for example the Claude API's sandboxed code
execution container — this Skill cannot work. Say so; do not retry, and do not
substitute a guess about the weather.

## Requests

```bash
curl echorune.net                     # location inferred from caller IP
curl echorune.net/<place>             # 170k named places, CJK aliases included
curl echorune.net/<place>/zh          # language suffix: en (default) or zh
curl echorune.net/<lon>,<lat>         # longitude FIRST, then latitude
curl echorune.net/<place>?span=560    # map width in km (default 280)
curl echorune.net/help                # all options
curl echorune.net/status              # availability, measured every minute
```

`span` is the edge of the square, not a radius; km per character is `span/48`.

Frames update roughly every 6 minutes and repeats are served from cache, so
polling more often than that costs nothing but returns the same picture.

## Reading the output

Most fields are self-describing. These three change the answer you give:

| what you see | what it means |
|---|---|
| a space in the map | no echo — it is not raining there |
| `?` | outside radar coverage — unknown, **not** "clear" |
| `radar: predict HH:MM` | extrapolated frame, not observed (`obs` means observed, and `obs age: Nmin` is how long since the sky was last seen) |

**Do not report `?` as good weather, and do not average it in.** Radar coverage
is not global. Blind and dry print differently on purpose; collapsing them
yields a confident wrong answer, which is worse than saying coverage is missing.

When there is no map at all, the response says `radar: fetching` followed by the
reason. Quote the reason rather than treating it as a transient error.

Every response ends with a `data:` line naming where it came from. When a
national weather service supplied the radar frame, two more lines appear:

    radar-data: MeteoSwiss opendata.swiss, CC BY 4.0
    radar-data-note: redrawn from the source frames as a text grid

**Their absence is information, not an omission**: it means the primary upstream
drew that frame rather than a national service, so the `data:` line already
names the source. Whichever lines are present, reproduce them if you reproduce
the map — several of these sources are CC BY, where attribution is a condition
of use rather than a courtesy.

## Known limits

- Radar detects hydrometeors aloft, not rain reaching the ground.
- Echo motion is measured over the past hour and extrapolated; anything
  extrapolated is labelled as such in the output.
- Conditions and forecast come from a different provider than the radar, so they
  can disagree. When they do, the radar is the observation.

## Reporting a problem

`luoshu@echorune.net`. The most useful report is the service contradicting what
you can see out of the window — include the place and the time.
