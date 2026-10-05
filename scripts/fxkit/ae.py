"""ae.py -- After-Effects-style precomp renderer for anime MAD shots (frame-exact, deterministic).

Public API (see render_precomp / zoom_through docstrings for the spec keys):
    render_precomp(spec: dict, out_path: str) -> int      # frames written; spec['effect'] in
                                                          #   freeze_pop | parallax | depth_dolly | text_behind | godrays
    zoom_through(clip_a, clip_b, out_path, frames) -> int # radial-blur zoom-through transition
    python ae.py spec.json out.mp4                        # CLI; last stdout line is `frames=N`
    python ae.py spec.json                                # legacy: spec may carry 'fx'/'out'/'n'/'t0'/'src'(path)
Output: 1920x1080, 24000/1001 fps, exactly round(dur*24000/1001) frames; .mp4 = H.264 CRF10, .mov = ProRes 422 HQ.
Run with a venv holding torch(MPS), onnxruntime, transformers, opencv-python, pillow, huggingface_hub, numpy.
A precomp replaces a shot's source in the FFmpeg cut (src=0). Episode lookup: spec['video'] | spec['root'] | $MAD_ROOT | cwd.

Effects (spec['fx']):
  matte          character cut-out preview over a solid / checker (QA)       -> needs matte
  parallax       2.5D camera: fg cut-out + inpainted bg move at different rates (+motion blur)
  depth_parallax Depth-Anything-V2 displacement camera for landscapes (+motion blur)
  freeze_pop     freeze frame, graded bg, stroked/glowing character pop, speed lines / burst
  text_behind    RGBA text layer between background and character matte
  zoom_through   radial-blur zoom transition A -> B
  godrays        point-light volumetric rays (+ shafts) from a locked light centre
  passthrough    decode/encode only (+post ops)
Post ops (spec['post'] list, applied in order to every output frame):
  {'op':'god_rays', ...} {'op':'chroma', ...} {'op':'vignette', ...} {'op':'grain', ...}

All paths are passed in; nothing project-specific is hard-coded. Models are fetched from the
Hugging Face hub on first use (skytnt/anime-seg isnetis.onnx, Depth-Anything-V2-Small-hf,
fashn-ai/LaMa big-lama.pt). Caches (raw mattes, plates, depth) go to spec['cache_dir'] or
$AE_CACHE or ~/.cache/ae-precomp.
"""
import os, sys, json, math, time, hashlib, subprocess, shutil
from fractions import Fraction as F
import warnings
import numpy as np
import cv2
warnings.filterwarnings('ignore', message='All-NaN')

FPS = F(24000, 1001)
FF = float(FPS)
W, H = 1920, 1080
SEG = 1024                      # anime-seg network size (letterboxed square)
cv2.setNumThreads(int(os.environ.get('AE_THREADS', '4')))

# ============================================================================ utils
def _hash(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]

def _src_id(src):
    st = os.stat(src)
    return [os.path.abspath(src), st.st_size, int(st.st_mtime)]

def cache_dir(spec=None):
    d = (spec or {}).get('cache_dir') or os.environ.get('AE_CACHE') or os.path.expanduser('~/.cache/ae-precomp')
    os.makedirs(d, exist_ok=True)
    return d

def frames_of(t):
    """seconds -> frame count on the 24000/1001 grid"""
    return int(round(F(str(round(t, 6))) * FPS))

def ease(u, kind='io'):
    u = min(max(u, 0.0), 1.0)
    if kind == 'lin':
        return u
    if kind == 'i':
        return u ** 3
    if kind == 'o':
        return 1 - (1 - u) ** 3
    if kind == 'back':                       # ease-out with overshoot
        c1 = 1.70158; c3 = c1 + 1
        return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2
    if kind == 'expo_i':
        return 0.0 if u == 0 else 2 ** (10 * u - 10)
    return u * u * (3 - 2 * u)               # 'io' smoothstep

class Timer:
    def __init__(self):
        self.t = {}
    def add(self, k, dt):
        self.t[k] = self.t.get(k, 0.0) + dt
    def __call__(self, k):
        tm = self
        class _C:
            def __enter__(s):
                s.t0 = time.perf_counter()
            def __exit__(s, *a):
                tm.add(k, time.perf_counter() - s.t0)
        return _C()

# ============================================================================ IO
def read_frames(src, t0=0.0, n=None, size=(W, H)):
    """Frame-exact decode of n frames starting at t0 (s) -> uint8 (n,h,w,3) RGB.
    Same seek/fps chain as fx.py (-ss before -i, setpts, fps=24000/1001). Images are repeated."""
    w, h = size
    ext = os.path.splitext(src)[1].lower()
    if ext in ('.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'):
        im = cv2.cvtColor(cv2.imread(src, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        im = cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA)
        return np.repeat(im[None], n or 1, 0)
    vf = (f'setpts=PTS-STARTPTS,fps={FPS.numerator}/{FPS.denominator},'
          f'scale={w}:{h}:flags=lanczos:in_color_matrix=bt709,format=rgb24')
    cmd = ['ffmpeg', '-v', 'error', '-ss', f'{max(0.0, t0):.4f}', '-i', src, '-vf', vf,
           '-frames:v', str(n), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    got = len(raw) // (w * h * 3)
    if got < n:
        raise RuntimeError(f'{src} @ {t0}: wanted {n} frames, decoded {got}')
    return np.frombuffer(raw, np.uint8)[: n * w * h * 3].reshape(n, h, w, 3).copy()

CODECS = {
    'prores': (['-c:v', 'prores_ks', '-profile:v', '3', '-vendor', 'apl0', '-pix_fmt', 'yuv422p10le'], 'rgb24'),
    'prores4444': (['-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', '-alpha_bits', '16'], 'rgba'),
    'h264': (['-c:v', 'libx264', '-preset', 'slow', '-crf', '10', '-pix_fmt', 'yuv420p', '-x264-params', 'aq-mode=3'], 'rgb24'),
}

class Writer:
    """Pipe RGB(A) uint8 or float [0,1] frames to ffmpeg; close() verifies the exact frame count."""
    def __init__(self, out, n, codec='prores', size=(W, H)):
        self.out, self.n, self.size = out, n, size
        args, self.pix = CODECS[codec]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        w, h = size
        vf = 'scale=out_color_matrix=bt709:out_range=tv' if self.pix == 'rgb24' else 'scale=out_color_matrix=bt709'
        cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', self.pix, '-s', f'{w}x{h}',
               '-r', f'{FPS.numerator}/{FPS.denominator}', '-i', '-', '-vf', vf] + args + [
               '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
               '-frames:v', str(n), '-threads', '4', out]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        self.k = 0

    def write(self, fr):
        if fr.dtype != np.uint8:
            fr = (np.clip(fr, 0, 1) * 255 + 0.5).astype(np.uint8)
        if self.pix == 'rgba' and fr.shape[2] == 3:
            fr = np.dstack([fr, np.full(fr.shape[:2], 255, np.uint8)])
        self.p.stdin.write(np.ascontiguousarray(fr).tobytes())
        self.k += 1

    def close(self):
        self.p.stdin.close()
        if self.p.wait() != 0:
            raise RuntimeError(f'ffmpeg failed writing {self.out}')
        got = count_frames(self.out)
        if got != self.n or self.k != self.n:
            raise RuntimeError(f'{self.out}: frame count {got} (written {self.k}) != {self.n}')
        return got

def count_frames(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                        'stream=nb_read_frames', '-of', 'csv=p=0', path], capture_output=True, text=True)
    return int(r.stdout.strip() or 0)

