#!/usr/bin/env python3
"""Forced-align user-supplied lyrics to a separated vocal stem.

The lyric text always comes from the user (a licensed source); this tool never
ships or generates lyric text itself.

Input text format (UTF-8):
    # comment lines and blank lines are ignored
    日本語の行<TAB>中文翻译          (ja + optional zh on one line)
    日本語の行                         (ja only)
    zh: 中文翻译                       (zh for the preceding ja line)
Repeated lines (choruses) are kept: every occurrence is its own row, in order.

Modes:
    full    (default) align the whole text in one pass with stable-ts
            model.align(); falls back to transcription + difflib if that fails.
    search  locate each line independently anywhere in the song (for partial
            text / excerpts): transcribe once, fuzzy-match each line's reading,
            then refine with a per-line model.align() on a local window.

Post-processing: snap line start/end to phrase-slot boundaries (slots CSV with
start,end columns) when within --snap seconds, enforce monotonic,
non-overlapping times, minimum display 1.0 s, and close gaps < 0.25 s.

CLI:
    python lyric_align.py --lyrics lyrics.txt --vocals vocals.wav \
        --slots lyrics-timed.csv --out lyrics-aligned.csv [--mode search]
Python:
    from lyric_align import align
    rows = align("lyrics.txt", "vocals.wav", "lyrics-timed.csv")
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
import unicodedata
from pathlib import Path

SR = 16000
LOW_SCORE = 0.5
MIN_DISPLAY = 1.0
CLOSE_GAP = 0.25
EPS = 0.02

# ----------------------------------------------------------------- text utils

def parse_lyrics(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("zh:") or line.startswith("zh："):
            if not rows:
                raise ValueError(f"zh line before any ja line: {raw!r}")
            rows[-1]["zh"] = line[3:].strip()
            continue
        ja, _, zh = line.partition("\t")
        rows.append({"ja": ja.strip(), "zh": zh.strip()})
    if not rows:
        raise ValueError(f"no lyric lines in {path}")
    return rows


_kks = None


def reading(text: str) -> str:
    """Normalised hiragana reading without punctuation/spaces (for matching)."""
    global _kks
    text = unicodedata.normalize("NFKC", text)
    try:
        if _kks is None:
            import pykakasi
            _kks = pykakasi.kakasi()
        text = "".join(t["hira"] for t in _kks.convert(text))
    except Exception:
        pass
    out = []
    for ch in text:
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:  # katakana -> hiragana
            ch = chr(o - 0x60)
        if unicodedata.category(ch)[0] in "LN":
            out.append(ch.lower())
    return "".join(out)


# ---------------------------------------------------------------- audio / asr

_model = None


def get_model(name: str):
    global _model
    if _model is None:
        import stable_whisper
        _model = stable_whisper.load_model(name, device="cpu")
    return _model


def load_audio(path: str | Path):
    import librosa
    y, _ = librosa.load(str(path), sr=SR, mono=True)
    return y


def _seg_score(seg) -> float:
    ps = [w.probability for w in seg.words if w.probability is not None]
    return float(sum(ps) / len(ps)) if ps else 0.0


def align_full(lines: list[dict], audio, model_name: str) -> list[dict]:
    """One-pass forced alignment of the entire text."""
    model = get_model(model_name)
    text = "\n".join(r["ja"] for r in lines)
    res = model.align(audio, text, language="ja", original_split=True)
    segs = [s for s in res.segments if s.text.strip()]
    if len(segs) != len(lines):
        raise RuntimeError(f"align returned {len(segs)} segments for {len(lines)} lines")
    out = []
    for r, s in zip(lines, segs):
        out.append({**r, "start": s.start, "end": s.end, "align_score": _seg_score(s)})
    return out


def transcribe_chars(audio, model_name: str, cache: str | None = None):
    """Return (reading_chars, times) from a word-timestamped transcription.

    With `cache`, the (machine) reading/time arrays are stored as JSON and
    reused on later runs; keep the cache out of version control.
    """
    import json
    if cache and Path(cache).exists():
        d = json.loads(Path(cache).read_text(encoding="utf-8"))
        return d["chars"], d["times"]
    model = get_model(model_name)
    res = model.transcribe(audio, language="ja", word_timestamps=True,
                           vad=False, regroup=False, verbose=None)
    chars, times = [], []
    for seg in res.segments:
        for w in seg.words:
            rd = reading(w.word)
            if not rd:
                continue
            n = len(rd)
            for i, ch in enumerate(rd):
                chars.append(ch)
                times.append(w.start + (w.end - w.start) * i / n)
    chars = "".join(chars)
    if cache:
        Path(cache).write_text(json.dumps({"chars": chars, "times": times}), encoding="utf-8")
    return chars, times


def _best_match(target: str, hay: str, lo: int = 0) -> tuple[int, int, float]:
    """Best fuzzy window of `hay[lo:]` for `target`: (start, end, ratio)."""
    n = len(target)
    best = (lo, min(len(hay), lo + n), 0.0)
    if n == 0:
        return best
    for L in {max(1, int(n * f)) for f in (0.8, 0.9, 1.0, 1.1, 1.25)}:
        for i in range(lo, max(lo + 1, len(hay) - L + 1)):
            r = difflib.SequenceMatcher(None, target, hay[i:i + L], autojunk=False).ratio()
            if r > best[2]:
                best = (i, i + L, r)
    return best


def align_by_transcript(lines, audio, model_name, monotonic=True, refine=False,
                        cache=None, slots=()):
    hay, times = transcribe_chars(audio, model_name, cache)
    if not hay:
        raise RuntimeError("empty transcription")
    out, lo = [], 0
    for r in lines:
        tgt = reading(r["ja"])
        i, j, score = _best_match(tgt, hay, lo if monotonic else 0)
        start, end = times[i], times[max(i, j - 1)]
        row = {**r, "start": start, "end": max(end, start + 0.3), "align_score": score,
               "coarse": (round(start, 2), round(end, 2))}
        if refine:
            row = _refine_window(row, audio, model_name, slots)
        out.append(row)
        if monotonic:
            lo = j
    return out


def _align_window(row, audio, model, a, b):
    """Forced-align row['ja'] inside audio[a:b]; returns (start, end, prob) or None."""
    clip = audio[int(a * SR):int(b * SR)]
    try:
        res = model.align(clip, row["ja"], language="ja", original_split=True)
    except Exception as e:
        print(f"  align failed {a:.1f}-{b:.1f}: {e}", file=sys.stderr)
        return None
    words = [w for s in res.segments for w in s.words]
    if not words:
        return None
    ps = [w.probability or 0 for w in words]
    return a + words[0].start, a + words[-1].end, sum(ps) / len(ps)


def _candidate_windows(row, slots, total, sec_per_char=0.3, pad=0.5):
    """Windows built from phrase slots around the coarse match: the slot nearest
    the coarse start (and its predecessor), extended over following slots until
    the line's expected duration fits. Falls back to a padded window."""
    need = max(1.5, len(reading(row["ja"])) * sec_per_char)
    if not slots:
        return [(max(0.0, row["start"] - 0.6), min(total, row["end"] + 0.6))]
    k = min(range(len(slots)), key=lambda i: 0 if slots[i][0] <= row["start"] <= slots[i][1]
            else min(abs(slots[i][0] - row["start"]), abs(slots[i][1] - row["start"])))
    i = max(0, k - 1)
    j = k
    while j + 1 < len(slots) and slots[j][1] - slots[k][0] < need:
        j += 1
    j = min(len(slots) - 1, j + 1)  # one slack slot: a single wide window keeps scores comparable
    return [(max(0.0, slots[i][0] - pad), min(total, slots[j][1] + pad))]


