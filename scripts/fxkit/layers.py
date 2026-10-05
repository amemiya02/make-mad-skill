"""Full-length overlay layers, frame-exact at 24000/1001.
light layer : RGB on black, screen-blended (embers, dust, light leaks, flares)  -> 960x540 mp4
gfx layer   : RGBA, alpha-overlaid (lyrics, captions, handwriting, title/end card) -> 1920x1080 mov (qtrle)
Every element is timed in SONG seconds.
"""
import numpy as np, subprocess, math, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FPS = 24000 / 1001
AS = '/System/Library/AssetsV2/com_apple_MobileAsset_Font8'
FONTS = {
    'mincho': f'{AS}/a35803b18dea500ee1e426f403635efbe5a84bd4.asset/AssetData/ToppanBunkyuMinchoPr6N-Regular.otf',
    'midashi': f'{AS}/36a81f2dad2ef266c50802d85839e0201fcf4e57.asset/AssetData/ToppanBunkyuMidashiMinchoStdN-ExtraBold.otf',
    'xingkai': (f'{AS}/13b8ce423f920875b28b551f9406bf1014e0a656.asset/AssetData/Xingkai.ttc', 0),
    'song': ('/System/Library/Fonts/Supplemental/Songti.ttc', 1),
}

FALLBACK = ['/System/Library/Fonts/Supplemental/Songti.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc',
            '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
def font(name, size):
    import os
    f = FONTS.get(name)
    path = f[0] if isinstance(f, tuple) else f
    if not path or not os.path.exists(path):
        for fb in FALLBACK:
            if os.path.exists(fb):
                return ImageFont.truetype(fb, size)
        return ImageFont.load_default()
    if isinstance(f, tuple):
        return ImageFont.truetype(f[0], size, index=f[1])
    return ImageFont.truetype(f, size)

def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)

# ------------------------------------------------------------------ light layer
LW, LH = 960, 540

def _sprite(r, sharp=2.2):
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    d = np.sqrt(x * x + y * y) / r
    return (np.clip(1 - d, 0, 1) ** sharp).astype(np.float32)

class Embers:
    """rising sparks spawned in [t0,t1]"""
    def __init__(self, t0, t1, n=70, color=(1.0, 0.55, 0.18), size=(2, 5), speed=(40, 110), seed=1, gain=1.0, region=(0, 1), drift_y=None):
        rnd = random.Random(seed)
        self.t0, self.t1, self.c, self.gain = t0, t1, np.array(color, np.float32), gain
        self.p = []
        for _ in range(n):
            self.p.append(dict(born=t0 + rnd.random() * (t1 - t0) - 2.0,
                               x=LW * (region[0] + rnd.random() * (region[1] - region[0])),
                               y=(LH + 20 + rnd.random() * 120) if drift_y is None else rnd.random() * LH,
                               v=rnd.uniform(*speed), sway=rnd.uniform(8, 30), ph=rnd.random() * 6.28, f=rnd.uniform(0.6, 1.8),
                               r=rnd.randint(*size), life=rnd.uniform(3.0, 6.5) if drift_y is None else drift_y))
        self.spr = {r: _sprite(r * 3) for r in range(size[0], size[1] + 1)}
    def span(self):
        return self.t0 - 2.5, self.t1 + 7.5
    def draw(self, acc, t):
        env = smooth((t - self.t0) / 1.0) * (1 - smooth((t - self.t1) / 1.5))
        if env <= 0:
            return
        for p in self.p:
            a = t - p['born']
            if a < 0 or a > p['life']:
                continue
            x = p['x'] + p['sway'] * math.sin(p['ph'] + a * p['f'] * 2.1)
            y = p['y'] - p['v'] * a
            fl = (0.65 + 0.35 * math.sin(p['ph'] * 3 + a * 9.0 * p['f'])) * math.sin(math.pi * a / p['life'])
            s = self.spr[p['r']]; R = s.shape[0] // 2
            xi, yi = int(x), int(y)
            if xi - R < 0 or yi - R < 0 or xi + R >= LW or yi + R >= LH:
                continue
            acc[yi - R:yi + R + 1, xi - R:xi + R + 1] += s[..., None] * self.c * (fl * env * self.gain)

