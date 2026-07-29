"""Synthetic radar echo -> ASCII, with zero external data.
Proves the renderer without touching any provider's copyrighted imagery."""
import numpy as np

RAMP = " ·░▒▓█"

def synth_field(h=240, w=480, t=0.0):
    """Two gaussian rain cells drifting east-northeast."""
    yy, xx = np.mgrid[0:h, 0:w]
    def cell(cy, cx, sy, sx, amp):
        return amp * np.exp(-(((yy-cy)/sy)**2 + ((xx-cx)/sx)**2))
    f  = cell(h*0.55 + 8*np.sin(t), w*0.30 + 34*t, h*0.10, w*0.09, 5.0)
    f += cell(h*0.35 - 5*t,          w*0.62 + 28*t, h*0.07, w*0.13, 3.6)
    f += 0.6 * np.random.default_rng(int(t*7)).random((h, w))
    return f

def to_ascii(field, cols=48, rows=20, ramp=RAMP, marker=None):
    h, w = field.shape
    ch, cw = h // rows, w // cols
    pooled = field[:ch*rows, :cw*cols].reshape(rows, ch, cols, cw).max(axis=(1, 3))
    lv = np.clip(pooled, 0, len(ramp) - 1).astype(int)
    grid = [[ramp[v] for v in row] for row in lv]
    if marker:
        (my, mx), tag = marker
        for i, c in enumerate(tag):
            if mx + i < cols:
                grid[my][mx + i] = c
    return "\n".join("".join(r) for r in grid)

if __name__ == "__main__":
    for t in (0.0, 1.0, 2.0):
        print(f"--- t+{int(t*30)} min (synthetic) ---")
        print(to_ascii(synth_field(t=t), marker=((11, 23), "HERE")))
        print()
