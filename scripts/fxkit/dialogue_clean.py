#!/usr/bin/env python3
"""dialogue_clean — isolate a character line from an anime episode mix (BGM/SFX/ambience -> near-silence).

Pipeline (UVR5 + RX "Dialogue Isolate" equivalent, all local, Apple Silicon MPS/CPU):
  1. ffmpeg: cut [a-pad, b+pad] of the Japanese track (separation models need musical context)
  2. stage 1  vocal model     (audio-separator / UVR backend; default Mel-Band RoFormer vocals)
  3. stage 2  denoise         ('hybrid' default = DFN only in the weak frames between words + plain vocal stem under speech; 'dfn' = DeepFilterNet3 everywhere: removes residual stationary BGM/drone the vocal stem keeps; 'roformer' = Mel-RoFormer Denoise aufr33 (near no-op on music residue), 'none')
  4. stage 3  speech gate     Silero-VAD + energy-tail extension, pre-roll/hold, raised-cosine ramps
  5. trim to [a,b] (3 ms declick), write 48 kHz stereo float WAV
Results are cached by hash(source, a, b, pad, models, gate params, version).

Run with the dedicated venv (audio-separator needs numpy>=2, DeepFilterNet needs numpy<2, so DFN lives
in its own venv and is called as a subprocess):
  AUDIO_PY=/path/.venv-audio/bin/python
  $AUDIO_PY dialogue_clean.py 14 1335.51 1338.95 out.wav [--pad 6] [--model ...] [--denoise roformer|dfn|none]
  $AUDIO_PY dialogue_clean.py --list lines.tsv          # rows: ep  a  b  out_wav
Importable:  from dialogue_clean import clean; clean('14', 1335.51, 1338.95, 'out.wav')
Any venv:    from dialogue_clean import load_clean; x = load_clean('14', 1335.51, 1338.95)   # (n,2) f32 @48k
             (cache miss -> runs this file in the audio venv via subprocess; DIALOGUE_AUDIO_PYTHON overrides)

Configuration (nothing project-specific is hard-coded):
  set_sources({'14': '/path/ep14.mkv', ...})   explicit episode-key -> media path
  set_resolver(fn)                               fn(ep:str) -> media path (any naming scheme)
  DIALOGUE_EPISODE_GLOB   glob template with {root} and {ep} (zero-padded), e.g. '{root}/downloads/*/*- {ep} [[]*.mkv'
  MAD_ROOT                project root used for {root} and the default cache (default: current directory)
  DIALOGUE_CACHE_DIR      cache dir (default {root}/analysis/dialogue-iso/cache)
  AUDIO_SEPARATOR_MODEL_DIR  checkpoints (default ~/.cache/audio-separator-models; auto-downloaded)
  DIALOGUE_AUDIO_PYTHON   python of the venv with audio-separator + silero-vad (default: this interpreter)
  DIALOGUE_DFN_PYTHON     python of a venv with `deepfilternet` (only for --denoise dfn)
CLI --src KEY=PATH is repeatable. Audio track: DIALOGUE_AUDIO_MAP (default '0:a:0', the Japanese track).
"""
from __future__ import annotations

import argparse, glob, hashlib, json, logging, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

VERSION = 6
SR = 48000           # delivery rate
MSR = 44100          # UVR/RoFormer models are trained at 44.1 kHz
DEFAULT_MODEL = 'mel_band_roformer_vocals_becruily.ckpt'
DEFAULT_DENOISE_MODEL = 'denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt'
GATE_DEFAULTS = dict(
    vad_threshold=0.35,   # silero speech prob
    tail_db=30.0,         # extend segment edges while frame level > (speech p95 - tail_db)
    tail_max=0.40,        # ...but at most this many seconds per edge
    preroll=0.04,         # open this early before detected onset (consonant attacks)
    hold=0.12,            # keep open after detected offset (word tails / reverb)
    merge=0.25,           # bridge gaps shorter than this (no pumping between words)
    attack=0.025,         # raised-cosine ramp lengths (20-40 ms)
    release=0.040,
    floor_db=-80.0,       # gain in non-speech (near-silence)
)