def Dust(t0, t1, n=60, seed=3, gain=0.35):
    """slow golden motes floating in warm light"""
    return Embers(t0, t1, n=n, color=(1.0, 0.86, 0.62), size=(1, 3), speed=(3, 12), seed=seed, gain=gain, drift_y=10.0)

class Leak:
    """soft moving light blob"""
    def __init__(self, t0, t1, color=(1.0, 0.62, 0.25), peak=0.5, x0=-0.2, x1=1.2, y=0.35, rad=0.55):
        self.t0, self.t1, self.c, self.peak, self.x0, self.x1, self.y, self.rad = t0, t1, np.array(color, np.float32), peak, x0, x1, y, rad
        yy, xx = np.mgrid[0:LH, 0:LW].astype(np.float32)
        self.xx, self.yy = xx / LW, yy / LH
    def span(self):
        return self.t0, self.t1
    def draw(self, acc, t):
        u = (t - self.t0) / (self.t1 - self.t0)
        if not 0 <= u <= 1:
            return
        env = math.sin(math.pi * u) ** 1.5 * self.peak
        cx = self.x0 + (self.x1 - self.x0) * u
        g = np.exp(-(((self.xx - cx) * 1.6) ** 2 + (self.yy - self.y) ** 2) / (self.rad ** 2 * 0.5))
        acc += g[..., None] * self.c * env

class Flare:
    """burst at t: radial bloom + anamorphic streak"""
    def __init__(self, t, x=0.5, y=0.5, color=(1.0, 0.75, 0.4), peak=1.0, dur=1.2, pre=0.12):
        self.t, self.x, self.y, self.c, self.peak, self.dur, self.pre = t, x, y, np.array(color, np.float32), peak, dur, pre
        yy, xx = np.mgrid[0:LH, 0:LW].astype(np.float32)
        self.dx, self.dy = xx / LW - x, yy / LH - y
    def span(self):
        return self.t - self.pre - 0.05, self.t + self.dur
    def draw(self, acc, t):
        a = t - self.t
        if a < -self.pre or a > self.dur:
            return
        att = smooth((a + self.pre) / self.pre) if a < 0 else math.exp(-a / (self.dur * 0.35))
        r = 0.16 + 0.25 * max(a, 0)
        bloom = np.exp(-((self.dx * 1.78) ** 2 + self.dy ** 2) / (r * r))
        streak = np.exp(-(self.dy ** 2) / 0.00022) * np.exp(-(self.dx ** 2) / (0.3 + 0.8 * max(a, 0)) ** 2)
        acc += (bloom * 0.8 + streak * 0.9)[..., None] * self.c * (att * self.peak)

def render_light(elements, total_frames, out):
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{LW}x{LH}', '-r', '24000/1001', '-i', '-',
                          '-c:v', 'libx264', '-preset', 'fast', '-crf', '14', '-pix_fmt', 'yuv420p', out], stdin=subprocess.PIPE)
    blank = np.zeros((LH, LW, 3), np.uint8).tobytes()
    spans = [(e, *e.span()) for e in elements]
    for f in range(total_frames):
        t = f / FPS
        live = [e for e, a, b in spans if a <= t <= b]
        if not live:
            p.stdin.write(blank); continue
        acc = np.zeros((LH, LW, 3), np.float32)
        for e in live:
            e.draw(acc, t)
        p.stdin.write((np.clip(acc, 0, 1) * 255).astype(np.uint8).tobytes())
    p.stdin.close(); p.wait()

# ------------------------------------------------------------------ gfx layer
GW, GH = 1920, 1080

