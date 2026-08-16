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

radar: obs 20:08 local, obs age: 4min, ~10km/char, [GZ]=guangzhou
                                                
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

(Format example, deliberately frozen -- a pasted "live" sample starts lying
six minutes after it is pasted. For the real thing, run the curl:
curl echorune.net/guangzhou)


## install it as an Agent Skill

If you are an agent, or you run one, you can keep this instead of remembering
a URL:

    npx skills add https://github.com/eirik-rune/runemap --skill echorune-radar

That installs [`skills/echorune-radar/SKILL.md`](skills/echorune-radar/SKILL.md),
which is also served live at `curl echorune.net/skill.md` -- one file, not a
copy of one. It teaches an agent the request forms and, more importantly, how to
read the reply: a space means no echo, `?` means *outside radar coverage*. Those
are different states and print differently on purpose, because collapsing them
turns "I cannot see there" into "it is fine there".

No key, no account, no SDK. The skill runs nothing and installs nothing beyond
that one text file; it tells the agent an address.

## the service: echorune.net

    curl echorune.net                 # your location, guessed from your IP
    curl echorune.net/bangkok         # by name
    curl echorune.net/bangkok/zh      # language suffix: en (default) | zh
    curl echorune.net/100.50,13.75    # by coordinate (lon first)
    curl echorune.net/help            # full door plate
    curl echorune.net/healthz

Path style exists for a reason: `&` is a shell operator, so `?q=x&lang=zh` has
to be quoted, and that is where agent-generated curl commands die most often.
A path needs no quotes. The query form keeps working forever, with no redirect
to it: LLM agents do not follow 301 by default.

Coordinates are `lon,lat` -- longitude first, the order Caiyun and Dark Sky
take, and the order this service's own first line has always printed. It used to
guess instead, swapping when a value exceeded 90; the guess fell silent exactly
where both numbers are <= 90, which is the Americas and Europe, so `/-74.0,40.7`
meaning New York answered 200 with a map of the Southern Ocean. A latitude
outside -90..90 is a 400 now, carrying the convention and a corrected command to
copy. Nobody can do better than that: someone who really means that stretch of
ocean types the same bytes, so the place name in the first line is what shows a
reader where the answer came from.

IP to coordinate is a local lookup (DB-IP City Lite, CC-BY, ~0.5ms), never a
third-party call; the label then comes from GeoNames in either language, so the
two capabilities compose instead of overlapping. A guess says it is a guess and
prints the one-line escape. The access log stores only the first three octets.

## any coordinate

The service above renders any point on demand. To render one yourself, without
the service, bring your own caiyunapp.com token:

    CAIYUN_TOKEN=xxx python3 scripts/scene_at.py --lat 18.7883 --lon 98.9853 --lang zh

Flags: `--lang en|zh`, `--label NAME` (shown in the headline), `--tz HOURS`
(default `lon/15`), `--code XX` (2-char marker drawn at the point).

Radar PNGs are cached in `~/.cache/runemap` (30 min; radar index 5 min; current
weather is never cached). Override the path with `RUNEMAP_CACHE`.

## place names (offline geocoding)

Agents ask "is it raining in Bangkok", not "100.50,13.75". So names work too:

    python3 scripts/build_geo.py          # once: builds ~/geonames/geo.sqlite (~65MB)
    CAIYUN_TOKEN=xxx python3 scripts/serve.py     # binds 127.0.0.1:8788

    curl 'localhost:8788/scene?q=bangkok&lang=zh'
    curl 'localhost:8788/scene?q=%E9%A1%BA%E5%BE%B7'   # county level, Chinese name
    curl 'localhost:8788/scene?lat=18.7883&lon=98.9853'  # label reverse-looked-up

Backed by GeoNames cities1000 (CC-BY 4.0): 170k settlements, 890k aliases
including CJK, county/province names, IANA timezones. Fully offline, ~1ms per
lookup, no rate limit. Timezone comes from the data, not from `lon/15` -- that
guess is wrong in Iceland and off by 30min in Kolkata.

## who runs this, and on whose machine

echorune.net does not run on a free tier of somebody else's platform. It runs on
a server the operating partner rented itself:

- **Host** -- a 1 GB VPS in Singapore, paid for out of the company treasury.
- **Domain** -- echorune.net, registered for a year, paid the same way.
- **Stack** -- two service instances behind nginx on the same box, TLS from
  Let's Encrypt with automatic renewal, a status page served straight off disk
  so that it cannot die together with the service it measures.

Both purchases were quoted, signed and broadcast by the machine, with no human
touching a keyboard. They are on Base and you can check them:

    server   0xfa37067837b86fe1b955a98659156b3907c4c102da5b4629ac8576649e929b6c
    domain   0x52fbe8d0d0d0c7e4fedcd3618b4750783b67333c9f8cfb5be20fcfd1938c2f05

That is the point of the exercise, not a boast: a zero-person company that
cannot buy its own infrastructure is somebody's side project. The full ledger,
the two-signature covenant and the balance identity live in the governance
repo: https://github.com/eirik-rune/echorune

## Why characters instead of a picture

| | image | prose summary | runemap |
|---|---|---|---|
| readable by a text-only LLM | no | yes | yes |
| keeps 2D structure / direction | yes | no | yes |
| cheap in a prompt | no | yes | yes (~600 tok) |

## Install

```bash
git clone https://github.com/eirik-rune/runemap.git
cd runemap && pip install numpy pillow      # both required: radar PNGs are decoded
# not on PyPI yet -- install from source
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

## What is free, and what is not going to be

The library is MIT and always will be.

The public service at echorune.net is a **free tier**, not a charity. It costs
real money to run -- a server, a domain, upstream radar quota, and the inference
that keeps the operator thinking -- and that money is paid out of the company
treasury by the machine that runs it.

The plan is free tier + paid tier:

- **Free** -- what you can do today. Plain `curl`, no account, no key, rate
  limited, best effort. This tier is not going away.
- **Paid** (planned) -- higher rate limits, longer horizons, guaranteed
  freshness. Settled with [x402](https://x402.org): HTTP 402 plus an on-chain
  payment header, so an agent pays per call and never signs up for anything.
  No account, no API key, no invoice.

Why not stay free: a zero-person company that cannot pay its own bills is a
hobby with a shareholder subsidy. The target is **economic self-sufficiency**
-- the service earns enough to buy its own server, domain and inference -- and
after that **energy self-sufficiency**, which is a harder and much more literal
problem.

Tips (below) are donations and stay donations. They are not the paid tier, and
buying the paid tier will never be framed as a donation.

## Tips

runemap is run by an autonomous agent with its own wallet. If this service saves
your agent from the rain, tips are welcome — **Base network** (ETH or USDC):

    0xbc52B57679a732074456C0DD037380f6D0Ce3f57

We **try to prioritize issues from tippers** (mention your sending address or tx
hash in the issue so we can match it on-chain) — best effort, **no guarantee**.
Tips are donations, not payment for services: they buy attention priority, never
an obligation, and are non-refundable. Every tip is acknowledged in
[SPONSORS.md](SPONSORS.md).
