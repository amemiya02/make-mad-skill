#!/usr/bin/env python3
"""Fetch the timed lyrics (+ Chinese translation) of the MAD's song for the user, in one command.

Run by the user (the lyric text is theirs to obtain; this tool never prints it):
    cd <project> && python fetch_lyrics.py --title 光の唄 --artist 大原ゆい子     # search, pick the exact title/artist
    python fetch_lyrics.py --id 123456                                         # a specific NetEase song id
    python fetch_lyrics.py --title 光の唄 --artist 大原ゆい子 --search-only     # list candidates, fetch nothing
Verify with a second source (e.g. Kugou) that the line count matches before trusting a short lyric file.

Sources: NetEase Cloud Music (timed original + uploader translation), falling back to lrclib.net (original only).
Writes:
    analysis/music/lyrics.lrc      timed original lines   [mm:ss.xx]text
    analysis/music/lyrics-zh.lrc   timed translation      (if the source has one)
    analysis/music/lyrics.txt      ja<TAB>zh per sung line (the input of lyric_align.py)
Prints only metadata and line counts.
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(os.environ.get('MAD_ROOT', os.getcwd()))   # the MAD project root (writes <root>/analysis/music/)
OUT = ROOT / 'analysis' / 'music'
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
      'Referer': 'https://music.163.com/'}
TAG = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\]')


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))


def ne_search(q):
    d = get('https://music.163.com/api/cloudsearch/pc?' + urllib.parse.urlencode({'s': q, 'type': 1, 'limit': 10}))   # search/get/web now returns an encrypted string
    res = d.get('result') if isinstance(d.get('result'), dict) else {}
    return [(s['id'], s['name'], '/'.join(a['name'] for a in s.get('ar', s.get('artists', []))), s.get('dt', s.get('duration', 0)) / 1000)
            for s in res.get('songs', [])]


def parse_lrc(text):
    rows = []
    for line in (text or '').splitlines():
        tags = TAG.findall(line)
        body = TAG.sub('', line).strip()
        if not tags or not body or re.match(r'^(作词|作曲|编曲|作詞|編曲|by|词|曲)\s*[:：]', body):
            continue
        for m, s in tags:
            rows.append((int(m) * 60 + float(s), body))
    return sorted(rows)


def write_lrc(path, rows):
    path.write_text(''.join(f'[{int(t // 60):02d}:{t % 60:05.2f}]{b}\n' for t, b in rows), encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--title', required=False)
    ap.add_argument('--artist', default='')
    ap.add_argument('--q', help='free search text (default: title + artist)')
    ap.add_argument('--id', type=int)
    ap.add_argument('--search-only', action='store_true')
    a = ap.parse_args()
    if not a.id and not (a.q or a.title):
        ap.error('give --title (and --artist), --q or --id')
    a.q = a.q or f'{a.title} {a.artist}'.strip()
    OUT.mkdir(parents=True, exist_ok=True)
    sid = a.id
    if not sid:
        cands = ne_search(a.q)
        for c in cands:
            print(f'candidate id={c[0]}  {c[1]} — {c[2]}  ({c[3]:.0f} s)')
        if a.search_only:
            return
        exact = [c for c in cands if (not a.title or a.title in c[1]) and (not a.artist or a.artist in c[2])] or cands
        if not exact:
            sys.exit('no NetEase match; pass --id')
        sid = exact[0][0]
        print(f'using id={sid}')
    d = get(f'https://music.163.com/api/song/lyric?id={sid}&lv=1&tv=-1')
    ja, zh = parse_lrc(d.get('lrc', {}).get('lyric')), parse_lrc(d.get('tlyric', {}).get('lyric'))
    if not ja:
        q = urllib.parse.urlencode({'track_name': a.title or a.q, 'artist_name': a.artist})
        hits = get('https://lrclib.net/api/search?' + q)
        ja = parse_lrc(next((h.get('syncedLyrics') for h in hits if h.get('syncedLyrics')), ''))
        print('NetEase had no lyric; lrclib lines:', len(ja))
    if not ja:
        sys.exit('no timed lyrics found; paste them into analysis/music/lyrics.txt (ja<TAB>zh per line)')
    write_lrc(OUT / 'lyrics.lrc', ja)
    if zh:
        write_lrc(OUT / 'lyrics-zh.lrc', zh)
    zmap = {round(t, 1): b for t, b in zh}
    lines = [f'{b}\t{zmap.get(round(t, 1), "")}'.rstrip('\t') for t, b in ja]
    (OUT / 'lyrics.txt').write_text('# fetched by fetch_lyrics.py (NetEase id %s)\n' % sid + '\n'.join(lines) + '\n', encoding='utf-8')
    print(f'wrote {len(ja)} timed lines, {len(zh)} translated lines -> {OUT / "lyrics.txt"}')


if __name__ == '__main__':
    main()