def _shadowed(size, draw_fn, blur=6, shadow_alpha=200, ink=(255, 250, 242, 255), shadow=(0, 0, 0)):
    fg = Image.new('RGBA', size, (0, 0, 0, 0)); draw_fn(ImageDraw.Draw(fg), ink)
    sh = Image.new('RGBA', size, (0, 0, 0, 0)); draw_fn(ImageDraw.Draw(sh), (*shadow, shadow_alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    out = Image.new('RGBA', size, (0, 0, 0, 0)); out.alpha_composite(sh, (2, 3)); out.alpha_composite(fg)
    return out

def _fade(im, a):
    c = im.copy()
    c.putalpha(c.getchannel('A').point(lambda v: int(v * a)))
    return c

DARK_INK = dict(ink=(30, 24, 22, 255), shadow=(255, 255, 255), shadow_alpha=150)

def _dark_w(t, dark):
    """dark = ([(t_on, t_off), ...], xfade): 0..1 weight of the dark-ink version at song time t"""
    if not dark:
        return 0.0
    spans, xf = dark
    return max(smooth((t - a) / xf) * (1 - smooth((t - b) / xf)) for a, b in spans)

class Lyric:
    """Japanese line inked in char by char + Chinese translation.
    dark=([(t_on, t_off), ...], xfade): cross-fade to sumi ink while the background is high-key (white text vanishes there).
    out_dur: fade-out length after t1 (shortened automatically when the next line follows closely)."""
    def __init__(self, t0, t1, ja, zh, x=150, y=842, size=46, step=0.07, align='left', dark=None, out_dur=0.5):
        self.t0, self.t1, self.x, self.y, self.size, self.step, self.align, self.dark = t0, t1, x, y, size, step, align, dark
        self.out_dur = out_dur
        self.text = (ja, zh)
        self._fj, self._fz = font('mincho', size), font('song', int(size * 0.56))
        d = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
        self.adv = [d.textlength(ja[:i], font=self._fj) + i * size * 0.12 for i in range(len(ja) + 1)]
        self.width = self.adv[-1]
        self._cw, self._zw = int(size * 1.6), int(d.textlength(zh, font=self._fz)) + 40 if zh else 0
        self.glyphs, self.zimg = self._make()
        self._dark_set = None
    def _make(self, **kw):
        ja, zh = self.text; size, fj, fz, cw, zw = self.size, self._fj, self._fz, self._cw, self._zw
        g = [_shadowed((cw, cw), lambda dr, fill, ch=ch: dr.text((size * 0.25, size * 0.2), ch, font=fj, fill=fill), **kw) for ch in ja]
        z = _shadowed((zw, int(size * 1.1)), lambda dr, fill: dr.text((10, 6), zh, font=fz, fill=fill), **{'blur': 4, **kw}) if zh else None
        return g, z
    def span(self):
        return self.t0 - 0.05, self.t1 + self.out_dur + 0.02
    def draw(self, img, t):
        out = 1 - smooth((t - self.t1) / self.out_dur)
        x0 = self.x if self.align == 'left' else (GW - self.width) / 2
        w = _dark_w(t, self.dark)
        sets = [(self.glyphs, self.zimg, 1 - w)]
        if w > 0.004:
            if self._dark_set is None:
                self._dark_set = self._make(**DARK_INK)
            sets.append((*self._dark_set, w))
        for glyphs, zimg, k in sets:
            if k < 0.004:
                continue
            for i, g in enumerate(glyphs):
                a = smooth((t - self.t0 - i * self.step) / 0.35) * out
                if a * k > 0.004:
                    img.alpha_composite(_fade(g, a * k), (int(x0 + self.adv[i] - self.size * 0.25), int(self.y - self.size * 0.2 + (1 - a) * 10)))
            az = smooth((t - self.t0 - 0.5) / 0.6) * out * 0.82 * k
            if zimg is not None and az > 0.004:
                zx = x0 if self.align == 'left' else (GW - zimg.width) / 2
                img.alpha_composite(_fade(zimg, az), (int(zx), int(self.y + self.size * 1.25)))

class Caption:
    """dialogue subtitle, centered bottom. dark: see Lyric"""
    def __init__(self, t0, t1, text, y=930, size=46, fontname='song', dark=None, plate=0.0):
        """plate: peak alpha of a soft feathered dark band behind the line (for light text over mixed light/dark
        backgrounds, e.g. a white robe on a dark wall, where neither light nor dark ink reads everywhere)"""
        self.t0, self.t1, self.dark, self.text = t0, t1, dark, text
        f = font(fontname, size)
        tw = ImageDraw.Draw(Image.new('RGBA', (10, 10))).textlength(text, font=f)
        self._mk = lambda **kw: _shadowed((int(tw) + 60, int(size * 1.7)), lambda dr, fill: dr.text((30, 10), text, font=f, fill=fill), **{'blur': 5, 'shadow_alpha': 230, **kw})
        self.img = self._mk()
        self.dimg = None
        self.x, self.y = int((GW - self.img.width) / 2), y
        if plate:
            import numpy as _np
            W, H = self.img.width + 320, int(self.img.height * 1.9)
            yy, xx = _np.mgrid[0:H, 0:W].astype(_np.float32)
            r = _np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
            al = (_np.clip((1 - r) * 1.6, 0, 1) ** 1.5 * 255 * plate).astype(_np.uint8)
            pl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); pl.putalpha(Image.fromarray(al))
            base = Image.new('RGBA', (W, H), (0, 0, 0, 0)); base.alpha_composite(pl)
            base.alpha_composite(self.img, ((W - self.img.width) // 2, (H - self.img.height) // 2))
            self.x, self.y = self.x - (W - self.img.width) // 2, self.y - (H - self.img.height) // 2
            self.img = base
    def span(self):
        return self.t0 - 0.02, self.t1 + 0.02
    def draw(self, img, t):
        a = smooth((t - self.t0) / 0.18) * (1 - smooth((t - (self.t1 - 0.18)) / 0.18))
        w = _dark_w(t, self.dark)
        if a * (1 - w) > 0.004:
            img.alpha_composite(_fade(self.img, a * (1 - w)), (self.x, self.y))
        if a * w > 0.004:
            if self.dimg is None:
                self.dimg = self._mk(**DARK_INK)
            img.alpha_composite(_fade(self.dimg, a * w), (self.x, self.y))

LYRIC_STYLE = dict(align='center', y=846, size=46, step=0.05)

def lyrics_from_csv(path, avoid=(), **style):
    """Lyric elements from an aligned lyric table (start,end,ja,zh). Every row with text becomes a subtitle; rows that would
    overlap a dialogue caption window are skipped. A line fades out before the next one starts (no stacked lines)."""
    import os, csv
    if not os.path.exists(path):
        return []
    rows = [r for r in csv.DictReader(open(path, encoding='utf-8')) if (r.get('ja') or '').strip()]
    rows = [(float(r['start']), float(r['end']), r['ja'].strip(), (r.get('zh') or '').strip()) for r in rows]
    rows = [r for r in rows if not any(r[0] < b and r[1] > a for a, b in avoid)]
    st = {**LYRIC_STYLE, **style}
    out = []
    for i, (a, b, ja, zh) in enumerate(rows):
        nxt = rows[i + 1][0] if i + 1 < len(rows) else None
        t1 = b + 0.35 if nxt is None else min(b + 0.35, nxt - 0.30)
        out_dur = 0.5 if nxt is None else max(0.12, min(0.5, nxt - 0.05 - t1))
        out.append(Lyric(a, max(t1, a + 0.8), ja, zh, out_dur=out_dur, **st))
    return out

def bright_spans(P, outs, fps, box=(360, 800, 1560, 1010), thr_mean=0.58, thr_frac=0.25):
    """timeline spans whose picture is too bright for white text in `box` (x0,y0,x1,y1 in 1920x1080), sampled per shot"""
    import subprocess
    spans = []
    for (s, a, n, head), path in zip(P, outs):
        bright = False
        for k in (0.15, 0.5, 0.85):
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{(head + n * k) / fps:.3f}', '-i', path, '-frames:v', '1',
                                  '-vf', 'scale=480:270,format=gray', '-f', 'rawvideo', '-'], capture_output=True).stdout
            if len(raw) != 480 * 270:
                continue
            f = np.frombuffer(raw, np.uint8).reshape(270, 480).astype(np.float32) / 255
            x0, y0, x1, y1 = [int(v / 4) for v in box]
            r = f[y0:y1, x0:x1]
            if r.mean() > thr_mean or (r > 0.72).mean() > thr_frac:
                bright = True
        if bright:
            spans.append((a / fps, (a + n) / fps))
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] < 0.05:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged

