"""Radar echo motion analysis v0.1: two radar frames -> rain-band motion vector.
Method: intensity-weighted centroid displacement (crude; TODO v2: block-matching / optical flow).
Input: radar image frames (PNG + bbox + timestamps) (PNG + bbox + timestamps).
Output: bearing, speed km/h, coverage trend -> LLM-friendly sentence."""
from PIL import Image
import math

DIRS = ["北","东北偏北","东北","东北偏东","东","东南偏东","东南","东南偏南",
        "南","西南偏南","西南","西南偏西","西","西北偏西","西北","西北偏北"]

def echo_centroid(path):
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()
    sx = sy = 0.0; wsum = 0.0; n = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b, a = px[x, y]
            if a > 50:
                wgt = 1.0 + (r / 255.0) * 2.0
                sx += x * wgt; sy += y * wgt; wsum += wgt; n += 1
    if n == 0:
        return None, 0, (w, h)
    return (sx / wsum, sy / wsum), n, (w, h)

def motion(frame0_path, frame1_path, bbox, span_min):
    """bbox = [lat0, lon0, lat1, lon1]; span_min = minutes between frames."""
    lat0, lon0, lat1, lon1 = bbox
    c0, n0, (w, h) = echo_centroid(frame0_path)
    c1, n1, _ = echo_centroid(frame1_path)
    if not c0 or not c1:
        return {"available": False, "reason": "no echo in one/both frames"}
    def geo(c):
        return (lat1 - (c[1] / h) * (lat1 - lat0), lon0 + (c[0] / w) * (lon1 - lon0))
    (la, lo), (lb, lo2) = geo(c0), geo(c1)
    km_n = (lb - la) * 111.0
    km_e = (lo2 - lo) * 111.0 * math.cos(math.radians((la + lb) / 2))
    dist = math.hypot(km_n, km_e)
    speed = dist / (span_min / 60.0) if span_min else 0
    bearing = (math.degrees(math.atan2(km_e, km_n)) + 360) % 360
    dname = DIRS[int((bearing + 11.25) // 22.5) % 16]
    trend = "扩大" if n1 > n0 * 1.1 else ("缩小" if n1 < n0 * 0.9 else "稳定")
    return {
        "available": True, "bearing_deg": round(bearing), "direction": dname,
        "speed_kmh": round(speed), "coverage_trend": trend,
        "text": f"雨带正以约{speed:.0f}km/h向{dname}方向移动，回波范围{trend}中",
        "caveat": "centroid method; upgrade to block-matching for true advection",
    }
