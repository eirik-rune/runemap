"""Minutely precipitation sparkline v0.2.
120 points -> 20 buckets (6 min each, max-pooled) -> unicode bar chart with computed axis.
Alignment rules (hard-won):
- sparkline gets its own line; no CJK prefix on aligned lines (CJK = double width)
- ruler & labels are COMPUTED, never eyeballed
- ruler marks bucket boundaries 0..20 -> 21 chars"""

BARS = "▁▂▃▄▅▆▇█"

def bar(x):
    if x < 0.031: return BARS[0]
    t = min((x - 0.031) / (0.6 - 0.031), 1.0)
    return BARS[1 + int(t * 6.999)]

def sparkline(precip_2h):
    p = list(precip_2h)[:120]
    buckets = [max(p[i*6:(i+1)*6]) for i in range(len(p)//6)]
    spark = "".join(bar(x) for x in buckets)
    ruler = "├" + ("────┼" * 3) + "────┤"
    lab = [" "] * 26
    def put(col, s, anchor="c"):
        start = col - (len(s)//2 if anchor == "c" else 0)
        start = max(0, min(start, 26 - len(s)))
        for i, ch in enumerate(s):
            lab[start + i] = ch
    put(0, "0", "l"); put(5, "30"); put(10, "60"); put(15, "90"); put(20, "120min")
    return "  " + spark + "\n  " + ruler + "\n  " + "".join(lab).rstrip()