ROOT = Path(os.environ.get('MAD_ROOT', os.getcwd()))
_RESOLVER = None
_SOURCES: dict[str, str] = {}
_SEPARATORS: dict[str, object] = {}
log = logging.getLogger('dialogue_clean')


# ---------------------------------------------------------------- paths
def set_sources(mapping: dict) -> None:
    """Explicit episode-key -> media path map (overrides glob lookup)."""
    _SOURCES.update({str(k): str(v) for k, v in mapping.items()})


def set_resolver(fn) -> None:
    """fn(ep) -> media path; used when the episode is not in set_sources()."""
    global _RESOLVER
    _RESOLVER = fn


def episode_path(ep) -> str:
    ep = str(ep)
    if ep in _SOURCES:
        return _SOURCES[ep]
    if os.path.isfile(ep):
        return ep
    if _RESOLVER is not None:
        return str(_RESOLVER(ep))
    tpl = os.environ.get('DIALOGUE_EPISODE_GLOB', '{root}/**/*{ep}*.mkv')
    hits = sorted(glob.glob(tpl.format(root=ROOT, ep=ep.zfill(2)), recursive=True))
    if not hits:
        raise FileNotFoundError(f'episode {ep!r}: no match for {tpl.format(root=ROOT, ep=ep.zfill(2))}')
    return hits[0]


def cache_dir() -> Path:
    d = Path(os.environ.get('DIALOGUE_CACHE_DIR', ROOT / 'analysis' / 'dialogue-iso' / 'cache'))
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_dir() -> str:
    return os.environ.get('AUDIO_SEPARATOR_MODEL_DIR', os.path.expanduser('~/.cache/audio-separator-models'))


# ---------------------------------------------------------------- audio io
def extract(src: str, t0: float, dur: float, out: str, sr: int) -> None:
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', f'{t0:.4f}', '-i', src, '-t', f'{dur:.4f}',
           '-map', os.environ.get('DIALOGUE_AUDIO_MAP', '0:a:0'), '-ac', '2', '-ar', str(sr), '-c:a', 'pcm_f32le', out]
    subprocess.run(cmd, check=True)


def read(path: str, sr: int = SR) -> np.ndarray:
    x, s = sf.read(path, always_2d=True, dtype='float32')
    if s != sr:
        x = soxr.resample(x, s, sr, quality='VHQ')
    return x.T.copy()  # (ch, n)


def fit(x: np.ndarray, n: int) -> np.ndarray:
    if x.shape[1] >= n:
        return x[:, :n]
    return np.pad(x, ((0, 0), (0, n - x.shape[1])))