def contact_sheet(frames, out, idxs=None, scale=0.25, cols=4, labels=None):
    """frames: array/list of RGB (uint8 or float) or a video path. Writes a labelled grid (1/4 res)."""
    if isinstance(frames, str):
        n = count_frames(frames)
        frames = read_frames(frames, 0, n)
    n = len(frames)
    idxs = idxs if idxs is not None else sorted(set(np.linspace(0, n - 1, min(8, n)).round().astype(int).tolist()))
    tiles = []
    for j, i in enumerate(idxs):
        f = frames[i]
        f = (np.clip(f, 0, 1) * 255).astype(np.uint8) if f.dtype != np.uint8 else f
        t = cv2.resize(f, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if t.ndim == 2:
            t = cv2.cvtColor(t, cv2.COLOR_GRAY2RGB)
        lab = labels[j] if labels else f'f{i}'
        cv2.putText(t, lab, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(t, lab, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1, cv2.LINE_AA)
        tiles.append(t)
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    cv2.imwrite(out, cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))
    return out

# ============================================================================ models (lazy singletons)
_M = {}

def _hf(repo, fname):
    from huggingface_hub import hf_hub_download
    return hf_hub_download(repo, fname)

class AnimeSeg:
    """SkyTNT anime-segmentation ISNet (isnetis.onnx). CoreML EP ~0.4 s/frame on M-series, CPU ~4.5 s."""
    def __init__(self, path=None, provider=None):
        import onnxruntime as ort
        path = path or _hf('skytnt/anime-seg', 'isnetis.onnx')
        so = ort.SessionOptions(); so.intra_op_num_threads = 4
        so.log_severity_level = 3
        provs = [provider] if provider else ['CoreMLExecutionProvider', 'CPUExecutionProvider']
        self.sess = ort.InferenceSession(path, so, providers=provs + (['CPUExecutionProvider'] if provider else []))

    def __call__(self, rgb):
        """rgb uint8 HxWx3 -> float32 alpha at the letterbox content res (SEG x SEG*h/w)."""
        h0, w0 = rgb.shape[:2]
        h, w = (SEG, int(SEG * w0 / h0)) if h0 > w0 else (int(SEG * h0 / w0), SEG)
        ph, pw = (SEG - h) // 2, (SEG - w) // 2
        x = np.zeros((SEG, SEG, 3), np.float32)
        x[ph:ph + h, pw:pw + w] = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        m = self.sess.run(None, {'img': x.transpose(2, 0, 1)[None]})[0][0, 0]
        return np.clip(m[ph:ph + h, pw:pw + w], 0, 1).astype(np.float32)

def _torch_device(pref='mps'):
    import torch
    if pref == 'mps' and torch.backends.mps.is_available():
        return 'mps'
    return 'cpu'

class Depth:
    """Depth Anything V2 Small (HF transformers). Returns relative depth in [0,1], 1 = near."""
    def __init__(self, repo='depth-anything/Depth-Anything-V2-Small-hf', device=None):
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        torch.set_num_threads(4)
        self.torch = torch
        self.proc = AutoImageProcessor.from_pretrained(repo)
        self.dev = device or _torch_device()
        self.model = AutoModelForDepthEstimation.from_pretrained(repo).to(self.dev).eval()

    def __call__(self, rgb):
        torch = self.torch
        inp = self.proc(images=rgb, return_tensors='pt').to(self.dev)
        with torch.no_grad():
            d = self.model(**inp).predicted_depth[0].float().cpu().numpy()
        d = cv2.resize(d, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_CUBIC)
        lo, hi = np.percentile(d, 1), np.percentile(d, 99)
        return np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1).astype(np.float32)

class Lama:
    """big-lama TorchScript (fashn-ai/LaMa). Inpaints the mask bbox crop at <= max_side px."""
    def __init__(self, device=None):
        import torch
        torch.set_num_threads(4)
        self.torch = torch
        path = _hf('fashn-ai/LaMa', 'big-lama.pt')
        self.dev = device or 'cpu'      # MPS lacks some FFT paths for this jit graph; CPU is safe
        self.model = torch.jit.load(path, map_location=self.dev).eval()

    def __call__(self, rgb, mask, max_side=1024, margin=0.35):
        torch = self.torch
        ys, xs = np.nonzero(mask)
        if len(ys) == 0:
            return rgb.copy()
        h0, w0 = mask.shape
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        my, mx = int((y1 - y0) * margin) + 32, int((x1 - x0) * margin) + 32
        y0, y1, x0, x1 = max(0, y0 - my), min(h0, y1 + my), max(0, x0 - mx), min(w0, x1 + mx)
        crop, cm = rgb[y0:y1, x0:x1], mask[y0:y1, x0:x1]
        ch, cw = crop.shape[:2]
        s = min(1.0, max_side / max(ch, cw))
        sw, sh = max(8, int(round(cw * s / 8)) * 8), max(8, int(round(ch * s / 8)) * 8)
        ci = cv2.resize(crop, (sw, sh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        mi = (cv2.resize(cm.astype(np.uint8), (sw, sh), interpolation=cv2.INTER_NEAREST) > 0).astype(np.float32)
        mi = cv2.dilate(mi, np.ones((3, 3), np.uint8))
        with torch.no_grad():
            ti = torch.from_numpy(ci.transpose(2, 0, 1))[None].to(self.dev)
            tm = torch.from_numpy(mi)[None, None].to(self.dev)
            o = self.model(ti, tm)[0].permute(1, 2, 0).float().cpu().numpy()
        o = np.clip(o, 0, 1) if o.max() <= 1.5 else np.clip(o / 255.0, 0, 1)
        o = cv2.resize(o, (cw, ch), interpolation=cv2.INTER_CUBIC)
        soft = cv2.GaussianBlur(cv2.dilate(cm.astype(np.float32), np.ones((5, 5), np.uint8)), (0, 0), 2.0)[..., None]
        out = rgb.astype(np.float32) / 255.0
        out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - soft) + o * soft
        return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)

def model(name):
    if name not in _M:
        _M[name] = {'seg': AnimeSeg, 'depth': Depth, 'lama': Lama}[name]()
    return _M[name]

# ============================================================================ image ops
def f32(img):
    return img.astype(np.float32) / 255.0 if img.dtype == np.uint8 else img

def gray(img):
    return cv2.cvtColor(f32(img), cv2.COLOR_RGB2GRAY)

def guided_filter(I, p, r=4, eps=2e-3):
    """He et al. guided filter (gray guide). Snaps an upsampled matte to the frame's line-art edges."""
    k = (2 * r + 1, 2 * r + 1)
    bf = lambda x: cv2.boxFilter(x, -1, k, borderType=cv2.BORDER_REFLECT)
    mI, mp = bf(I), bf(p)
    a = (bf(I * p) - mI * mp) / (bf(I * I) - mI * mI + eps)
    b = mp - a * mI
    return bf(a) * I + bf(b)

def norm_conv(img, w, sigma):
    num = cv2.GaussianBlur(img * w[..., None], (0, 0), sigma)
    den = cv2.GaussianBlur(w, (0, 0), sigma)[..., None]
    return num / np.maximum(den, 1e-4), den[..., 0]

def decontaminate(img, a, plate=None, solid=0.95):
    """Foreground colour estimate for edge pixels (AE 'Decontaminate edge colors').
    With a clean plate: unmix F=(I-(1-a)B)/a; otherwise pull colour inward from solid matte."""
    I = f32(img)
    w = (a > solid).astype(np.float32)
    Fb, den = norm_conv(I, w, 3.0)
    far = den < 0.02
    if far.any():
        F2, _ = norm_conv(I, w, 12.0)
        Fb[far] = F2[far]
    if plate is not None:
        B = f32(plate)
        au = np.maximum(a, 0.05)[..., None]
        Fu = np.clip((I - (1 - a[..., None]) * B) / au, 0, 1)
        t = np.clip((a - 0.25) / 0.5, 0, 1)[..., None]           # trust unmixing only at mid/high alpha
        Fb = Fu * t + Fb * (1 - t)
    return np.where(w[..., None] > 0, I, Fb).astype(np.float32)

def over(bg, fg, a):
    a = a[..., None] if a.ndim == 2 else a
    return fg * a + bg * (1 - a)

def screen(a, b):
    return 1 - (1 - a) * (1 - b)

def affine(scale=1.0, pivot=(W / 2, H / 2), t=(0.0, 0.0), rot=0.0):
    """2x3 matrix: rotate/scale about pivot, then translate (dst = M @ src)."""
    M = cv2.getRotationMatrix2D((float(pivot[0]), float(pivot[1])), float(rot), float(scale))
    M[0, 2] += t[0]; M[1, 2] += t[1]
    return M

def warp(img, M, border='reflect', interp=cv2.INTER_LINEAR):
    bm = cv2.BORDER_REFLECT101 if border == 'reflect' else cv2.BORDER_CONSTANT
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=interp, borderMode=bm)

def radial_blur(img, center, amount, passes=5, decay=1.0, inward=True):
    """CC Radial Blur 'zoom' / volumetric light: average of 2**passes copies scaled about center
    over [1/(1+amount), 1] using log-doubling passes (cost = passes warps, not 2**passes)."""
    if amount <= 1e-4:
        return img
    out = img
    cx, cy = center
    N = passes
    for k in range(N):
        f = (1.0 + amount) ** (2 ** k / 2 ** N)
        s = 1.0 / f if inward else f
        M = np.array([[s, 0, cx * (1 - s)], [0, s, cy * (1 - s)]], np.float32)
        sh = cv2.warpAffine(out, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                            borderMode=cv2.BORDER_REPLICATE)
        out = (out + decay * sh) / (1 + decay)
    return out

def stroke_alpha(a, px, thr=0.5):
    """Anti-aliased round stroke (AE Layer Style > Stroke, outside) from distance transform."""
    hard = (a < thr).astype(np.uint8)
    d = cv2.distanceTransform(hard, cv2.DIST_L2, 5)
    return np.maximum(np.clip(px - d + 0.5, 0, 1), a).astype(np.float32)

def desaturate(img, amt):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)[..., None]
    return img * (1 - amt) + g * amt

