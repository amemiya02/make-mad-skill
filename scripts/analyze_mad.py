"""Measure a finished MAD: shots, transitions, cut-to-music alignment, camera moves, overlays + review sheets.

usage: analyze_mad.py VIDEO OUTDIR
Outputs in OUTDIR:
  metrics.json      summary numbers (see keys at the end of main())
  shots.csv         idx,start_s,end_s,dur_s,in_kind,luma,sat,motion,scale_per_s,shake
  shotboard-N.jpg   one frame per shot in order (narrative structure, shot choice)
  transitions-N.jpg 8-frame strips of every soft transition (dissolve/flash/fade) + a sample of hard cuts
  curve.png         timeline: cuts/10 s, music RMS, picture luma, beats
Honesty: this is measurement + still frames; it is not watching or listening.
"""
import sys, os, json, math, subprocess
import numpy as np, cv2, librosa
from PIL import Image, ImageDraw, ImageFont

FONT = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 13)
SW, SH = 160, 90        # metric resolution
TW, TH = 240, 135       # sheet thumbnails


def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=r_frame_rate,nb_frames:format=duration',
                          '-of', 'json', path], capture_output=True, text=True).stdout
    j = json.loads(out); n, d = j['streams'][0]['r_frame_rate'].split('/')
    return float(n) / float(d), float(j['format']['duration'])


def frames(path, w, h):
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', path, '-vf', f'scale={w}:{h}:flags=area', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                         stdout=subprocess.PIPE)
    sz = w * h * 3
    while True:
        b = p.stdout.read(sz)
        if len(b) < sz:
            break
        yield np.frombuffer(b, np.uint8).reshape(h, w, 3)
    p.wait()