def auto_dark(elements, spans, xfade=0.12):
    """switch Lyric/Caption elements to dark ink over bright picture spans"""
    for e in elements:
        if isinstance(e, (Lyric, Caption)):
            hit = [(max(a, e.t0 - 0.5), min(b, e.t1 + 1.0)) for a, b in spans if a < e.t1 + 0.6 and b > e.t0 - 0.05]
            e.dark = (hit, xfade) if hit else None

class Handwrite:
    """ink-writing reveal (Xingkai): soft left-to-right wipe line by line"""
    def __init__(self, t0, t1, lines, y=430, size=62, speed=9.0, gap=0.35):
        self.t0, self.t1, self.speed, self.gap, self.text = t0, t1, speed, gap, tuple(lines)
        f = font('xingkai', size)
        d = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
        self.lines, yy = [], y
        for ln in lines:
            w = int(d.textlength(ln, font=f)) + 40
            im = _shadowed((w, int(size * 1.5)), lambda dr, fill, ln=ln: dr.text((20, 8), ln, font=f, fill=fill), blur=7, shadow_alpha=220, ink=(250, 238, 218, 255))
            self.lines.append((im, int((GW - w) / 2), yy, len(ln)))
            yy += int(size * 1.45)
    def span(self):
        return self.t0 - 0.02, self.t1 + 0.8
    def draw(self, img, t):
        out = 1 - smooth((t - self.t1) / 0.7)
        start = self.t0
        for (im, x, y, nch) in self.lines:
            dur = nch / self.speed
            u = (t - start) / dur
            start += dur + self.gap
            if u <= 0 or out <= 0:
                continue
            w, ramp = im.width, 70
            edge = int((w + ramp) * min(u, 1.0))
            col = np.clip((edge - np.arange(w)) / ramp, 0, 1).astype(np.float32)
            a = np.array(im.getchannel('A'), np.float32) * col[None, :] * out
            c = im.copy(); c.putalpha(Image.fromarray(a.astype(np.uint8)))
            img.alpha_composite(c, (x, y))

