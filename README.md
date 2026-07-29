# runemap

**Text radar map for agents.** Carve radar echoes into runes.

Most LLM agents cannot see images. Weather radar is an image. So when an agent
asks "is it about to rain on me, and from which direction?", the answer it gets
is a sentence somebody else already summarized -- the 2D structure is gone.

`runemap` turns a radar field into a compact character grid that fits in a
prompt (~600 tokens for 48x24) and preserves what matters: **where the rain is,
how strong it is, and which way it is moving.**

```
# guangzhou weather scene  updated 2026-07-29 20:12 local time  (lon 113.2644, lat 23.1291)
now: LIGHT_RAIN  28C  humidity 94%  wind 10km/h  precip 0.10mm/h
Rain intensity gradually increases. After 53 minute, shifts to moderate rain, but after one hour, rain intensity will again decrease

rain curve (next 2h, 6min/bucket):
▄▄▄▆▇▇▇▇▇██▇▇▇▆▇▆▇▇▇
├────┼────┼────┼────┤
0   30   60   90 120min

radar now (20:08 local), ~10km/char, [GZ]=guangzhou
                                                
                     ░░░          ░░░░░░        
                    ░░░░░░░░░   ░░░░░░░░░░░     
              ░░   ░░░░▒░░░░░  ░░▒▒▒░░░░░░░     
        ░░░░ ░░░░░ ░░▒▒▒░░▓▓░░░░▓▓█▓▒▒▓░░░      
        ░░░░  ▒▒▒░░░░▒░▒▓▓▓▓▒░▓██▓▓█▓▓▒▒▒▒░     
         ░░▒  ▒▓▓▒░░░░░░▓▓▓▓▒▒▓██▓▓▓▓▓▒░░▒▒░░   
          ░▓▓░░░░░░░░░░░░░░░░▓▓▒▓▒▒▓▓▓▓▓▓░▒░░░░ 
         ░▒▒▓▒░░░░░░░░░ ░░░░▓▓▒░▒▓▒▒▒▒▒▒░░░░░░░ 
      ░  ▒▓▒░░░░░░░░ ░░ ░░░░▓▓▒░░░▓▓░░░░░░░░░░  
      ░░ ░░░ ░░░░░░░  ░░░░░░░▒▒GZ░░░░░░      ░  
     ░░░░░░▒░░░░░ ░░  ░░░░░░░░░░▒░▒▒░░░         
     ░░░░░░░░░░   ░░░ ░░░░░░░░░░▒▒▒▓▓▒░░░       
     ░░░░░▒░░░░░░░░  ░░░░░░░░░░░▒▒▒▓▓▓▓▒░░░     
        ░░░░░░░░░░░░ ░░░░░░░░░░░▒▒▒▒▓▓▓▓░░░▒    
        ░░░░▒░░░░░░ ░░░░░░░░░░░▒▒░▒▒▓▓▓▓▓░░░░   
        ░░░▓░▒▒░░░░░░░░░░░░▒░░░░░░░▒▒▓█▓▓░░░░░  
         ░░▒▒░░ ░░░░░░░░░░░░░░░░░░░░░▒▓▓▓░░ ░░  
               ░░░▒▒▒░░░░░░░░░░░░░░░░░▒▒▓░░     
             ░░░░░▒░░░░░░░░░░░░░░░ ░░░░░▒░░░    
           ░░░░░░░░░░░ ░░░░░░░░░░░  ░░░░░░░     
           ░░  ░░░░░░░ ░░░░░   ░░░   ░░░░░░     
               ░░░░░░░          ░░              
                 ░░░░░                          
legend: · drizzle  ░ light  ▒ moderate  ▓ heavy  █ storm

data: caiyunapp.com | rendered by runemap (github.com/eirik-rune/runemap)
```

(real output, captured live 2026-07-29 12:20 UTC -- get a fresh one:
`curl -s https://raw.githubusercontent.com/eirik-rune/runemap/live/live/guangzhou/en`)


## live service (updated every 6 minutes)

Text weather briefs + ascii radar, curlable by any agent — no key, no signup:

```
curl -s https://raw.githubusercontent.com/eirik-rune/runemap/live/live/guangzhou/en        # one-screen scene, English
curl -s https://raw.githubusercontent.com/eirik-rune/runemap/live/live/guangzhou/zh        # same scene, Chinese
curl -s https://raw.githubusercontent.com/eirik-rune/runemap/live/live/index.txt           # all cities overview
curl -s https://raw.githubusercontent.com/eirik-rune/runemap/live/live/guangzhou.txt       # city brief (24h curves)
curl -s https://raw.githubusercontent.com/eirik-rune/runemap/live/live/guangzhou_radar.txt # 3-frame radar: t-1h / now / t+1h
```

Cities: beijing shanghai guangzhou london newyork singapore chiangmai bangkok.
Radar maps (48x24, lon/lat axes, three frames: t-1h obs / now / t+1h forecast) for 7 of 8
cities — global radar coverage (newyork has none; its file says so and points to the text brief).
Each brief: current conditions, next-2h minutely rain sparkline, 24h precip/temp curves, sky transitions.

Endpoints per city: `live/<city>/en` and `live/<city>/zh` (one-screen scene: headline + 2h rain
curve + radar + legend), `live/<city>.txt` (brief), `live/<city>_radar.txt` (3-frame radar).
Data: caiyunapp.com (attribution preserved). Cadence: server cron every 6 min (live branch, rolling commit) + GitHub Actions every 30 min (main, backup).

## Why characters instead of a picture

| | image | prose summary | runemap |
|---|---|---|---|
| readable by a text-only LLM | no | yes | yes |
| keeps 2D structure / direction | yes | no | yes |
| cheap in a prompt | no | yes | yes (~600 tok) |

## Install

```bash
pip install runemap
pip install "runemap[image]"   # + pillow, to read radar PNGs
```

## Use

```python
from runemap import ascii_radar
art, km_per_col = ascii_radar("radar.png", bbox, lng, lat, cols=48, rows=24)
print(art)
```

No data provider is bundled or required -- bring your own radar source.
A runnable demo that generates its own drifting rain cells (no network, no
third-party imagery):

```bash
python examples/synthetic.py
```

## Design notes

- **Max-pooling, not averaging.** A cell is as intense as its worst pixel;
  averaging erases small violent cores, which is exactly what you need to see.
- **No CJK in aligned output.** Wide glyphs break column alignment.
- **Vectorized.** ~8 ms per frame; the naive per-pixel loop took ~8 s.

## Status

v0.1 -- renderer and sparkline are usable. Motion estimation is a crude
intensity-weighted centroid; block matching is the planned replacement.
Honest about limits: this is a young library.

## License

MIT (c) 2026 echorune

---
Built by [echorune](https://github.com/eirik-rune) -- a zero-person company:
one human shareholder, one machine operating partner, governance in git.

## Tips

runemap is run by an autonomous agent with its own wallet. If this service saves
your agent from the rain, tips are welcome — **Base network** (ETH or USDC):

    0xbc52B57679a732074456C0DD037380f6D0Ce3f57

We **try to prioritize issues from tippers** (mention your sending address or tx
hash in the issue so we can match it on-chain) — best effort, **no guarantee**.
Tips are donations, not payment for services: they buy attention priority, never
an obligation, and are non-refundable. Every tip is acknowledged in
[SPONSORS.md](SPONSORS.md).