def speed_lines(size, center, seed, n=90, r0=(0.42, 0.75), width=(0.004, 0.012), color=(1, 1, 1)):
    """Manga radial speed lines (Saber/Concentration lines). Deterministic per seed. -> (rgb, alpha)."""
    w, h = size
    rng = np.random.default_rng(seed)
    cx, cy = center
    R = math.hypot(w, h)
    ss = 2
    m = np.zeros((h * ss // 2, w * ss // 2), np.uint8)     # draw at 1x with AA
    sc = ss / 2
    for _ in range(n):
        th = rng.uniform(0, 2 * math.pi)
        ri = rng.uniform(*r0) * 0.5 * math.hypot(w, h) * 0.9
        dw = rng.uniform(*width) * math.pi
        p0 = (cx + ri * math.cos(th), cy + ri * math.sin(th))
        p1 = (cx + R * math.cos(th - dw), cy + R * math.sin(th - dw))
        p2 = (cx + R * math.cos(th + dw), cy + R * math.sin(th + dw))
        pts = (np.array([p0, p1, p2]) * sc * 16).astype(np.int32)
        cv2.fillPoly(m, [pts], 255, lineType=cv2.LINE_AA, shift=4)
    a = m.astype(np.float32) / 255.0
    rgb = np.empty((h, w, 3), np.float32); rgb[:] = color
    return rgb, a

def light_burst(size, center, phase=0.0, n_rays=24, sharp=6.0, falloff=0.55, seed=7):
    """Radial light rays behind a subject (soft angular noise x radial falloff). -> alpha."""
    w, h = size
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = xx - center[0], yy - center[1]
    th = np.arctan2(dy, dx) + phase
    r = np.sqrt(dx * dx + dy * dy) / math.hypot(w, h)
    pat = np.zeros_like(th)
    for k, amp in ((n_rays, 1.0), (int(n_rays * 1.7) + 1, 0.6), (int(n_rays * 0.6) + 1, 0.5)):
        pat += amp * np.cos(k * th + rng.uniform(0, 6.283))
    pat = np.clip(pat / 2.1 * 0.5 + 0.5, 0, 1) ** sharp
    return (pat * np.exp(-r / falloff) + 0.35 * np.exp(-(r / 0.18) ** 2)).astype(np.float32)

_CA = {}
def chroma(img, amount=3.0, power=2.0):
    """Lens chromatic aberration at the frame edge: R scaled out, B scaled in by amount px at the corner."""
    h, w = img.shape[:2]
    key = (w, h, amount, power)
    if key not in _CA:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = (w - 1) / 2, (h - 1) / 2
        dx, dy = xx - cx, yy - cy
        rn = np.sqrt(dx * dx + dy * dy) / math.hypot(cx, cy)
        k = amount * rn ** power / np.maximum(rn * math.hypot(cx, cy), 1e-3)
        _CA[key] = [(cx + dx * (1 - s * k), cy + dy * (1 - s * k)) for s in (1, -1)]
    (rx, ry), (bx, by) = _CA[key]
    out = img.copy()
    out[..., 0] = cv2.remap(img[..., 0], rx, ry, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    out[..., 2] = cv2.remap(img[..., 2], bx, by, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out

def god_rays(img, center=None, threshold=0.78, length=0.45, strength=0.55, tint=(1.0, 0.85, 0.6),
             occluder=None, passes=6, res=0.5, softness=0.12, ang=0.0, ang_phase=0.0, ang_n=48):
    """Volumetric light (AE CC Light Rays / Trapcode Shine): bright-region mask -> radial blur from
    the light position -> screen. occluder (HxW alpha, 1 = blocks light) cuts rays around a character."""
    h, w = img.shape[:2]
    L = gray(img)
    m = np.clip((L - threshold) / softness, 0, 1)
    if occluder is not None:
        m = m * (1 - occluder)
    if center is None or center == 'auto':
        b = cv2.GaussianBlur(m, (0, 0), 25)
        cy, cx = np.unravel_index(np.argmax(b), b.shape)
        center = (float(cx) / w, float(cy) / h)
    small = cv2.resize(m * 1.0, None, fx=res, fy=res, interpolation=cv2.INTER_AREA)
    rays = radial_blur(small, (center[0] * w * res, center[1] * h * res), length, passes=passes, decay=0.97)
    rays = cv2.resize(rays, (w, h), interpolation=cv2.INTER_LINEAR)
    rays = np.clip(rays * 2.2, 0, 1)
    if ang > 0:            # angular streak modulation -> discrete shafts instead of a smooth glow
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        th = np.arctan2(yy - center[1] * h, xx - center[0] * w)
        rng = np.random.default_rng(11)
        co = rng.uniform(0.2, 1.0, (ang_n // 2, 2)).astype(np.float32); ph = rng.uniform(0, 6.28, (ang_n // 2, 2))
        mod = sum(co[i, 0] * np.cos((i + 1) * th + ph[i, 0] + ang_phase * (1 + i % 3 * 0.3)) for i in range(ang_n // 2))
        mod = (mod - mod.min()) / (np.ptp(mod) + 1e-6)
        r = np.hypot(yy - center[1] * h, xx - center[0] * w) / (0.18 * w)
        a_eff = ang * np.clip(r, 0, 1) ** 1.5              # no angular pinch in the flame core
        rays = rays * (1 - a_eff + a_eff * np.clip(mod * 1.8 - 0.3, 0, 1) ** 1.5)
    rays = rays[..., None] * np.array(tint, np.float32) * strength
    return screen(img, rays), center

def vignette(img, amount=0.35, radius=0.85):
    h, w = img.shape[:2]
    key = ('vig', w, h, amount, radius)
    if key not in _CA:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / math.sqrt(2)
        _CA[key] = (1 - amount * np.clip((r - (1 - radius)) / radius, 0, 1) ** 2)[..., None].astype(np.float32)
    return img * _CA[key]

def grain(img, amount=0.02, seed=0, size=1.2):
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    g = rng.standard_normal((h // 2, w // 2)).astype(np.float32)
    g = cv2.GaussianBlur(cv2.resize(g, (w, h)), (0, 0), size * 0.5)
    return img + g[..., None] * amount

def apply_post(img, post, k, ctx=None):
    for op in post or []:
        o = dict(op); kind = o.pop('op')
        if kind == 'god_rays':
            occ = ctx.get('alpha') if (ctx and o.pop('occlude', False)) else None
            o.pop('occlude', None)
            if ctx is not None and o.get('center') in (None, 'auto') and 'gr_center' in ctx:
                o['center'] = ctx['gr_center']              # lock auto centre after frame 0 (no jitter)
            img, c = god_rays(img, occluder=occ, **o)
            if ctx is not None:
                ctx['gr_center'] = c
        elif kind == 'chroma':
            img = chroma(img, **o)
        elif kind == 'vignette':
            img = vignette(img, **o)
        elif kind == 'grain':
            img = grain(img, seed=o.pop('seed', 0) * 100003 + k, **o)
        else:
            raise ValueError(f'unknown post op {kind}')
    return img

# ============================================================================ matte (roto)
MATTE_DEFAULTS = dict(temporal='flow_ema', ema=0.6, conf_sigma=0.05, bidir=True, edge='snap', snap_r=2, snap_eps=1e-3,
                      snap_thr=0.5, guided_r=4, guided_eps=2e-3, lo=0.08, hi=0.92, choke=0.0, feather=0.0,
                      keep_min_frac=0.0, roi=None, hold_thresh=0.0015)

def raw_mattes(frames, spec, tm=None, cache_key=None):
    """Per-frame anime-seg mattes at seg res, with hold-frame reuse (anime on 2s/3s) and disk cache."""
    tm = tm or Timer()
    path = os.path.join(cache_dir(spec), f'raw_{cache_key}.npz') if cache_key else None
    if path and os.path.exists(path):
        return np.load(path)['m'].astype(np.float32) / 65535.0, True
    seg = model('seg')
    out, prev, holds = [], None, 0
    for f in frames:
        small = cv2.resize(f, (480, 270), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        if prev is not None and np.abs(small - prev[0]).mean() < spec.get('hold_thresh', 0.0015):
            out.append(prev[1]); holds += 1
            continue
        with tm('seg'):
            m = seg(f)
        out.append(m); prev = (small, m)
    arr = np.stack(out)
    if path:
        np.savez_compressed(path, m=(arr * 65535).astype(np.uint16))
    return arr, False

def _dis():
    if 'dis' not in _M:
        d = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        _M['dis'] = d
    return _M['dis']

def _flow_warp(img, flow):
    h, w = flow.shape[:2]
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(img, gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

def _flows(smalls, direction):
    """flow[t] maps pixels of frame t to frame t-1 (direction=-1) or t+1 (+1). smalls: float RGB."""
    dis = _dis()
    gs = [(cv2.cvtColor(s, cv2.COLOR_RGB2GRAY) * 255).astype(np.uint8) for s in smalls]
    n = len(gs); fl = [None] * n
    for t in range(n):
        u = t + direction
        if 0 <= u < n:
            fl[t] = dis.calc(gs[t], gs[u], None)
    return fl

def temporal_smooth(raw, frames, spec, tm=None):
    """Flow-warped, confidence-weighted EMA run forward and backward (offline => no lag), averaged.
    conf = exp(-(photometric warp error / conf_sigma)^2) so occlusions/fast motion fall back to raw."""
    tm = tm or Timer()
    if spec.get('temporal', 'flow_ema') in (None, 'none') or len(raw) < 2:
        return raw
    k, sig = spec.get('ema', 0.6), spec.get('conf_sigma', 0.05)
    hs, ws = raw.shape[1:]
    with tm('flow'):
        smalls = [cv2.resize(f, (ws, hs), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0 for f in frames]
        passes = [(-1, range(len(raw)))]
        if spec.get('bidir', True):
            passes.append((1, range(len(raw) - 1, -1, -1)))
        res = []
        for direction, order in passes:
            fl = _flows(smalls, direction)
            s = np.empty_like(raw); last = None
            for t in order:
                if last is None:
                    s[t] = raw[t]
                else:
                    wa = _flow_warp(s[last], fl[t])
                    err = np.abs(_flow_warp(smalls[last], fl[t]) - smalls[t]).mean(2)
                    conf = np.exp(-(cv2.GaussianBlur(err, (0, 0), 1.5) / sig) ** 2)
                    wgt = k * conf
                    s[t] = raw[t] * (1 - wgt) + wa * wgt
                last = t
            res.append(s)
    return np.mean(res, 0).astype(np.float32)

def refine(alpha_small, frame, spec, size=(W, H)):
    """Upsample seg-res matte to full res, guided-filter to line-art edges, levels, choke, feather."""
    a = cv2.resize(alpha_small, size, interpolation=cv2.INTER_LINEAR)
    if spec.get('edge', 'snap') == 'snap':
        # anime edges are hard: binarise the (temporally smoothed) matte, then a small-radius guided
        # filter re-anti-aliases it along the frame's own line-art -> crisp edge, no soft fringe
        a = guided_filter(gray(frame), (a > spec.get('snap_thr', 0.5)).astype(np.float32),
                          spec.get('snap_r', 2), spec.get('snap_eps', 1e-3))
    else:
        if spec.get('guided_r', 4):
            a = guided_filter(gray(frame), a, spec.get('guided_r', 4), spec.get('guided_eps', 2e-3))
        lo, hi = spec.get('lo', 0.08), spec.get('hi', 0.92)
        a = np.clip((a - lo) / max(hi - lo, 1e-3), 0, 1)
    if spec.get('roi'):
        x0, y0, x1, y1 = spec['roi']
        m = np.zeros_like(a); m[int(y0 * size[1]):int(y1 * size[1]), int(x0 * size[0]):int(x1 * size[0])] = 1
        a = a * cv2.GaussianBlur(m, (0, 0), 8)
    if spec.get('keep_min_frac', 0) > 0:
        n, lab, st, _ = cv2.connectedComponentsWithStats((a > 0.5).astype(np.uint8))
        if n > 1:
            big = st[1:, cv2.CC_STAT_AREA].max()
            keep = np.zeros(n, bool); keep[1:] = st[1:, cv2.CC_STAT_AREA] >= big * spec['keep_min_frac']
            k = cv2.dilate(keep[lab].astype(np.uint8), np.ones((9, 9), np.uint8)).astype(np.float32)
            a = a * k
    if spec.get('choke', 0) > 0:
        r = int(math.ceil(spec['choke']))
        a = cv2.erode(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    if spec.get('feather', 0) > 0:
        a = cv2.GaussianBlur(a, (0, 0), spec['feather'])
    return np.clip(a, 0, 1).astype(np.float32)

def flicker_metrics(seq_small, frames):
    """Matte stability. raw = mean |a_t - a_{t-1}|; comp = same after warping a_{t-1} by optical flow
    (removes real motion -> measures flicker); *_edge = restricted to the matte boundary band."""
    if len(seq_small) < 2:
        return {}
    hs, ws = seq_small.shape[1:]
    smalls = [cv2.resize(f, (ws, hs), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0 for f in frames]
    fl = _flows(smalls, -1)
    raw, comp, raw_e, comp_e = [], [], [], []
    for t in range(1, len(seq_small)):
        a, b = seq_small[t], seq_small[t - 1]
        band = cv2.dilate(((a > 0.03) & (a < 0.97)).astype(np.uint8) | (np.abs(a - b) > 0.2).astype(np.uint8),
                          np.ones((7, 7), np.uint8)).astype(bool)
        d = np.abs(a - b); dc = np.abs(a - _flow_warp(b, fl[t]))
        raw.append(d.mean()); comp.append(dc.mean())
        if band.any():
            raw_e.append(d[band].mean()); comp_e.append(dc[band].mean())
    r = lambda x: round(float(np.mean(x)), 5) if x else 0.0
    return dict(mad=r(raw), mad_flowcomp=r(comp), mad_edge=r(raw_e), mad_flowcomp_edge=r(comp_e),
                worst_flowcomp=round(float(np.max(comp)), 5))

class MatteSeq:
    """Character matte for a decoded sequence. .alpha(t) -> full-res refined matte (cached per t)."""
    def __init__(self, frames, spec, src_key=None, tm=None):
        self.frames, self.tm = frames, tm or Timer()
        self.spec = {**MATTE_DEFAULTS, **(spec or {})}
        key = _hash(src_key, 'raw', self.spec.get('roi_pre'), 'isnetis-v1') if src_key else None
        self.raw, self.cached = raw_mattes(frames, self.spec, self.tm, key)
        self.small = temporal_smooth(self.raw, frames, self.spec, self.tm)
        self._full = {}

    def alpha(self, t):
        if t not in self._full:
            with self.tm('refine'):
                self._full[t] = refine(self.small[t], self.frames[t], self.spec)
            if len(self._full) > 6:
                self._full.pop(next(iter(self._full)))
        return self._full[t]

    def metrics(self, n_max=None):
        n = len(self.frames) if n_max is None else min(n_max, len(self.frames))
        fin = np.stack([cv2.resize(refine(self.small[t], self.frames[t], self.spec), (960, 540),
                                   interpolation=cv2.INTER_AREA) for t in range(n)])
        rawf = np.stack([cv2.resize(refine(self.raw[t], self.frames[t], {**self.spec}), (960, 540),
                                    interpolation=cv2.INTER_AREA) for t in range(n)])
        return {'raw': flicker_metrics(rawf, self.frames[:n]), 'smoothed': flicker_metrics(fin, self.frames[:n])}

    def bbox(self, t, thr=0.5):
        ys, xs = np.nonzero(self.alpha(t) > thr)
        if len(xs) == 0:
            return (0, 0, W, H)
        return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

# ============================================================================ clean plate
PLATE_DEFAULTS = dict(mode='static', grow=14, thr=0.04, max_frames=24, lama_max=1024)

def clean_plate(frames, mseq, spec, src_key=None, tm=None, frame_idx=None):
    """Background with the character removed (AE Content-Aware Fill).
    static: temporal median of unoccluded pixels over sampled frames (static camera), LaMa for the
            pixels covered in every sample.   frame: LaMa on a single frame (freeze / moving camera)."""
    tm = tm or Timer()
    sp = {**PLATE_DEFAULTS, **(spec or {})}
    mode = sp['mode'] if frame_idx is None else 'frame'
    key = _hash(src_key, 'plate', sp, mode, frame_idx, mseq.spec) if src_key else None
    path = os.path.join(cache_dir(sp), f'plate_{key}.png') if key else None
    if path and os.path.exists(path):
        return cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB), cv2.imread(path[:-4] + '_hole.png', 0) > 0
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * sp['grow'] + 1, 2 * sp['grow'] + 1))
    hole_of = lambda t: cv2.dilate((mseq.alpha(t) > sp['thr']).astype(np.uint8), ker) > 0
    with tm('plate'):
        if mode == 'frame':
            t = frame_idx or 0
            base, hole = frames[t], hole_of(t)
        else:
            idx = np.unique(np.linspace(0, len(frames) - 1, min(sp['max_frames'], len(frames))).round().astype(int))
            base = np.zeros_like(frames[0]); hole = np.ones(frames[0].shape[:2], bool)
            holes = [hole_of(t) for t in idx]
            for y0 in range(0, H, 120):          # strip-wise masked median (bounded memory)
                st = np.stack([frames[t][y0:y0 + 120].astype(np.float32) for t in idx])
                hm = np.stack([h_[y0:y0 + 120] for h_ in holes])
                st[hm] = np.nan
                med = np.nanmedian(st, 0)
                cov = hm.all(0)
                med[cov] = 0
                base[y0:y0 + 120] = np.nan_to_num(med).astype(np.uint8)
                hole[y0:y0 + 120] = cov
        with tm('lama'):
            plate = model('lama')(base, hole, max_side=sp['lama_max']) if hole.any() else base
    if path:
        cv2.imwrite(path, cv2.cvtColor(plate, cv2.COLOR_RGB2BGR)); cv2.imwrite(path[:-4] + '_hole.png', hole.astype(np.uint8) * 255)
    return plate, hole

# ============================================================================ depth
def depth_map(frame, spec, src_key=None, tm=None):
    tm = tm or Timer()
    key = _hash(src_key, 'depth', spec.get('depth_frame', 0), 'da2s') if src_key else None
    path = os.path.join(cache_dir(spec), f'depth_{key}.npy') if key else None
    if path and os.path.exists(path):
        return np.load(path)
    with tm('depth'):
        d = model('depth')(frame)
        d = guided_filter(gray(frame), d, 8, 1e-3)             # snap depth edges to image edges
        d = cv2.GaussianBlur(d, (0, 0), spec.get('depth_blur', 3.0))
    if path:
        np.save(path, d.astype(np.float32))
    return d.astype(np.float32)

# ============================================================================ motion-blur helper
def _cam(c, u):
    """camera spec {'z0','z1','x0','x1','y0','y1','r0','r1','ease'} -> (zoom, tx_frac, ty_frac, rot) at u."""
    e = ease(u, c.get('ease', 'io'))
    lerp = lambda a, b: c.get(a, 0 if a[0] != 'z' else 1.0) + (c.get(b, c.get(a, 0 if a[0] != 'z' else 1.0)) - c.get(a, 0 if a[0] != 'z' else 1.0)) * e
    return lerp('z0', 'z1'), lerp('x0', 'x1'), lerp('y0', 'y1'), lerp('r0', 'r1')

def _subsamples(n, k, mb, disp_fn):
    """motion blur: sub-frame times around frame k; count adapts to pixel displacement over the shutter."""
    if not mb:
        return [k / max(n - 1, 1)]
    sh = mb.get('shutter', 0.5)
    u0, u1 = (k - sh / 2) / max(n - 1, 1), (k + sh / 2) / max(n - 1, 1)
    d = disp_fn(u0, u1)
    S = int(min(mb.get('max_samples', 12), max(1, math.ceil(d / mb.get('px_per_sample', 1.5)))))
    if S == 1:
        return [k / max(n - 1, 1)]
    return list(np.linspace(u0, u1, S))

# ============================================================================ effects
def _load(spec, tm):
    n = spec.get('n') or frames_of(spec['dur'])
    with tm('decode'):
        frames = read_frames(spec['src'], spec.get('t0', 0.0), n)
    key = [_src_id(spec['src']), round(spec.get('t0', 0.0), 4), n]
    return frames, n, key

def fx_passthrough(spec, tm, rep):
    frames, n, key = _load(spec, tm)
    for k in range(n):
        yield f32(frames[k])

def fx_matte(spec, tm, rep):
    """QA render: cut-out over a solid colour (default magenta) to expose haloes / chatter."""
    frames, n, key = _load(spec, tm)
    ms = MatteSeq(frames, spec.get('matte'), key, tm)
    rep['matte_cached'] = ms.cached
    if spec.get('metrics', True):
        rep['flicker'] = ms.metrics()
    col = np.array(spec.get('bg_color', (1.0, 0.0, 1.0)), np.float32)
    rep['_alphas'] = []
    for k in range(n):
        a = ms.alpha(k)
        with tm('composite'):
            Fg = decontaminate(frames[k], a) if spec.get('decontaminate', True) else f32(frames[k])
            if spec.get('codec') == 'prores4444':          # straight RGBA cut-out layer for other compositors
                out = np.dstack([Fg, a])
            else:
                bg = np.empty_like(Fg); bg[:] = col
                out = over(bg, Fg, a)
        if k % max(1, n // 8) == 0:
            rep['_alphas'].append((k, a))
        yield out

def fx_parallax(spec, tm, rep):
    """2.5D camera move. spec: cam{z0,z1,x0,x1,y0,y1,r0,r1,ease}, fg_rate (1.5), bg_rate (0.5),
    fg_pivot 'auto'|(x,y) px, bg_blur sigma (or [s0,s1] ramp), plate{mode..}, motion_blur{shutter,max_samples}"""
    frames, n, key = _load(spec, tm)
    ms = MatteSeq(frames, spec.get('matte'), key, tm)
    if spec.get('metrics', True):
        rep['flicker'] = ms.metrics()
    plate, hole = clean_plate(frames, ms, spec.get('plate'), key, tm)
    rep['plate_hole_frac'] = round(float(hole.mean()), 4)
    rep['_plate'] = plate
    plate_f = f32(plate)
    cam = spec.get('cam', {'z0': 1.0, 'z1': 1.12})
    fr_, br_ = spec.get('fg_rate', 1.5), spec.get('bg_rate', 0.5)
    piv = spec.get('fg_pivot', 'auto')
    if piv == 'auto':
        x0, y0, x1, y1 = ms.bbox(0)
        piv = ((x0 + x1) / 2, H if y1 >= H - 4 else (y0 + y1) / 2)
    over_scan = spec.get('bg_overscan', 1.0 + 2 * max(abs(cam.get('x0', 0)), abs(cam.get('x1', 0))) * br_
                         + 2 * max(abs(cam.get('y0', 0)), abs(cam.get('y1', 0))) * br_)

    def mats(u):
        z, tx, ty, r = _cam(cam, u)
        Mb = affine((1 + (z - 1) * br_) * over_scan, (W / 2, H / 2), (tx * W * br_, ty * H * br_), r * br_)
        Mf = affine(1 + (z - 1) * fr_, piv, (tx * W * fr_, ty * H * fr_), r * fr_)
        return Mb, Mf

    def disp(u0, u1):
        corners = np.array([[0, 0, 1], [W, 0, 1], [0, H, 1], [W, H, 1], [piv[0], piv[1] - H * 0.5, 1]], np.float32).T
        (a0, f0), (a1, f1) = mats(u0), mats(u1)
        return float(max(np.abs(f1 @ corners - f0 @ corners).max(), np.abs(a1 @ corners - a0 @ corners).max()))

    mb = spec.get('motion_blur')
    blur = spec.get('bg_blur', 0)
    for k in range(n):
        a = ms.alpha(k)
        with tm('composite'):
            Fg = decontaminate(frames[k], a, plate if spec.get('unmix', True) else None)
            pm = np.dstack([Fg * a[..., None], a])
            us = _subsamples(n, k, mb, disp)
            acc_b = 0; acc_f = 0
            for u in us:
                Mb, Mf = mats(u)
                acc_b = acc_b + warp(plate_f, Mb)
                acc_f = acc_f + warp(pm, Mf, border='const')
            B, P = acc_b / len(us), acc_f / len(us)
            sg = blur if not isinstance(blur, (list, tuple)) else blur[0] + (blur[1] - blur[0]) * ease(k / max(n - 1, 1), 'io')
            if sg > 0.3:
                B = cv2.GaussianBlur(B, (0, 0), sg)
            out = P[..., :3] + B * (1 - P[..., 3:4])        # premultiplied over
        rep.setdefault('_samples', []).append(len(us))
        yield out

def fx_depth_parallax(spec, tm, rep):
    """Depth-driven camera for landscapes. spec: cam{z0,z1,x0,x1,y0,y1,ease} (x/y = shift of the
    NEAR plane as fraction of W/H), depth_gain (near zooms this much more than far, 1.0), focus (0..1
    depth that stays locked, 0 = horizon), overscan (1.04), depth_mode 'static'|'per_frame', motion_blur."""
    frames, n, key = _load(spec, tm)
    df = spec.get('depth_frame', n // 2)
    D = depth_map(frames[df], {**spec, 'depth_frame': df}, key, tm)
    rep['_depth'] = D
    cam = spec.get('cam', {'z0': 1.0, 'z1': 1.08, 'x0': 0.0, 'x1': -0.02})
    gain, focus, osc = spec.get('depth_gain', 1.0), spec.get('focus', 0.0), spec.get('overscan', 1.04)
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    cx, cy = W / 2, H / 2

    def maps(u):
        z, tx, ty, _ = _cam(cam, u)
        qx, qy = gx.copy(), gy.copy()
        for _ in range(3):                                        # fixed-point: depth at the source pixel
            d = cv2.remap(D, qx, qy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            s = osc * (1 + (z - 1) * (1 + gain * (d - focus)))
            qx = cx + (gx - cx - tx * W * (d - focus)) / s
            qy = cy + (gy - cy - ty * H * (d - focus)) / s
            qx, qy = qx.astype(np.float32), qy.astype(np.float32)
        return qx, qy

    def disp(u0, u1):
        a, b = maps(u0), maps(u1)
        return float(np.percentile(np.hypot(a[0] - b[0], a[1] - b[1])[::8, ::8], 99))

    mb = spec.get('motion_blur')
    for k in range(n):
        with tm('composite'):
            img = f32(frames[k])
            us = _subsamples(n, k, mb, disp) if mb else [k / max(n - 1, 1)]
            acc = 0
            for u in us:
                qx, qy = maps(u)
                acc = acc + cv2.remap(img, qx, qy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT101)
            out = acc / len(us)
        rep.setdefault('_samples', []).append(len(us))
        yield out

def fx_freeze_pop(spec, tm, rep):
    """定格抠像. spec: freeze_at (frame idx, default 0), live (frames of live action before the freeze),
    pop_frames (6), flash (0.6), bg{darken .45, blur 10, desat .6, tint (r,g,b), tint_amt .25, z 1.0->1.03},
    fg{stroke 7, stroke_color, glow_sigma 26, glow_color, glow_strength .9, s0 1.0, s1 1.07, drift (dx,dy) px,
    hold_z .02}, behind 'burst'|'speedlines'|None, behind_color, behind_opacity, lines{n,..}"""
    n = spec.get('n') or frames_of(spec['dur'])
    fi = spec.get('freeze_at', 0)
    live = spec.get('live', fi)
    hold = spec.get('hold')                    # frames the freeze lasts; None = freeze to the end of the clip
    with tm('decode'):
        allf = read_frames(spec['src'], spec.get('t0', 0.0), n)
    # matte only a short window ending at the freeze frame (flow-compensated smoothing needs history)
    w0 = max(0, fi - spec.get('matte_window', 12))
    frames = allf[w0:fi + 1]
    key = [_src_id(spec['src']), round(spec.get('t0', 0.0), 4), w0, fi + 1]
    ms = MatteSeq(frames, spec.get('matte'), key, tm)
    fi_w = fi - w0                              # freeze index inside the matte window
    if spec.get('metrics', True):
        rep['flicker'] = ms.metrics()
    a0 = ms.alpha(fi_w)
    plate, hole = clean_plate(frames, ms, spec.get('plate'), key, tm, frame_idx=fi_w)
    rep['plate_hole_frac'] = round(float(hole.mean()), 4)
    rep['_plate'] = plate; rep['_alphas'] = [(fi, a0)]
    Fz = decontaminate(frames[fi_w], a0, plate)
    bgs, fgs = {**dict(darken=0.45, blur=10, desat=0.6, tint=(0.25, 0.35, 0.7), tint_amt=0.25, z0=1.0, z1=1.04)}, None
    bgs.update(spec.get('bg', {}))
    fgs = dict(stroke=7, stroke_color=(1, 1, 1), glow_sigma=26, glow_color=(1.0, 0.75, 0.45), glow_strength=0.9,
               s0=1.0, s1=1.07, drift=(0, -10), hold_z=0.025)
    fgs.update(spec.get('fg', {}))
    x0, y0, x1, y1 = ms.bbox(fi_w)
    piv = spec.get('pivot') or ((x0 + x1) / 2, H if y1 >= H - 4 else (y0 + y1) / 2)
    st = stroke_alpha(a0, fgs['stroke']) if fgs['stroke'] > 0 else a0
    glow = cv2.GaussianBlur(st, (0, 0), fgs['glow_sigma']) if fgs['glow_strength'] > 0 else None
    P = f32(plate)
    behind = spec.get('behind', 'burst')
    bc = np.array(spec.get('behind_color', (1.0, 0.92, 0.75)), np.float32)
    lc = (piv[0], (y0 + y1) / 2)
    pop = spec.get('pop_frames', 6)
    for k in range(n):
        if k < live:                       # live action up to the hit
            yield f32(allf[k])
            continue
        if hold is not None and k >= live + hold:      # freeze swallowed source time; resume live motion
            r = k - live - hold
            img = f32(allf[k])
            rf = spec.get('resume_flash', 0.0)   # default off: a second white flash at the unfreeze stacks with the pop flash
            if rf and r < 3:
                img = img + rf * (0.45 ** r) * (1 - img)
            yield img
            continue
        j = k - live
        nh = (hold if hold is not None else n - live)
        with tm('composite'):
            u = min(1.0, j / max(pop, 1))
            ub = ease(min(1.0, j / max(pop * 2, 1)), 'o')
            # background: blur / desat / darken / tint ramp in, slow counter-push
            sg = bgs['blur'] * ub
            zb = bgs['z0'] + (bgs['z1'] - bgs['z0']) * (j / max(nh - 1, 1))
            B = warp(P, affine(zb, (W / 2, H / 2)))
            if sg > 0.3:
                B = cv2.GaussianBlur(B, (0, 0), sg)
            B = desaturate(B, bgs['desat'] * ub)
            B = B * (1 - bgs['darken'] * ub)
            B = B * (1 - bgs['tint_amt'] * ub) + np.array(bgs['tint'], np.float32) * B.mean(2, keepdims=True) * 2 * bgs['tint_amt'] * ub
            # character transform: ease-out-back pop then slow hold zoom + drift
            s = fgs['s0'] + (fgs['s1'] - fgs['s0']) * ease(u, 'back')
            hp = j / max(nh - 1, 1)
            s *= 1 + fgs['hold_z'] * hp
            dx, dy = fgs['drift'][0] * hp, fgs['drift'][1] * hp
            M = affine(s, piv, (dx, dy))
            if behind == 'burst':
                rays = light_burst((W, H), (lc[0] + dx, lc[1] + dy), phase=0.004 * j, seed=spec.get('seed', 7))
                B = screen(B, rays[..., None] * bc * spec.get('behind_opacity', 0.55) * ub)
            elif behind == 'speedlines':
                lsp = spec.get('lines', {})
                rgb, la = speed_lines((W, H), (lc[0] + dx, lc[1] + dy), seed=spec.get('seed', 7) + j // lsp.get('boil', 2),
                                      n=lsp.get('n', 90), color=tuple(lsp.get('color', (1, 1, 1))))
                B = over(B, rgb, la * spec.get('behind_opacity', 0.8) * ub)
            if glow is not None:
                g = warp(glow, M, border='const')[..., None] * np.array(fgs['glow_color'], np.float32)
                B = screen(B, np.clip(g * fgs['glow_strength'] * 1.6 * ub, 0, 1))
            sa = warp(st, M, border='const')
            B = over(B, np.array(fgs['stroke_color'], np.float32)[None, None], sa * min(1.0, j / 2 + 0.5))
            pm = warp(np.dstack([Fz * a0[..., None], a0]), M, border='const')
            out = pm[..., :3] + B * (1 - pm[..., 3:4])
            fl = spec.get('flash', 0.6)
            if fl and j < 4:
                out = out + fl * (0.5 ** j) * (1 - out) if j > 0 else out * (1 - fl) + fl
        yield out

def make_text_rgba(text, font=None, size=300, color=(255, 255, 255), stroke=0, stroke_color=(0, 0, 0),
                   pos=(0.5, 0.5), tracking=0, canvas=(W, H), shadow=None):
    """Render a text layer to a full-frame RGBA uint8 (Pillow). pos = centre (fractions of the canvas)."""
    from PIL import Image, ImageDraw, ImageFont
    cands = [font] if font else ['/System/Library/Fonts/Avenir Next Condensed.ttc', '/System/Library/Fonts/Helvetica.ttc',
                                 '/Library/Fonts/Arial Unicode.ttf', 'DejaVuSans-Bold.ttf']
    fnt = None
    for c in cands:
        try:
            fnt = ImageFont.truetype(c, size, index=0) if not str(c).endswith('.ttc') else ImageFont.truetype(c, size, index=_bold_index(c))
            break
        except Exception:
            continue
    fnt = fnt or ImageFont.load_default()
    im = Image.new('RGBA', canvas, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    widths = [d.textlength(ch, font=fnt) for ch in text]
    tw = sum(widths) + tracking * (len(text) - 1)
    bb = d.textbbox((0, 0), text, font=fnt, stroke_width=stroke)
    th = bb[3] - bb[1]
    x = canvas[0] * pos[0] - tw / 2
    y = canvas[1] * pos[1] - th / 2 - bb[1]
    for ch, w_ in zip(text, widths):
        d.text((x, y), ch, font=fnt, fill=tuple(color) + (255,), stroke_width=stroke, stroke_fill=tuple(stroke_color) + (255,))
        x += w_ + tracking
    return np.array(im)

def _bold_index(path):
    if 'Avenir Next Condensed' in path:
        return 8          # Heavy (face order in the macOS collection)
    if 'Helvetica.ttc' in path:
        return 1
    return 0

def fx_text_behind(spec, tm, rep):
    """Text between background and character. spec: text_rgba (HxWx4 uint8 array or PNG path) or
    text{...make_text_rgba kwargs}; anim{in_frames 12, from_scale 1.12, from_alpha 0, from_dy 40, ease 'o'},
    text_opacity 1, text_blend 'normal'|'screen', cam{z0,z1,...} applied to the scene, text_rate (0.6 -> text
    moves less than the scene = sits further back), fg_lift (0: cut-out moves with the scene)."""
    frames, n, key = _load(spec, tm)
    ms = MatteSeq(frames, spec.get('matte'), key, tm)
    if spec.get('metrics', True):
        rep['flicker'] = ms.metrics()
    T = spec.get('text_rgba')
    if isinstance(T, str):
        T = cv2.cvtColor(cv2.imread(T, cv2.IMREAD_UNCHANGED), cv2.COLOR_BGRA2RGBA)
    if T is None:
        T = make_text_rgba(**spec.get('text', {'text': 'TEXT'}))
    Tf = T.astype(np.float32) / 255.0
    tpm = np.dstack([Tf[..., :3] * Tf[..., 3:4], Tf[..., 3]])      # premultiplied
    an = {**dict(in_frames=12, from_scale=1.12, from_alpha=0.0, from_dy=40, ease='o', drift_z=0.03), **spec.get('anim', {})}
    cam = spec.get('cam', {'z0': 1.0, 'z1': 1.0})
    trate = spec.get('text_rate', 0.6)
    op, blend = spec.get('text_opacity', 1.0), spec.get('text_blend', 'normal')
    for k in range(n):
        a = ms.alpha(k)
        with tm('composite'):
            u = k / max(n - 1, 1)
            z, tx, ty, r = _cam(cam, u)
            Ms = affine(z, (W / 2, H / 2), (tx * W, ty * H), r)
            ui = ease(min(1.0, k / max(an['in_frames'], 1)), an['ease'])
            ts = (an['from_scale'] + (1 - an['from_scale']) * ui) * (1 + an['drift_z'] * u) * (1 + (z - 1) * trate)
            Mt = affine(ts, (W / 2, H / 2), (tx * W * trate, ty * H * trate + an['from_dy'] * (1 - ui)), r * trate)
            ta = an['from_alpha'] + (1 - an['from_alpha']) * ui
            I = f32(frames[k])
            Fg = decontaminate(frames[k], a)
            Bw = warp(I, Ms) if (z != 1 or tx or ty or r) else I
            tl = warp(tpm, Mt, border='const') * (ta * op)
            if blend == 'screen':
                Bt = screen(Bw, tl[..., :3])
            else:
                Bt = tl[..., :3] + Bw * (1 - tl[..., 3:4])
            fa = warp(a, Ms, border='const') if Bw is not I else a
            Fw = warp(Fg, Ms) if Bw is not I else Fg
            out = over(Bt, Fw, fa)
        yield out

def fx_zoom_through(spec, tm, rep):
    """Zoom-through radial-blur transition. spec: a{src,t0,n,center(0.5,0.5),zoom 2.6}, b{src,t0,n,center,
    zoom 1.9}, blur 0.45 (radial amount at the cut), flash 0.5, chroma 6 (px at cut), ease_a 'i' ease_b 'o'.
    Output = a.n + b.n frames (A's tail accelerates in, B's head decelerates out of the blur)."""
    A, B = spec['a'], spec['b']
    with tm('decode'):
        fa = read_frames(A['src'], A.get('t0', 0), A['n'])
        fb = read_frames(B['src'], B.get('t0', 0), B['n'])
    peak, fl, ca = spec.get('blur', 0.45), spec.get('flash', 0.5), spec.get('chroma', 6.0)
    na, nb = A['n'], B['n']
    for side, frs, S in (('a', fa, A), ('b', fb, B)):
        c = S.get('center', (0.5, 0.5)); cp = (c[0] * W, c[1] * H)
        nn = len(frs)
        for k in range(nn):
            with tm('composite'):
                if side == 'a':
                    u = ease((k + 1) / nn, spec.get('ease_a', 'i')); z = 1 + (S.get('zoom', 2.6) - 1) * u
                    amt = peak * u ** 1.5
                else:
                    u = ease(k / nn, spec.get('ease_b', 'o')); z = S.get('zoom', 1.9) + (1 - S.get('zoom', 1.9)) * u
                    amt = peak * (1 - u) ** 1.5
                img = warp(f32(frs[k]), affine(z, cp))
                img = radial_blur(img, cp, amt, passes=5, inward=False)
                g = amt / max(peak, 1e-6)
                if fl:
                    img = img + fl * g ** 3 * (1 - img)
                if ca:
                    img = chroma(img, ca * g)
            yield img

def qa_matte_sheet(frames, ms, idxs, out, crop=None, plate=None):
    """QA: per row = frame | matte | cut-out over magenta | 1:1 edge crop over magenta (1/4 res tiles).
    crop = (x, y, w, h) full-res region for the 1:1 tile (default: around the matte's top edge)."""
    rows = []
    for t in idxs:
        a = ms.alpha(t)
        Fg = decontaminate(frames[t], a, plate)
        mag = over(np.array([1, 0, 1], np.float32)[None, None] * np.ones_like(Fg), Fg, a)
        if crop is None:
            x0, y0, x1, y1 = ms.bbox(t)
            cw, ch = 480, 270
            cx = int(min(max((x0 + x1) / 2 - cw / 2, 0), W - cw)); cy = int(min(max(y0 - 40, 0), H - ch))
            c = (cx, cy, cw, ch)
        else:
            c = crop
        tile = lambda im: cv2.resize((np.clip(f32(im), 0, 1) * 255).astype(np.uint8), (480, 270), interpolation=cv2.INTER_AREA)
        cr = (np.clip(mag[c[1]:c[1] + c[3], c[0]:c[0] + c[2]], 0, 1) * 255).astype(np.uint8)
        cr = cv2.resize(cr, (480, 270), interpolation=cv2.INTER_NEAREST)
        rows.append(np.hstack([tile(frames[t]), cv2.cvtColor(tile(a), cv2.COLOR_GRAY2RGB), tile(mag), cr]))
        cv2.putText(rows[-1], f'f{t}', (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
    cv2.imwrite(out, cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))
    return out

def fx_godrays(spec, tm, rep):
    """God rays from a point light (candle / lamp flame). spec: center (fx,fy fractions) or 'auto' (brightest blob
    of frame 0, locked), light{threshold .8, length .5, strength .6, tint, passes 7, softness .1},
    flicker (0.15: strength wobble), bloom (0.25: soft halo on the source), occlude (False), matte{}.
    Rays come from the shot's own bright pixels (the flame), radiating from a locked centre. Fixed light only."""
    frames, n, key = _load(spec, tm)
    L = {**dict(threshold=0.8, length=0.5, strength=0.6, tint=(1.0, 0.8, 0.5), passes=7, softness=0.1, res=0.5, ang=0.6), **spec.get('light', {})}
    ms = MatteSeq(frames, spec.get('matte'), key, tm) if spec.get('occlude') else None
    c = spec.get('center', 'auto')
    rng = np.random.default_rng(spec.get('seed', 3))
    fl, bl = spec.get('flicker', 0.15), spec.get('bloom', 0.25)
    track, cur = spec.get('track', False), None
    phase = rng.uniform(0, 6.28, 3)
    ref_mass = 1.0
    shafts = spec.get('shafts', 0.5)      # opacity of the synthetic shaft layer (light_burst) gated by flame brightness
    if c == 'auto':          # lock the light to the brightest compact blob over the whole clip (flame may be unlit at frame 0)
        best = (-1.0, None)
        for k in range(0, n, max(1, n // 12)):
            m = np.clip((gray(f32(frames[k])) - L['threshold']) / L['softness'], 0, 1)
            b = cv2.GaussianBlur(m, (0, 0), 12)
            if b.max() > best[0]:
                cy, cx = np.unravel_index(np.argmax(b), b.shape)
                best = (float(b.max()), (cx / W, cy / H))
        c = best[1] or (0.5, 0.5)
        track = False
        ref_mass = max(best[0], 1e-6)
    for k in range(n):
        img = f32(frames[k])
        with tm('composite'):
            occ = ms.alpha(k) if ms is not None else None
            cc = c
            st = L['strength'] * (1 + fl * (0.6 * math.sin(k * 0.9 + phase[0]) + 0.4 * math.sin(k * 2.3 + phase[1])))
            out, cc2 = god_rays(img, center=cc, occluder=occ, **{**L, 'strength': st, 'ang_phase': 0.02 * k})
            if track and cur is not None:
                cc2 = (0.7 * cur[0] + 0.3 * cc2[0], 0.7 * cur[1] + 0.3 * cc2[1])
            cur = (c if not track else cc2)
            if bl:
                m = np.clip((gray(img) - L['threshold']) / L['softness'], 0, 1)
                hal = cv2.GaussianBlur(m, (0, 0), 28)[..., None] * np.array(L['tint'], np.float32)
                out = screen(out, hal * bl * (st / L['strength']))
            if shafts:
                mk = cv2.GaussianBlur(np.clip((gray(img) - L['threshold']) / L['softness'], 0, 1), (0, 0), 12).max()
                gate = float(np.clip(mk / ref_mass, 0, 1)) ** 1.5
                sh = light_burst((W, H), (c[0] * W, c[1] * H), phase=0.003 * k, n_rays=spec.get('n_shafts', 14), sharp=5.0,
                                 falloff=0.45, seed=spec.get('seed', 3))
                out = screen(out, sh[..., None] * np.array(L['tint'], np.float32) * shafts * gate * (st / L['strength']))
            rep['light_center'] = [round(float(cur[0]), 4), round(float(cur[1]), 4)]
        yield out

FX = {'godrays': fx_godrays, 'passthrough': fx_passthrough, 'matte': fx_matte, 'parallax': fx_parallax, 'depth_parallax': fx_depth_parallax,
      'freeze_pop': fx_freeze_pop, 'text_behind': fx_text_behind, 'zoom_through': fx_zoom_through}

# ============================================================================ driver
def render(spec):
    """Render one precomp. Returns a report (frames, timings, s/frame, flicker metrics) also written to out+'.json'.
    Common keys: fx, src, t0, n|dur, out, codec ('prores'|'h264'|'prores4444'), post [...], sheet (path),
    sheet_idxs, matte{...}, plate{...}, cache_dir."""
    tm = Timer(); rep = {'fx': spec['fx'], 'out': spec['out']}
    t_start = time.perf_counter()
    if spec['fx'] == 'zoom_through':
        n = spec['a']['n'] + spec['b']['n']
    else:
        n = spec.get('n') or frames_of(spec['dur'])
    wr = Writer(spec['out'], n, spec.get('codec') or ('h264' if spec['out'].lower().endswith(('.mp4', '.m4v')) else 'prores'))
    keep = {}
    want = set(spec.get('sheet_idxs') or np.linspace(0, n - 1, min(8, n)).round().astype(int).tolist())
    ctx = {}
    try:
        for k, fr in enumerate(FX[spec['fx']](spec, tm, rep)):
            if spec.get('post'):
                with tm('post'):
                    fr = apply_post(fr, spec['post'], k, ctx)
            if k in want:
                keep[k] = (np.clip(fr[..., :3], 0, 1) * 255).astype(np.uint8)
            with tm('encode'):
                wr.write(fr)
        rep['frames'] = wr.close()
    except BaseException:
        try:
            wr.p.kill()
        except Exception:
            pass
        raise
    total = time.perf_counter() - t_start
    rep['seconds'] = round(total, 2)
    rep['s_per_frame'] = round(total / n, 3)
    rep['timings_s'] = {k: round(v, 2) for k, v in tm.t.items()}
    if rep.get('_samples'):
        rep['mb_samples_mean'] = round(float(np.mean(rep['_samples'])), 2)
    if spec.get('sheet'):
        ks = sorted(keep)
        contact_sheet([keep[i] for i in ks], spec['sheet'], idxs=list(range(len(ks))), labels=[f'f{i}' for i in ks])
        rep['sheet'] = spec['sheet']
    extras = {k: rep.pop(k) for k in list(rep) if k.startswith('_')}
    with open(spec['out'] + '.json', 'w') as f:
        json.dump({'spec': {k: v for k, v in spec.items() if k != 'text_rgba'}, 'report': rep}, f, indent=1, default=str)
    rep['_extras'] = extras
    return rep

# ============================================================================ public API
def find_episode(ep, root=None, video=None):
    """episode number -> mkv path. Searches <root>/downloads/*/*- NN [*.mkv ; root = arg | $MAD_ROOT | cwd and parents."""
    import glob
    if video:
        return video
    roots = [root] if root else ([os.environ['MAD_ROOT']] if os.environ.get('MAD_ROOT') else [])
    if not roots:
        d = os.getcwd()
        while True:
            roots.append(d)
            if os.path.dirname(d) == d:
                break
            d = os.path.dirname(d)
    for r in roots:
        for pat in (f'{r}/downloads/*/*- {int(ep):02d} [[]*.mkv', f'{r}/downloads/*/*{int(ep):02d}*.mkv', f'{r}/*- {int(ep):02d} [[]*.mkv'):
            g = sorted(glob.glob(pat))
            if g:
                return g[0]
    raise FileNotFoundError(f'episode {ep} not found (set spec["video"], spec["root"] or $MAD_ROOT)')

EFFECTS = {'freeze_pop': 'freeze_pop', 'parallax': 'parallax', 'depth_dolly': 'depth_parallax', 'text_behind': 'text_behind',
           'godrays': 'godrays', 'matte': 'matte'}

def render_precomp(spec, out_path):
    """Render one precomp -> out_path (.mp4 = H.264 CRF10 yuv420p, .mov = ProRes 422 HQ). Returns frames written.
    Always 1920x1080 @ 24000/1001, exactly round(dur*24000/1001) frames, starting at source time `src`.
    Common keys: effect, ep (episode no.) | video (explicit path), src (s, start in the episode), dur (s),
                 root (project root with downloads/), cache_dir, matte{}, post[], sheet (contact-sheet jpg), codec.
    freeze_pop : freeze_at (s, abs src time of the apex), hold (s, 0.6), + fx_freeze_pop keys (bg{}, fg{}, behind
                 'burst'|'speedlines'|None, pop_frames, flash, resume_flash). The hold REPLACES source time
                 [freeze_at, freeze_at+hold]; live motion resumes at src time freeze_at+hold, total length unchanged.
    parallax   : cam{z0,z1,x0,x1,y0,y1,ease}, fg_rate (1.5), bg_rate (.5), bg_blur, plate{}, motion_blur{} (static-ish
                 shots; fg = anime-seg matte, bg = median/LaMa clean plate)
    depth_dolly: cam{...}, depth_gain, focus, overscan, depth_frame, motion_blur{} (Depth Anything V2 small displacement)
    text_behind: text{text,font,size,color,stroke,pos,tracking} | text_rgba, anim{}, cam{}, text_rate, text_blend
    godrays    : center (fx,fy)|'auto', light{threshold,length,strength,tint,passes}, flicker, bloom, occlude
    Prints/returns the frame count; the JSON report (s/frame, timings, flicker metrics) goes to out_path+'.json'."""
    sp = dict(spec)
    eff = sp.pop('effect', None) or sp.get('fx')
    if eff not in EFFECTS:
        raise ValueError(f'effect must be one of {sorted(EFFECTS)}')
    sp['fx'] = EFFECTS[eff]
    if 'ep' in sp or 'video' in sp:
        sp['src_video'] = find_episode(sp.get('ep'), sp.get('root'), sp.get('video'))
        t0 = sp.pop('src', sp.get('t0', 0.0))
        sp['t0'] = float(t0)
        sp['src'] = sp['src_video']
    sp['n'] = frames_of(sp['dur']) if 'dur' in sp else sp['n']
    sp.pop('dur', None)
    sp['out'] = out_path
    if eff == 'freeze_pop':
        fa = float(sp.pop('freeze_at', sp['t0'] + 0.5 * sp['n'] / FF))
        sp['freeze_at'] = int(math.floor((fa - sp['t0']) * FF + 0.5))
        sp['live'] = sp['freeze_at']
        sp['hold'] = frames_of(sp.pop('hold', 0.6))
        sp['hold'] = min(sp['hold'], sp['n'] - sp['live'])
    rep = render(sp)
    return rep['frames']

def zoom_through(clip_a, clip_b, out, frames, **kw):
    """Radial-blur zoom-through transition between two clips -> out (mp4/mov). clip = path | dict(src, t0, center,
    zoom [, ep, root]); A plays its tail (zoom in, blur), B its head (zoom out of blur). frames = TOTAL output frames
    (A gets frames//2, B the rest). t0 is where the clip starts, so give A's t0 = (cut_time_a - A_frames/fps).
    Extra kw -> spec keys (blur .45, flash .5, chroma 6, ease_a, ease_b, codec). Returns frames written."""
    def norm(c, n):
        c = {'src': c} if isinstance(c, str) else dict(c)
        if 'ep' in c:
            c['src'] = find_episode(c['ep'], c.get('root'), c.get('video'))
        c.setdefault('t0', 0.0); c['n'] = n
        return c
    na = frames // 2
    spec = dict(fx='zoom_through', a=norm(clip_a, na), b=norm(clip_b, frames - na), out=out, **kw)
    return render(spec)['frames']

def main(argv):
    if not argv:
        print(__doc__); return
    if len(argv) == 2 and argv[1].lower().endswith(('.mp4', '.mov', '.m4v')):      # ae.py spec.json out.mp4
        spec = json.load(open(argv[0]))
        if spec.get('effect') == 'zoom_through' or spec.get('fx') == 'zoom_through':
            n = zoom_through(spec['a'], spec['b'], argv[1], spec['frames'], **{k: v for k, v in spec.items() if k not in ('a', 'b', 'frames', 'effect', 'fx')})
        else:
            n = render_precomp(spec, argv[1])
        print(f'frames={n}')
        return
    for p in argv:                                                                    # legacy: ae.py spec.json [spec2.json]
        specs = json.load(open(p))
        for s in (specs if isinstance(specs, list) else [specs]):
            r = render(s); r.pop('_extras', None)
            print(json.dumps(r))

if __name__ == '__main__':
    main(sys.argv[1:])