def _refine_window(row, audio, model_name, slots=()):
    """Per-line forced alignment inside slot-based candidate windows; keep the
    candidate with the best mean word probability."""
    model = get_model(model_name)
    total = len(audio) / SR
    best = None
    for a, b in _candidate_windows(row, slots, total):
        r = _align_window(row, audio, model, a, b)
        if r and (best is None or r[2] > best[2]):
            best = r
    if best is None:
        return row
    s0, e0, sc = best
    need = max(1.5, len(reading(row["ja"])) * 0.3)
    wb = _candidate_windows(row, slots, total)[0][1]
    if e0 >= wb - 0.15:  # end ran into the window edge: not trustworthy, cap by expected length
        e0 = min(e0, s0 + need * 1.3)
    return {**row, "start": s0, "end": e0, "align_score": round((row["align_score"] + sc) / 2, 3),
            "match_score": row["align_score"], "align_prob": sc}


# ------------------------------------------------------------ post-processing

def load_slots(path: str | Path | None) -> list[tuple[float, float]]:
    if not path or not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [(float(r["start"]), float(r["end"])) for r in csv.DictReader(f)]


def snap_and_clean(rows: list[dict], slots, snap: float = 0.35,
                   contiguous: bool = True) -> list[dict]:
    """contiguous=False (search mode): lines are independent, so only snap and
    enforce the minimum display; no overlap/gap-closing against neighbours."""
    starts = [s for s, _ in slots]
    ends = [e for _, e in slots]
    for r in rows:
        r["snapped"] = False
        if starts:
            s = min(starts, key=lambda x: abs(x - r["start"]))
            if abs(s - r["start"]) <= snap:
                r["start"], r["snapped"] = s, True
        if ends:
            e = min(ends, key=lambda x: abs(x - r["end"]))
            if abs(e - r["end"]) <= snap and e > r["start"]:
                r["end"], r["snapped"] = e, True
    rows.sort(key=lambda r: r["start"])
    if not contiguous:
        for r in rows:
            r["end"] = max(r["end"], r["start"] + MIN_DISPLAY)
        return rows
    for i, r in enumerate(rows):
        nxt = rows[i + 1]["start"] if i + 1 < len(rows) else None
        if i and r["start"] < rows[i - 1]["end"]:
            rows[i - 1]["end"] = max(rows[i - 1]["start"] + 0.1, r["start"] - EPS)
        if r["end"] - r["start"] < MIN_DISPLAY:
            r["end"] = r["start"] + MIN_DISPLAY
        if nxt is not None:
            if r["end"] > nxt - EPS:
                r["end"] = max(r["start"] + 0.1, nxt - EPS)
            elif nxt - r["end"] < CLOSE_GAP:
                r["end"] = nxt - EPS
    return rows


