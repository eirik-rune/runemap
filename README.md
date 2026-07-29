# runemap

**Text radar map for agents.** Carve radar echoes into runes.

Most LLM agents cannot see images. Weather radar is an image. So when an agent
asks "is it about to rain on me, and from which direction?", the answer it gets
is a sentence somebody else already summarized -- the 2D structure is gone.

`runemap` turns a radar field into a compact character grid that fits in a
prompt (~600 tokens for 48x24) and preserves what matters: **where the rain is,
how strong it is, and which way it is moving.**

```
                      ....ddddddd.....
                    ...dd###OOO###dd...
             .      ...ddd##OOOO##dd...
         ...ddddd...  ...ddddddddd....
        ..d##OOO#dd..      ...
       ..d#OO```O#dd..
       ..d#OO```O#dd.. HERE
        ..d##OOO##d..
         ...ddddd...
```

(schematic; real output uses the shade ramp
`" "` `\u00b7` `\u2591` `\u2592` `\u2593` `\u2588`
= blank, drizzle, light, moderate, heavy, storm)

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
