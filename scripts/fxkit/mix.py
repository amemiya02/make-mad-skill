"""Audio mix: original song (never ducked over singing) + dialogue excerpts + synthesized SFX.
All times are SONG seconds. Output: float WAV stems + mix, 48 kHz stereo.
"""
import numpy as np, subprocess, glob, sys, os, soundfile as sf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scipy.signal import butter, sosfilt

SR = 48000

import os
from fx import epfile, set_sources  # shared resolver

def load(path, ss=None, t=None):
    cmd = ['ffmpeg', '-v', 'error']
    if ss is not None:
        cmd += ['-ss', f'{ss:.4f}']
    if t is not None:
        cmd += ['-t', f'{t:.4f}']
    cmd += ['-i', path, '-map', '0:a:0', '-ac', '2', '-ar', str(SR), '-f', 'f32le', '-']
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32).reshape(-1, 2).copy()

def db(x):
    return 10 ** (np.asarray(x) / 20)

def env_trap(n, t0, t1, ramp, depth_db):
    t = np.arange(n) / SR
    w = np.minimum(np.clip((t - (t0 - ramp)) / ramp, 0, 1), np.clip(((t1 + ramp) - t) / ramp, 0, 1))
    w = 0.5 - 0.5 * np.cos(np.pi * w)
    return db(depth_db * w).astype(np.float32)

def bp(x, lo, hi, order=2):
    sos = butter(order, [lo, hi], btype='band', fs=SR, output='sos')
    return sosfilt(sos, x, axis=0).astype(np.float32)

def hp(x, fc, order=2):
    return sosfilt(butter(order, fc, btype='high', fs=SR, output='sos'), x, axis=0).astype(np.float32)

def lp(x, fc, order=2):
    return sosfilt(butter(order, fc, btype='low', fs=SR, output='sos'), x, axis=0).astype(np.float32)

def norm(y):
    return (y / (np.abs(y).max() + 1e-9)).astype(np.float32)

def st(y, spread=0):
    return np.stack([y, np.roll(y, spread)], 1)

# ---------------------------------------------------------------- SFX synths
def sfx_whoosh(dur=0.45, seed=1, lo=300, hi=3500):
    n = int(dur * SR); t = np.arange(n) / SR
    w = np.random.default_rng(seed).standard_normal(n).astype(np.float32)
    a = bp(w, lo, hi); b = bp(w, lo * 0.4, hi * 0.35)
    mixk = np.clip(t / dur, 0, 1)  # sweep from low band to high band
    y = (b * (1 - mixk) + a * mixk) * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    return st(norm(y), 120)

def sfx_impact(dur=1.0, f0=58, seed=2):
    n = int(dur * SR); t = np.arange(n) / SR
    body = np.sin(2 * np.pi * (f0 * t + 45 * (1 - np.exp(-t * 16)) / 16)) * np.exp(-t * 5.5)
    click = lp(np.random.default_rng(seed).standard_normal(n), 3000) * np.exp(-t * 55) * 0.6
    return st(norm(body + click))

def sfx_riser(dur=2.2, seed=3):
    n = int(dur * SR); t = np.arange(n) / SR
    noise = bp(np.random.default_rng(seed).standard_normal(n), 400, 5000)
    tone = np.sin(2 * np.pi * (180 * t + 260 * t * t / dur)) * 0.25
    y = (noise * 0.8 + tone) * (t / dur) ** 2.4
    return st(norm(y), 200)

def sfx_reverse(dur=1.8, seed=7):
    """reversed cymbal-like swell"""
    n = int(dur * SR); t = np.arange(n) / SR
    y = hp(np.random.default_rng(seed).standard_normal(n), 2500) * np.exp(-t * 2.2)
    return st(norm(y[::-1]), 300)

def sfx_shimmer(dur=1.8, seed=4):
    n = int(dur * SR); t = np.arange(n) / SR
    rng = np.random.default_rng(seed); y = np.zeros(n, np.float32)
    for f in rng.uniform(1600, 5200, 16):
        y += np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) * np.exp(-t * rng.uniform(2.0, 4.5))
    return st(norm(y * np.clip(t / 0.015, 0, 1)), 240)