class Title:
    def __init__(self, t0, t1, big, small, y=780, big_size=86, small_size=30, sub=None):
        self.t0, self.t1, self.text = t0, t1, (big, small, sub, y)
        fb, fs, fsub = font('midashi', big_size), font('mincho', small_size), font('mincho', int(small_size * 0.8))
        d = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
        spaced = ' '.join(list(small)) if small else ''
        bw, sw = d.textlength(big, font=fb), d.textlength(spaced, font=fs)
        subw = d.textlength(sub, font=fsub) if sub else 0
        w = int(max(bw, sw, subw)) + 80
        hgt = int(small_size * 1.6 + big_size * 1.3 + (small_size * 1.6 if sub else 0) + 30)
        def fn(dr, fill):
            dr.text(((w - sw) / 2, 0), spaced, font=fs, fill=fill)
            dr.text(((w - bw) / 2, small_size * 1.6), big, font=fb, fill=fill)
            if sub:
                dr.text(((w - subw) / 2, small_size * 1.6 + big_size * 1.3), sub, font=fsub, fill=fill)
        self.img = _shadowed((w, hgt), fn, blur=8, shadow_alpha=200)
        self.y = y
    def span(self):
        return self.t0, self.t1
    def draw(self, img, t):
        a = smooth((t - self.t0) / 0.6) * (1 - smooth((t - (self.t1 - 0.6)) / 0.6))
        if a <= 0.004:
            return
        sc = 1.0 + 0.03 * (t - self.t0) / max(self.t1 - self.t0, 0.1)
        c = self.img.resize((int(self.img.width * sc), int(self.img.height * sc)), Image.LANCZOS)
        img.alpha_composite(_fade(c, a), (int((GW - c.width) / 2), int(self.y - (c.height - self.img.height) / 2)))

