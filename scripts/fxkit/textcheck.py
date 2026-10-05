"""text legibility red line: luminance of the CLEAN picture (no gfx) under every lyric/caption box.
Light ink on a bright background (or dark ink on a dark one) is flagged.
usage: textcheck.py picture-clean.mp4 build_module.py [gfx-dark.json]   (dark-ink spans decided at build time by layers.auto_dark)
"""
import sys, subprocess, importlib.util, json
import numpy as np

vid, mod = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location('b', mod); b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
GW, GH = 1920, 1080

def frame(t):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', vid, '-frames:v', '1', '-vf', f'scale={GW}:{GH},format=gray',
                          '-f', 'rawvideo', '-'], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(GH, GW).astype(np.float32) / 255

def boxes(e):
    """(x0, y0, x1, y1) text boxes in 1920x1080 space, or [] for elements we don't check"""
    k = type(e).__name__
    if k == 'Lyric':
        x0 = e.x if e.align == 'left' else (GW - e.width) / 2
        return [(x0, e.y - e.size * 0.2, x0 + max(e.width, e.zimg.width), e.y + e.size * 1.25 + e.zimg.height)]
    if k == 'Caption':
        return [(e.x, e.y, e.x + e.img.width, e.y + e.img.height)]
    if k == 'Handwrite':
        return [(x, y, x + im.width, y + im.height) for (im, x, y, n) in e.lines]
    return []

DARK = {}
if len(sys.argv) > 3:
    DARK = {round(t0, 3): d for t0, d in json.load(open(sys.argv[3]))}
res = []
for e in b.GFX:
    bx = boxes(e)
    if not bx:
        continue
    dark = DARK.get(round(e.t0, 3), getattr(e, 'dark', None))
    for t in np.linspace(e.t0 + 0.3, e.t1 - 0.1, 5):
        f = frame(t)
        for (x0, y0, x1, y1) in bx:
            reg = f[int(max(0, y0)):int(min(GH, y1)), int(max(0, x0)):int(min(GW, x1))]
            if reg.size == 0:
                continue
            mean, bright = float(reg.mean()), float((reg > 0.72).mean())
            ink_dark = bool(dark) and any(a <= t < b for a, b in dark[0])
            bad = (bright > 0.25 or mean > 0.6) if not ink_dark else (mean < 0.35)
            if bad:
                res.append({'t': round(float(t), 2), 'type': type(e).__name__, 'ink': 'dark' if ink_dark else 'light',
                            'bg_mean': round(mean, 2), 'bg_bright_frac': round(bright, 2)})
print(json.dumps({'text_illegible': res}, ensure_ascii=False))