def main():
    vid, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    fps, dur = probe(vid)

    # ---- pass 1: per-frame metrics at 160x90
    G, C, L, S = [], [], [], []
    for fr in frames(vid, SW, SH):
        g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(fr, cv2.COLOR_RGB2HSV)
        G.append(g); C.append(cv2.resize(fr, (40, 22), interpolation=cv2.INTER_AREA).astype(np.float32))
        L.append(g.mean()); S.append(hsv[..., 1].mean())
    G = np.array(G); C = np.array(C); L = np.array(L); S = np.array(S); n = len(G)
    Gf = G.astype(np.float32)
    d = np.r_[0, np.abs(np.diff(Gf, axis=0)).mean(axis=(1, 2))]
    hist = np.array([np.histogram(g, bins=16, range=(0, 255))[0] / g.size for g in G])
    hd = np.r_[0, np.abs(np.diff(hist, axis=0)).sum(axis=1)]

    # hard cuts (same rule as fxkit/cutguard: absolute + spike vs local median, or histogram jump)
    hard = []
    for i in range(1, n):
        loc = np.median(np.r_[d[max(1, i - 6):i], d[i + 1:i + 7]]) if n > 3 else 0
        if (d[i] > 18 and d[i] > 3.5 * max(loc, 2)) or (hd[i] > 0.55 and d[i] > 10):
            hard.append(i)
    # flashes: a short bright run (luma jump > 50 to > 200) — white-frame transitions or source light
    flash = []
    i = 1
    while i < n:
        if L[i] > 200 and L[i] - L[i - 1] > 50:
            j = i
            while j < n and L[j] > 170 and j - i < 12:
                j += 1
            flash.append((i, j)); i = j
        i += 1
    # dips to black
    fades = []
    i = 0
    while i < n:
        if L[i] < 10:
            j = i
            while j < n and L[j] < 10:
                j += 1
            if j - i >= 2:
                fades.append((i, j))
            i = j
        i += 1
    # dissolves: frame ≈ average of frames k before/after, endpoints differ, no hard cut inside
    k = 4; hs = set(hard); dis_frames = []
    for i in range(k, n - k):
        if any(x in hs for x in range(i - k + 1, i + k + 1)):
            continue
        a, b = C[i - k], C[i + k]
        span = np.abs(a - b).mean()
        if span < 18:
            continue
        r = np.abs(C[i] - 0.5 * (a + b)).mean()
        if r < 0.22 * span:
            dis_frames.append(i)
    dissolves = []
    for i in dis_frames:
        if dissolves and i - dissolves[-1][1] <= 2:
            dissolves[-1][1] = i
        else:
            dissolves.append([i, i])
    dissolves = [(a - k, b + k) for a, b in dissolves if b - a >= 2]

    # ---- shot boundaries
    bounds = sorted(set([0] + hard + [int((a + b) / 2) for a, b in dissolves] + [b for a, b in fades if a > 0]))
    bounds = [b for idx, b in enumerate(bounds) if idx == 0 or b - bounds[idx - 1] >= 2] + [n]
    kind_at = {b: 'cut' for b in hard}
    for a, b in dissolves:
        kind_at[int((a + b) / 2)] = 'dissolve'
    for a, b in fades:
        kind_at[b] = 'fade'
    for a, b in flash:
        for x in range(max(0, a - 2), b + 3):
            if x in kind_at:
                kind_at[x] = 'flash+' + kind_at[x]

    # ---- per-frame translation (shake) via phase correlation
    tx = np.zeros(n); ty = np.zeros(n)
    win = cv2.createHanningWindow((SW, SH), cv2.CV_32F)
    for i in range(1, n):
        if i in hs:
            continue
        (sx, sy), resp = cv2.phaseCorrelate(Gf[i - 1], Gf[i], win)
        if resp > 0.2:
            tx[i], ty[i] = sx, sy

    # ---- pass 2: thumbnails / zoom measurement at 320x180 for needed frames
    shots = []
    need = {}
    for si in range(len(bounds) - 1):
        a, b = bounds[si], bounds[si + 1]
        need[min(b - 1, a + int((b - a) * 0.45))] = ('mid', si)
    trans_rows = []
    for a, b in dissolves:
        trans_rows.append(('dissolve', a, b))
    for a, b in flash:
        trans_rows.append(('flash', a - 3, b + 3))
    for a, b in fades:
        trans_rows.append(('fade', a - 3, b + 3))
    trans_rows.sort(key=lambda r: r[1])
    rng = np.random.default_rng(7)
    sample_cuts = sorted(rng.choice(hard, size=min(24, len(hard)), replace=False).tolist()) if hard else []
    for c in sample_cuts:
        trans_rows.append(('cut', c - 3, c + 3))
    strip_idx = {}
    for r_i, (kind, a, b) in enumerate(trans_rows):
        for j, x in enumerate(np.linspace(max(0, a), min(n - 1, b), 8).round().astype(int)):
            strip_idx.setdefault(int(x), []).append((r_i, j))
    zoom_pairs = {}
    for si in range(len(bounds) - 1):
        a, b = bounds[si], bounds[si + 1]
        if (b - a) / fps >= 1.0:
            p, q = a + int((b - a) * 0.15), a + int((b - a) * 0.85)
            zoom_pairs[si] = (p, q)
    zoom_need = {x for pq in zoom_pairs.values() for x in pq}
    keep = {}
    for i, fr in enumerate(frames(vid, 320, 180)):
        if i in need or i in strip_idx or i in zoom_need:
            keep[i] = fr.copy()

    orb = cv2.ORB_create(600); bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    def scale_between(p, q):
        g1 = cv2.cvtColor(keep[p], cv2.COLOR_RGB2GRAY); g2 = cv2.cvtColor(keep[q], cv2.COLOR_RGB2GRAY)
        k1, d1 = orb.detectAndCompute(g1, None); k2, d2 = orb.detectAndCompute(g2, None)
        if d1 is None or d2 is None or len(k1) < 20 or len(k2) < 20:
            return None
        m = bf.match(d1, d2)
        if len(m) < 20:
            return None
        A = np.float32([k1[x.queryIdx].pt for x in m]); B = np.float32([k2[x.trainIdx].pt for x in m])
        M, inl = cv2.estimateAffinePartial2D(A, B, ransacReprojThreshold=2.0)
        if M is None or inl.sum() < 15:
            return None
        return float(math.hypot(M[0, 0], M[1, 0]))

    for si in range(len(bounds) - 1):
        a, b = bounds[si], bounds[si + 1]
        sc = None
        if si in zoom_pairs:
            p, q = zoom_pairs[si]
            s = scale_between(p, q)
            if s:
                sc = (s - 1) / ((q - p) / fps)
        jit = 0.0
        if b - a > 4:
            jx = np.diff(tx[a + 1:b]); jy = np.diff(ty[a + 1:b])
            jit = float(np.sqrt((jx ** 2 + jy ** 2).mean()))   # px at 160 wide: high-frequency positional jitter
        shots.append(dict(idx=si, start_s=round(a / fps, 3), end_s=round(b / fps, 3), dur_s=round((b - a) / fps, 3),
                          in_kind=kind_at.get(a, 'start' if a == 0 else 'cut'), luma=round(float(L[a:b].mean()), 1),
                          sat=round(float(S[a:b].mean()), 1), motion=round(float(d[a + 1:b].mean()) if b - a > 1 else 0, 2),
                          scale_per_s=None if sc is None else round(sc, 4), shake=round(jit, 2)))

    # ---- audio
    au = None
    try:
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', vid, '-vn', '-ac', '1', '-ar', '22050', '-f', 'f32le', '-'], capture_output=True).stdout
        y, sr = np.frombuffer(raw, np.float32).copy(), 22050   # librosa/soundfile cannot read mp4 containers
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units='time')
        oenv = librosa.onset.onset_strength(y=y, sr=sr)
        onsets = librosa.onset.onset_detect(onset_envelope=oenv, sr=sr, units='time', backtrack=False)
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        rt = librosa.times_like(rms, sr=sr, hop_length=512)
        au = dict(tempo=float(np.atleast_1d(tempo)[0]), beats=beats.tolist(), onsets=onsets.tolist(), rms_t=rt, rms=rms)
    except Exception as e:
        print('audio failed:', e, file=sys.stderr)

    cut_t = np.array([b / fps for b in hard])
    res = {}
    if au and len(cut_t):
        on = np.array(au['onsets']); be = np.array(au['beats'])
        def near(ts, ref, tol):
            if not len(ref):
                return 0.0
            return float(np.mean([np.min(np.abs(ref - t)) <= tol for t in ts]))
        tol1, tol2 = 1.0 / fps + 0.012, 2.0 / fps + 0.012
        base_on = min(1.0, len(on) / dur * 2 * tol1)      # chance of a random time being that close to an onset
        res = dict(cut_on_onset_1f=near(cut_t, on, tol1), cut_on_onset_2f=near(cut_t, on, tol2), chance_onset_1f=base_on,
                   cut_on_beat_2f=near(cut_t, be, tol2), chance_beat_2f=min(1.0, len(be) / dur * 2 * tol2), tempo=au['tempo'])
        # density vs loudness (10 s windows)
        edges = np.arange(0, dur + 10, 10)
        cpm = np.histogram(cut_t, bins=edges)[0] * 6.0
        en = np.array([au['rms'][(au['rms_t'] >= a) & (au['rms_t'] < a + 10)].mean() if ((au['rms_t'] >= a) & (au['rms_t'] < a + 10)).any() else 0
                       for a in edges[:-1]])
        res['cpm_10s'] = cpm.round(1).tolist()
        res['rms_10s'] = en.round(4).tolist()
        res['density_loudness_r'] = float(np.corrcoef(cpm, en)[0, 1]) if cpm.std() > 0 and en.std() > 0 else None

    # ---- overlays that persist through hard cuts (lyrics, logos, watermarks)
    persist_rows = np.zeros(SH)
    pc = 0
    for c in hard:
        if c < 1:
            continue
        same = (np.abs(Gf[c] - Gf[c - 1]) < 3) & (cv2.Laplacian(G[c], cv2.CV_32F) ** 2 > 400)
        if same.mean() > 0.002:
            pc += 1; persist_rows += same.mean(axis=1)
    overlay = dict(cuts_with_persistent_edges=pc / max(1, len(hard)),
                   band=('top' if persist_rows[:SH // 3].sum() > persist_rows[2 * SH // 3:].sum() else 'bottom') if pc else None)

    # ---- sheets
    def label(img, text):
        dr = ImageDraw.Draw(img); dr.rectangle((0, 0, img.width, 15), fill=(0, 0, 0)); dr.text((3, 1), text, fill=(255, 230, 0), font=FONT)
        return img
    cols = 8; per = 96
    mids = sorted(need.items())
    for page in range(0, len(mids), per):
        chunk = mids[page:page + per]
        sheet = Image.new('RGB', (cols * TW, math.ceil(len(chunk) / cols) * (TH + 16)), (12, 12, 12))
        for j, (fi, (_, si)) in enumerate(chunk):
            sh = shots[si]
            im = Image.fromarray(keep[fi]).resize((TW, TH))
            tile = Image.new('RGB', (TW, TH + 16)); tile.paste(im, (0, 16))
            k2 = {'cut': '', 'dissolve': ' DIS', 'fade': ' FADE', 'start': ''}.get(sh['in_kind'], ' ' + sh['in_kind'].upper())
            label(tile, f"#{si} {int(sh['start_s'] // 60)}:{sh['start_s'] % 60:04.1f} {sh['dur_s']:.1f}s{k2}")
            sheet.paste(tile, ((j % cols) * TW, (j // cols) * (TH + 16)))
        sheet.save(f'{out}/shotboard-{page // per + 1}.jpg', quality=82)
    rows_per = 20
    for page in range(0, len(trans_rows), rows_per):
        chunk = trans_rows[page:page + rows_per]
        sheet = Image.new('RGB', (8 * 200, len(chunk) * (113 + 16)), (12, 12, 12))
        for r_i, (kind, a, b) in enumerate(chunk):
            for j, x in enumerate(np.linspace(max(0, a), min(n - 1, b), 8).round().astype(int)):
                im = Image.fromarray(keep[int(x)]).resize((200, 113))
                tile = Image.new('RGB', (200, 129)); tile.paste(im, (0, 16))
                label(tile, f"{kind} {x / fps:.2f}s" if j == 0 else f"{x / fps:.2f}")
                sheet.paste(tile, (j * 200, r_i * 129))
        sheet.save(f'{out}/transitions-{page // rows_per + 1}.jpg', quality=82)
    # curve
    Wc, Hc = 1600, 360
    cv = Image.new('RGB', (Wc, Hc), (16, 16, 20)); dr = ImageDraw.Draw(cv)
    X = lambda t: int(t / dur * (Wc - 20)) + 10
    if res.get('cpm_10s'):
        m = max(res['cpm_10s']) or 1
        for i, v in enumerate(res['cpm_10s']):
            dr.rectangle((X(i * 10), Hc - 30 - int(v / m * 140), X(i * 10 + 10) - 2, Hc - 30), fill=(70, 110, 200))
        dr.text((10, Hc - 25), f'cuts/min per 10 s (max {m:.0f})', fill=(120, 160, 255), font=FONT)
    if au:
        rr = au['rms'] / (au['rms'].max() or 1)
        pts = [(X(t), 170 - int(v * 130)) for t, v in zip(au['rms_t'][::8], rr[::8])]
        dr.line(pts, fill=(230, 120, 60), width=2); dr.text((10, 20), 'music RMS', fill=(230, 120, 60), font=FONT)
        for t in au['beats']:
            dr.point((X(t), 178), fill=(200, 200, 200))
    lp = [(X(i / fps), 330 - int(L[i] / 255 * 120)) for i in range(0, n, max(1, int(fps / 4)))]
    dr.line(lp, fill=(220, 220, 120), width=1)
    for c in hard:
        dr.line((X(c / fps), 182, X(c / fps), 192), fill=(255, 255, 255))
    for a, b in dissolves:
        dr.line((X(a / fps), 195, X(b / fps), 195), fill=(80, 220, 120), width=4)
    for a, b in flash:
        dr.line((X(a / fps), 199, X(b / fps), 199), fill=(255, 255, 255), width=4)
    for mm in range(0, int(dur) + 1, 30):
        dr.text((X(mm), Hc - 14), f'{mm // 60}:{mm % 60:02d}', fill=(150, 150, 150), font=FONT)
    cv.save(f'{out}/curve.png')

    with open(f'{out}/shots.csv', 'w') as f:
        keys = list(shots[0].keys())
        f.write(','.join(keys) + '\n')
        for s in shots:
            f.write(','.join('' if s[k] is None else str(s[k]) for k in keys) + '\n')
    durs = np.array([s['dur_s'] for s in shots])
    scales = [s['scale_per_s'] for s in shots if s['scale_per_s'] is not None]
    metrics = dict(
        video=os.path.basename(vid), fps=round(fps, 3), duration_s=round(dur, 2), shots=len(shots),
        cuts_per_min=round(len(shots) / dur * 60, 1), hard_cuts=len(hard), dissolves=len(dissolves), flashes=len(flash), fades_to_black=len(fades),
        hard_cut_share=round(len(hard) / max(1, len(hard) + len(dissolves) + len(flash) + len(fades)), 3),
        shot_len=dict(median=round(float(np.median(durs)), 2), p10=round(float(np.percentile(durs, 10)), 2), p90=round(float(np.percentile(durs, 90)), 2),
                      max=round(float(durs.max()), 2), under_0_5s=int((durs < 0.5).sum()), over_3s=int((durs > 3).sum())),
        zoom_shots=dict(measured=len(scales), push_in_gt_2pct_s=int(sum(1 for s in scales if s > 0.02)), pull_out=int(sum(1 for s in scales if s < -0.02))),
        shaky_shots=int(sum(1 for s in shots if s['shake'] > 1.2)),
        music=res, overlay=overlay,
        luma_mean=round(float(L.mean()), 1), luma_p95=round(float(np.percentile(L, 95)), 1))
    json.dump(metrics, open(f'{out}/metrics.json', 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({k: metrics[k] for k in ('video', 'shots', 'cuts_per_min', 'hard_cut_share', 'dissolves', 'flashes', 'shot_len', 'zoom_shots', 'shaky_shots')},
                     ensure_ascii=False))
    if res:
        print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.items() if k not in ('cpm_10s', 'rms_10s')}))


if __name__ == '__main__':
    main()