# ---------------------------------------------------------------- separation
def _separator(model: str, out_dir: str, overlap: int):
    import torch
    torch.set_num_threads(max(1, min(4, (os.cpu_count() or 4) // 2)))   # shared machine
    key = f'{model}|{overlap}'
    sep = _SEPARATORS.get(key)
    if sep is None:
        from audio_separator.separator import Separator
        sep = Separator(log_level=logging.WARNING, model_file_dir=model_dir(), output_dir=out_dir,
                        output_format='WAV', use_soundfile=True, sample_rate=MSR,
                        normalization_threshold=1.0,   # never rescale stems (keeps levels comparable)
                        mdxc_params={'segment_size': 256, 'override_model_segment_size': False,
                                     'batch_size': 1, 'overlap': overlap, 'pitch_shift': 0})
        sep.load_model(model)
        _SEPARATORS[key] = sep
    sep.output_dir = out_dir
    if getattr(sep, 'model_instance', None) is not None:
        sep.model_instance.output_dir = out_dir
    return sep


def separate(inp: str, model: str, want: tuple[str, ...], work: str, overlap: int = 2) -> str:
    """Run one audio-separator model, return the path of the stem whose name matches `want`."""
    out_dir = tempfile.mkdtemp(dir=work)
    sep = _separator(model, out_dir, overlap)
    files = sep.separate(inp)
    files = [f if os.path.isabs(f) else os.path.join(out_dir, f) for f in files]
    for w in want:
        for f in files:
            name = os.path.basename(f).lower()
            if f'({w})' in name:
                return f
    raise RuntimeError(f'{model}: none of {want} in outputs {files}')


def dfn(inp: str, out: str, atten_lim_db: float | None = None) -> None:
    py = os.environ.get('DIALOGUE_DFN_PYTHON', sys.executable)
    code = (
        'import sys,torch;torch.set_num_threads(4)\n'
        'from df.enhance import enhance,init_df,load_audio,save_audio\n'
        'm,s,_=init_df(log_level="ERROR")\n'
        'a,_=load_audio(sys.argv[1],sr=s.sr())\n'
        'lim=None if sys.argv[3]=="none" else float(sys.argv[3])\n'
        'e=enhance(m,s,a,atten_lim_db=lim)\n'
        'import soundfile as sf;sf.write(sys.argv[2],e.numpy().T,s.sr(),subtype="FLOAT")\n')
    subprocess.run([py, '-c', code, inp, out, 'none' if atten_lim_db is None else str(atten_lim_db)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- hybrid
def hybrid_mix(voc: np.ndarray, den: np.ndarray, sr: int, margin_db: float = 15.0, max_loss_db: float = 1.5) -> np.ndarray:
    """Auto-select: full DFN if it costs <= max_loss_db of speech-band level, else use DeepFilterNet output only where the vocal stem is weak (between words / tails, level < speech p95 - margin);
    keep the un-denoised vocal stem where the voice is strong. DFN removes residual BGM drone in the gaps (-50 -> -90 dB)
    but can eat 7-18 dB of shouted / non-lexical voice, so it must not touch the speech itself."""
    from scipy.ndimage import uniform_filter1d
    lev, hop = frame_levels(voc, sr)
    act = lev[lev > lev.max() - 50]
    p95 = np.percentile(act, 95)
    # auto: if DFN keeps the strong (speech) frames within `max_loss_db` of the vocal stem, use it everywhere
    from scipy.signal import butter, sosfiltfilt
    sos = butter(4, [250, 4000], btype='band', fs=sr, output='sos')
    strong = np.repeat(lev > p95 - 15, int(round(hop * sr)))[:voc.shape[1]]
    strong = np.pad(strong, (0, voc.shape[1] - len(strong)))
    if strong.sum() > 0.05 * sr:
        ev = (sosfiltfilt(sos, voc.mean(0))[strong] ** 2).mean(); ed = (sosfiltfilt(sos, den.mean(0))[strong] ** 2).mean()
        loss = 10 * np.log10(ev / (ed + 1e-20) + 1e-20)
        log.info('hybrid: DFN speech-band loss %.1f dB', loss)
        if loss <= max_loss_db:
            return den
    thr = p95 - margin_db
    w = (lev < thr).astype(np.float32)
    w = uniform_filter1d(w, size=max(1, int(0.03 / hop)), mode='nearest')      # ~30 ms crossfade
    wn = np.interp(np.arange(voc.shape[1]) / sr, np.arange(len(w)) * hop, w).astype(np.float32)
    return voc * (1 - wn) + den * wn


# ---------------------------------------------------------------- gate
_VAD = None


def speech_segments(x: np.ndarray, sr: int, thr: float) -> list[tuple[float, float]]:
    global _VAD
    import torch
    from silero_vad import load_silero_vad, get_speech_timestamps
    if _VAD is None:
        _VAD = load_silero_vad()
    y = soxr.resample(x.mean(0), sr, 16000).astype(np.float32)
    ts = get_speech_timestamps(torch.from_numpy(y), _VAD, sampling_rate=16000, threshold=thr,
                               min_silence_duration_ms=100, min_speech_duration_ms=120,
                               speech_pad_ms=0, return_seconds=True)
    return [(t['start'], t['end']) for t in ts]


def frame_levels(x: np.ndarray, sr: int, hop: float = 0.005, win: float = 0.02):
    from scipy.signal import butter, sosfiltfilt
    sos = butter(4, [120, 7500], btype='band', fs=sr, output='sos')
    m = sosfiltfilt(sos, x.mean(0))
    h, w = int(hop * sr), int(win * sr)
    p = np.pad(m ** 2, (w // 2, w // 2))
    c = np.cumsum(np.concatenate([[0.0], p]))
    idx = np.arange(0, len(m), h)
    e = (c[idx + w] - c[idx]) / w
    return 10 * np.log10(e + 1e-20), hop


def gate(x: np.ndarray, sr: int, **kw) -> tuple[np.ndarray, list, np.ndarray]:
    """Return gated audio, final open segments (s) and the gain curve."""
    g = {**GATE_DEFAULTS, **kw}
    n = x.shape[1]
    segs = speech_segments(x, sr, g['vad_threshold'])
    lev, hop = frame_levels(x, sr)
    if not segs:
        log.warning('gate: no speech detected; output is floor-level')
        gain = np.full(n, 10 ** (g['floor_db'] / 20), np.float32)
        return x * gain, [], gain
    sp = np.concatenate([lev[int(s / hop):max(int(s / hop) + 1, int(e / hop))] for s, e in segs])
    thr = np.percentile(sp, 95) - g['tail_db']
    nf = len(lev); mx = int(g['tail_max'] / hop)
    out = []
    for s, e in segs:
        i = int(s / hop); j = min(nf - 1, int(e / hop))
        k = 0
        while i > 0 and k < mx and lev[i - 1] > thr:
            i -= 1; k += 1
        k = 0
        while j < nf - 1 and k < mx and lev[j + 1] > thr:
            j += 1; k += 1
        out.append([max(0.0, i * hop - g['preroll']), min(n / sr, j * hop + g['hold'])])
    out.sort()
    merged = [out[0]]
    for s, e in out[1:]:
        if s - merged[-1][1] < g['merge']:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    gain = np.zeros(n, np.float32)
    A, R = int(g['attack'] * sr), int(g['release'] * sr)
    ra = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, A, endpoint=False)) if A else np.zeros(0)
    rr = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, R, endpoint=False)) if R else np.zeros(0)
    for s, e in merged:
        i, j = int(s * sr), int(e * sr)
        gain[i:j] = 1.0
        a0 = max(0, i - A); gain[a0:i] = np.maximum(gain[a0:i], ra[A - (i - a0):])
        r1 = min(n, j + R); gain[j:r1] = np.maximum(gain[j:r1], rr[:r1 - j])
    fl = 10 ** (g['floor_db'] / 20)
    gain = fl + (1 - fl) * gain
    return x * gain, [tuple(m) for m in merged], gain


# ---------------------------------------------------------------- main entry

def _spec(src, a, b, pad=6.0, model=DEFAULT_MODEL, denoise='hybrid', denoise_model=DEFAULT_DENOISE_MODEL,
          use_gate=True, overlap=2, gate_kw=None):
    gate_kw = gate_kw or {}
    spec = dict(v=VERSION, src=os.path.basename(src), a=round(a, 4), b=round(b, 4), pad=pad, model=model,
                denoise=denoise, dmodel=denoise_model if denoise == 'roformer' else None, gate=use_gate,
                gk={**GATE_DEFAULTS, **gate_kw} if use_gate else None, ov=overlap)
    return spec, hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def audio_python() -> str:
    """Interpreter of the venv that has audio-separator + silero-vad (default: this interpreter)."""
    py = os.environ.get('DIALOGUE_AUDIO_PYTHON') or sys.executable
    if not os.path.isfile(py):
        raise FileNotFoundError(f'audio venv python not found: {py} (set DIALOGUE_AUDIO_PYTHON)')
    return py


def load_clean(ep, a: float, b: float, **kw) -> np.ndarray:
    """Cleaned dialogue for episode seconds [a,b] -> float32 array (n, 2) @ 48 kHz, n == round((b-a)*48000).

    Works from any venv with numpy+soundfile: on a cache miss the heavy pipeline runs in the audio venv
    via subprocess (cache: DIALOGUE_CACHE_DIR, keyed by source/a/b/models/params/VERSION). Raises on any failure.
    """
    ep = str(ep).zfill(2) if str(ep).isdigit() else str(ep)
    src = episode_path(ep)
    _, h = _spec(src, a, b)
    cached = cache_dir() / f'{h}.wav'
    if not (cached.exists() and (cache_dir() / f'{h}.json').exists()):
        out = cache_dir() / f'_req_{h}_{os.getpid()}.wav'
        cmd = [audio_python(), str(Path(__file__).resolve()), src, repr(float(a)), repr(float(b)), str(out)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f'dialogue_clean failed for E{ep} {a}-{b} (rc={r.returncode}):\n{r.stdout[-1500:]}\n{r.stderr[-3000:]}')
        finally:
            if out.exists():
                out.unlink()
        if not cached.exists():
            raise RuntimeError(f'dialogue_clean produced no cache file {cached}')
    x, sr = sf.read(cached, always_2d=True, dtype='float32')
    if sr != SR:
        raise RuntimeError(f'cache {cached}: sample rate {sr} != {SR}')
    n = int(round((b - a) * SR))
    if x.shape[0] >= n:
        x = x[:n]
    else:
        x = np.pad(x, ((0, n - x.shape[0]), (0, 0)))
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    if not np.isfinite(x).all():
        raise RuntimeError(f'cache {cached}: non-finite samples')
    return np.ascontiguousarray(x, dtype=np.float32)

def clean(ep, a: float, b: float, out_wav: str, pad: float = 6.0, model: str = DEFAULT_MODEL,
          denoise: str = 'hybrid', denoise_model: str = DEFAULT_DENOISE_MODEL, use_gate: bool = True,
          overlap: int = 2, keep_stages: bool = False, force: bool = False, quiet: bool = False,
          **gate_kw) -> dict:
    """Isolate dialogue in [a,b] (episode seconds) -> 48 kHz stereo float WAV at out_wav. Returns info dict."""
    T = time.time()
    src = episode_path(ep)
    t0 = max(0.0, a - pad)
    dur = (b + pad) - t0
    head = a - t0
    spec, h = _spec(src, a, b, pad, model, denoise, denoise_model, use_gate, overlap, gate_kw)
    cdir = cache_dir()
    cached = cdir / f'{h}.wav'
    meta_p = cdir / f'{h}.json'
    say = (lambda *m: None) if quiet else (lambda *m: print('[dialogue_clean]', *m, flush=True))
    if cached.exists() and meta_p.exists() and not force:
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, out_wav)
        info = json.loads(meta_p.read_text()); info['cache'] = 'hit'
        say(f'cache hit {h} -> {out_wav} ({time.time() - T:.2f}s)')
        return info

    timing = {}
    work = tempfile.mkdtemp(prefix=f'dc_{h}_', dir=cdir)
    try:
        t = time.time()
        ctx = os.path.join(work, 'ctx.wav')
        extract(src, t0, dur, ctx, MSR)
        n_ctx = int(round(dur * SR))
        timing['extract'] = time.time() - t

        t = time.time()
        voc = separate(ctx, model, ('vocals', 'vocal'), work, overlap)
        timing['vocal_model'] = time.time() - t

        t = time.time()
        if denoise == 'roformer':
            stage = separate(voc, denoise_model, ('dry', 'no noise', 'vocals'), work, overlap)
        elif denoise in ('dfn', 'hybrid'):
            stage = os.path.join(work, 'dfn.wav')
            dfn(voc, stage)
        elif denoise == 'none':
            stage = voc
        else:
            raise ValueError(f'denoise={denoise!r}')
        timing['denoise'] = time.time() - t

        t = time.time()
        y = fit(read(stage, SR), n_ctx)
        if denoise == 'hybrid':
            y = hybrid_mix(fit(read(voc, SR), n_ctx), y, SR, gate_kw.get('hybrid_db', 15.0))
            gate_kw = {k: v for k, v in gate_kw.items() if k != 'hybrid_db'}
        segs = []
        if use_gate:
            y, segs, _ = gate(y, SR, **gate_kw)
        timing['gate'] = time.time() - t

        i0 = int(round(head * SR)); i1 = i0 + int(round((b - a) * SR))
        y = y[:, i0:i1].copy()
        f = min(int(0.003 * SR), y.shape[1] // 2)
        if f:
            ramp = np.linspace(0, 1, f, dtype=np.float32)
            y[:, :f] *= ramp; y[:, -f:] *= ramp[::-1]
        sf.write(cached, y.T, SR, subtype='FLOAT')
        if keep_stages:
            sd = cdir / f'{h}_stages'; sd.mkdir(exist_ok=True)
            shutil.copyfile(ctx, sd / 'ctx_mix.wav'); shutil.copyfile(voc, sd / 'stage1_vocals.wav')
            if stage != voc:
                shutil.copyfile(stage, sd / 'stage2_denoised.wav')
        timing['total'] = time.time() - T
        info = dict(spec=spec, hash=h, out=str(out_wav), ctx_start=t0, head=head,
                    gate_segments_abs=[(round(float(t0 + s), 3), round(float(t0 + e), 3)) for s, e in segs],
                    timing={k: round(v, 2) for k, v in timing.items()},
                    peak_dbfs=round(float(20 * np.log10(np.abs(y).max() + 1e-12)), 1))
        meta_p.write_text(json.dumps(info, indent=1))
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, out_wav)
        say(f'E{ep} {a:.2f}-{b:.2f} -> {out_wav}  ' +
            '  '.join(f'{k}={v:.1f}s' for k, v in timing.items()))
        info['cache'] = 'miss'
        return info
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ep', nargs='?'); ap.add_argument('a', nargs='?', type=float)
    ap.add_argument('b', nargs='?', type=float); ap.add_argument('out', nargs='?')
    ap.add_argument('--list', help='TSV/space file: ep a b out_wav per line')
    ap.add_argument('--src', action='append', default=[], help='KEY=PATH episode override (repeatable)')
    ap.add_argument('--pad', type=float, default=6.0)
    ap.add_argument('--model', default=DEFAULT_MODEL)
    ap.add_argument('--denoise', default='hybrid', choices=['hybrid', 'roformer', 'dfn', 'none'])
    ap.add_argument('--denoise-model', default=DEFAULT_DENOISE_MODEL)
    ap.add_argument('--no-gate', action='store_true')
    ap.add_argument('--floor-db', type=float, default=GATE_DEFAULTS['floor_db'])
    ap.add_argument('--hold', type=float, default=GATE_DEFAULTS['hold'])
    ap.add_argument('--overlap', type=int, default=2, help='RoFormer overlap windows (2 fast, 4-8 slower/smoother)')
    ap.add_argument('--keep-stages', action='store_true')
    ap.add_argument('--force', action='store_true')
    o = ap.parse_args(argv)
    for kv in o.src:
        k, v = kv.split('=', 1); set_sources({k: v})
    jobs = []
    if o.list:
        for line in Path(o.list).read_text().splitlines():
            p = line.split('#')[0].split()
            if len(p) >= 4:
                jobs.append((p[0], float(p[1]), float(p[2]), p[3]))
    if o.ep:
        if o.a is None or o.b is None or not o.out:
            ap.error('need: ep a b out')
        jobs.append((o.ep, o.a, o.b, o.out))
    if not jobs:
        ap.error('nothing to do')
    for ep, a, b, out in jobs:
        clean(ep, a, b, out, pad=o.pad, model=o.model, denoise=o.denoise, denoise_model=o.denoise_model,
              use_gate=not o.no_gate, overlap=o.overlap, keep_stages=o.keep_stages, force=o.force,
              floor_db=o.floor_db, hold=o.hold)


if __name__ == '__main__':
    main()