def sfx_puff(dur=0.45, seed=5):
    n = int(dur * SR); t = np.arange(n) / SR
    y = lp(np.random.default_rng(seed).standard_normal(n), 650) * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.5
    return st(norm(y))

def sfx_glitch(dur=0.22, seed=6):
    n = int(dur * SR); rng = np.random.default_rng(seed)
    y = np.repeat(rng.standard_normal(n // 60 + 1), 60)[:n] * (np.sin(2 * np.pi * 37 * np.arange(n) / SR) > 0)
    y = bp(y.astype(np.float32), 400, 6000)
    return np.stack([norm(y), -norm(y)], 1)

def sfx_thunder(dur=1.4, seed=8):
    n = int(dur * SR); t = np.arange(n) / SR
    crack = hp(np.random.default_rng(seed).standard_normal(n), 1500) * np.exp(-t * 30)
    rumble = lp(np.random.default_rng(seed + 1).standard_normal(n), 180) * np.exp(-t * 2.8) * 2.0
    return st(norm(crack + rumble), 90)

SYNTH = {'whoosh': sfx_whoosh, 'impact': sfx_impact, 'riser': sfx_riser, 'reverse': sfx_reverse, 'shimmer': sfx_shimmer,
         'puff': sfx_puff, 'glitch': sfx_glitch, 'thunder': sfx_thunder}

def place(buf, clip, t, gain_db):
    i = int(round(t * SR))
    if i < 0:
        clip, i = clip[-i:], 0
    j = min(len(buf), i + len(clip))
    if j > i:
        buf[i:j] += clip[:j - i] * db(gain_db)

def build(music_path, total_s, dialogue, ducks, sfx, out_prefix, end_fade=None, dialogue_loader=None, music_offset=0.0, bed=None):
    """dialogue_loader(ep, a, b) -> float32 (n,2) at SR: e.g. separated, BGM-free voice. Never mix raw episode audio under
    a MAD unless the line has no music in it. music_offset: seconds of silence before the song. bed: optional (n,2) ambience."""
    n = int(round(total_s * SR))
    mus = load(music_path) if music_path else np.zeros((n, 2), np.float32)
    if music_offset:
        mus = np.vstack([np.zeros((int(round(music_offset * SR)), 2), np.float32), mus])
    mus = mus[:n]
    if len(mus) < n:
        mus = np.vstack([mus, np.zeros((n - len(mus), 2), np.float32)])
    g = np.ones(n, np.float32)
    for (a, b, d, r) in ducks:
        g *= env_trap(n, a, b, r, d)
    if end_fade:
        a, b = end_fade
        t = np.arange(n) / SR
        g *= np.clip((b - t) / (b - a), 0, 1) ** 1.5
    mus = mus * g[:, None]
    dlg = np.zeros((n, 2), np.float32)
    for (ep, a, b, t, gd, fd) in dialogue:
        x = dialogue_loader(ep, a, b) if dialogue_loader else load(epfile(ep), a, b - a)
        m = len(x); k = max(1, int(fd * SR))
        w = np.ones(m, np.float32); w[:k] = np.linspace(0, 1, k); w[-k:] = np.minimum(w[-k:], np.linspace(1, 0, k))
        place(dlg, hp(x * w[:, None], 110), t, gd)
    fxb = np.zeros((n, 2), np.float32)
    for (name, t, gd, kw) in sfx:
        place(fxb, SYNTH[name](**kw), t, gd)
    if bed is not None:
        m = min(n, len(bed)); fxb[:m] += bed[:m]
    mix = mus + dlg + fxb
    for nm, arr in [('music', mus), ('dialogue', dlg), ('sfx', fxb), ('mix', mix)]:
        sf.write(f'{out_prefix}-{nm}.wav', arr, SR, subtype='FLOAT')
    return f'{out_prefix}-mix.wav'
