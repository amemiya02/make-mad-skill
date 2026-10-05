"""Timed LRC (ja + zh) -> aligned lyric table for lyrics_ass.py, snapped to the vocal phrase slots of the work master.

When a lyric site's timestamps already sit on the sung onsets (光の唄: NetEase lines start within 0.15 s of the slot onsets of
analysis/music/lyrics-timed.csv), forced alignment is unnecessary: each line starts at the first slot onset near its timestamp
and ends at the end of the last slot sung before the next line. No lyric text is printed.

usage: python lrc_align.py lyrics.lrc lyrics-zh.lrc lyrics-timed.csv out.csv [--offset S] [--snap 0.6]
"""
import argparse, csv, re

TAG = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\]')


def read_lrc(path):
    rows = []
    try:
        text = open(path, encoding='utf-8').read()
    except FileNotFoundError:
        return rows
    for line in text.splitlines():
        body = TAG.sub('', line).strip()
        for m, s in TAG.findall(line):
            if body:
                rows.append((int(m) * 60 + float(s), body))
    return sorted(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ja'); ap.add_argument('zh'); ap.add_argument('slots'); ap.add_argument('out')
    ap.add_argument('--offset', type=float, default=0.0, help='work-master time minus lyric-file time')
    ap.add_argument('--snap', type=float, default=0.6, help='max distance from a timestamp to a slot onset')
    a = ap.parse_args()
    ja = [(t + a.offset, b) for t, b in read_lrc(a.ja)]
    zh = {round(t + a.offset, 1): b for t, b in read_lrc(a.zh)}
    slots = [(float(r['start']), float(r['end'])) for r in csv.DictReader(open(a.slots))]
    starts = []
    for t, _ in ja:   # pass 1: snap every start to the nearest slot onset
        near = [s for s in slots if abs(s[0] - t) <= a.snap]
        starts.append(min(near, key=lambda s: abs(s[0] - t))[0] if near else t)
    out, moved = [], []
    for i, ((t, body), start) in enumerate(zip(ja, starts)):   # pass 2: end = last slot sung before the next (snapped) start
        nxt = starts[i + 1] if i + 1 < len(starts) else 1e9
        sung = [s for s in slots if start - 0.01 <= s[0] < nxt - 0.05]
        end = min(max(s[1] for s in sung), nxt - 0.05) if sung else min(t + 4.0, nxt - 0.3)   # a slot spanning two lines is cut
        moved.append(round(start - t, 2))
        out.append(dict(start=f'{start:.2f}', end=f'{end:.2f}', ja=body, zh=zh.get(round(t, 1), ''), style='', slots=len(sung)))
    with open(a.out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['start', 'end', 'ja', 'zh', 'style', 'slots'])
        w.writeheader(); w.writerows(out)
    print(f'{len(out)} lines -> {a.out}; snap shifts (s): {moved}; slots per line: {[r["slots"] for r in out]}; '
          f'zh matched {sum(1 for r in out if r["zh"])}/{len(out)}')


if __name__ == '__main__':
    main()