# ------------------------------------------------------------------- driver

def align(lyrics_txt, vocals_wav, slots_csv=None, *, mode="full",
          model_name="large-v3-turbo", snap=0.35, cache=None) -> list[dict]:
    lines = parse_lyrics(lyrics_txt)
    audio = load_audio(vocals_wav)
    if mode == "full":
        try:
            rows = align_full(lines, audio, model_name)
        except Exception as e:
            print(f"stable-ts full align failed ({e}); falling back to "
                  "transcription + difflib", file=sys.stderr)
            rows = align_by_transcript(lines, audio, model_name, monotonic=True,
                                       cache=cache)
    elif mode == "search":
        rows = align_by_transcript(lines, audio, model_name, monotonic=False,
                                   refine=True, cache=cache, slots=load_slots(slots_csv))
    else:
        raise ValueError(mode)
    for r in rows:
        print(f"  raw {r['start']:7.2f}-{r['end']:7.2f} score {r['align_score']:.2f} "
              f"coarse {r.get('coarse')} {r['ja'][:20]}", file=sys.stderr)
    rows = snap_and_clean(rows, load_slots(slots_csv), snap, contiguous=(mode == "full"))
    for r in rows:
        r["start"], r["end"] = round(r["start"], 2), round(r["end"], 2)
        r["align_score"] = round(float(r["align_score"]), 3)
    return rows


def write_csv(rows, out):
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["start", "end", "ja", "zh", "align_score", "snapped"])
        for r in rows:
            w.writerow([f"{r['start']:.2f}", f"{r['end']:.2f}", r["ja"], r.get("zh", ""),
                        r["align_score"], str(r["snapped"]).lower()])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--lyrics", required=True, help="user-supplied lyrics .txt")
    p.add_argument("--vocals", required=True, help="separated vocal stem .wav")
    p.add_argument("--slots", default=None, help="phrase-slot CSV (start,end,...)")
    p.add_argument("--out", required=True, help="output CSV")
    p.add_argument("--mode", choices=["full", "search"], default="full")
    p.add_argument("--model", default="large-v3-turbo")
    p.add_argument("--snap", type=float, default=0.35)
    p.add_argument("--cache", default=None,
                   help="JSON cache for the ASR pass (keep out of the repo)")
    a = p.parse_args(argv)
    rows = align(a.lyrics, a.vocals, a.slots, mode=a.mode, model_name=a.model, snap=a.snap,
               cache=a.cache)
    write_csv(rows, a.out)
    print(f"wrote {len(rows)} rows -> {a.out}")
    low = [r for r in rows if r["align_score"] < LOW_SCORE]
    for r in low:
        print(f"  LOW {r['align_score']:.2f}  {r['start']:7.2f}-{r['end']:7.2f}  {r['ja']}")
    print(f"{len(low)} low-score line(s) (< {LOW_SCORE})")


if __name__ == "__main__":
    main()