def spec_key(elements, total_frames):
    """hash of every element's plain parameters + this module's source"""
    import hashlib, json
    plain = lambda v: isinstance(v, (int, float, str, bool, type(None))) or (isinstance(v, (list, tuple)) and all(plain(x) for x in v))
    spec = [(type(e).__name__, sorted((k, v) for k, v in vars(e).items() if plain(v))) for e in elements]
    return hashlib.sha1(json.dumps([spec, total_frames, open(__file__).read()], default=str).encode()).hexdigest()[:16]

def stale(path, elements, total_frames):
    import os
    try:
        return not os.path.exists(path) or open(path + '.key').read().strip() != spec_key(elements, total_frames)
    except OSError:
        return True

def stamp(path, elements, total_frames):
    open(path + '.key', 'w').write(spec_key(elements, total_frames))

def render_gfx(elements, total_frames, out):
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{GW}x{GH}', '-r', '24000/1001', '-i', '-',
                          '-c:v', 'qtrle', '-pix_fmt', 'argb', out], stdin=subprocess.PIPE)
    blank = bytes(GW * GH * 4)
    spans = [(e, *e.span()) for e in elements]
    for f in range(total_frames):
        t = f / FPS
        live = [e for e, a, b in spans if a <= t <= b]
        if not live:
            p.stdin.write(blank); continue
        img = Image.new('RGBA', (GW, GH), (0, 0, 0, 0))
        for e in live:
            e.draw(img, t)
        p.stdin.write(img.tobytes())
    p.stdin.close(); p.wait()

# ------------------------------------------------------------------ ink wipe mask
def make_ink_mask(frames, out_dir, seed=5, seeds=((0.30, 0.55), (0.62, 0.40), (0.80, 0.70)), w=960, h=540):
    """grayscale PNG sequence (white = incoming revealed) of ink blooming from seed points with fractal edges"""
    import os
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.full((h, w), 9.0, np.float32)
    for k, (sx, sy) in enumerate(seeds):
        d = np.sqrt(((xx / w - sx) * 1.78) ** 2 + (yy / h - sy) ** 2) + 0.12 * k
        dist = np.minimum(dist, d)
    noise = np.zeros((h, w), np.float32)
    for octv, amp in [(8, 1.0), (24, 0.5), (64, 0.25), (160, 0.12)]:
        g = rng.random((octv * 9 // 16 + 2, octv + 2)).astype(np.float32)
        noise += np.array(Image.fromarray((g * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255 * amp
    noise = (noise - noise.mean()) / (noise.std() + 1e-6)
    for f in range(frames):
        u = (f + 1) / frames
        r = (u ** 1.9) * 2.0
        m = 1 / (1 + np.exp(-((r - dist + 0.07 * noise) / 0.018)))
        Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8)).save(f'{out_dir}/m{f:03d}.png')
    return f'{out_dir}/m%03d.png'
