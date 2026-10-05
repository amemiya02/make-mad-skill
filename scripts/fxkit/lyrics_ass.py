"""Lyrics + dialogue captions as one editable .ass file, rendered to the transparent gfx layer by libass
(OpenAdobe engine image: its ffmpeg has libass; the Homebrew ffmpeg here does not).

Why ASS instead of the PIL layer (layers.Lyric/Caption): the user can open the .ass in Aegisub and retime or restyle any line,
and one style sheet keeps every text in the film in one typeface (the v7/v8 red line).

    import lyrics_ass as LA
    ass = LA.build(f'{ROOT}/analysis/music/lyrics-aligned.csv', CAPTIONS, f'{work}/text.ass', dark=L.bright_spans(P, outs, fx.FF))
    LA.render(ass, total_frames, f'{work}/gfx.mov')        # cached by a hash of the .ass + frame count

Look (from the corpus study, references/18): one sung line per screen, Japanese in a large serif with a soft halo at the lower
third, the Chinese line small beneath it; whole-line fades (no per-character pop-in on a lyrical song); a line that crosses a
high-key shot switches to dark ink with a light halo at that shot's cut, instead of vanishing.
"""
import csv, hashlib, os, subprocess

IMAGE = os.environ.get('OA_IMAGE', 'openadobe/engines:dev')
FPS = '24000/1001'
W, H = 1920, 1080

# colours are ASS &HAABBGGRR. Halo = a blurred, bordered copy on layer 0 under the crisp text on layer 1.
STYLES = {
    #        font                 size  primary     outline     border shadow align marginV spacing
    'JA':   ('Noto Serif CJK JP', 50, '&H00F6F6F6', '&H00141414', 1.3, 0, 2, 118, 4),
    'ZH':   ('Noto Serif CJK SC', 35, '&H00E4E8EE', '&H00141414', 1.2, 0, 2, 70, 3),
    'CAP':  ('Noto Serif CJK SC', 44, '&H00F6F6F6', '&H00141414', 1.0, 0, 2, 64, 2),   # spoken lines (in-song dialogue)
    'BIG':  ('Noto Serif CJK JP', 96, '&H00F6F6F6', '&H00141414', 1.2, 0, 5, 0, 18),    # rare: one held key word, centred
}
DARK_INK, DARK_HALO = '161616', ('40', 'F2F2F2')   # ink + light halo, for text over a high-key shot
LIGHT_HALO = ('50', '000000')                       # (alpha, BGR): soft dark halo under light text (a white glow lost
                                                    # contrast on mid-grey frames in the 2026-10-02 test; α 0x78 was too faint on sunset/fire/white-robe frames → 0x50)


def _ts(t):
    cs = int(round(max(0.0, t) * 100))
    return f'{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}'


def _style_line(name, s):
    font, size, prim, outl, bord, shad, align, mv, sp = s
    return (f'Style: {name},{font},{size},{prim},{prim},{outl},&H00000000,0,0,0,0,100,100,{sp},0,1,{bord},{shad},{align},'
            f'90,90,{mv},1')


def _overlap(a, b, spans):
    """fraction of [a,b] inside high-key spans"""
    if not spans or b <= a:
        return 0.0
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans) / (b - a)


def _event1(style, a, b, text, dark, fade):
    ha, hc = DARK_HALO if dark else LIGHT_HALO
    ink = f'\\1c&H{DARK_INK}&' if dark else ''
    f = f'\\fad({fade[0]},{fade[1]})'
    return [f'Dialogue: 0,{_ts(a)},{_ts(b)},{style},,0,0,0,,{{{f}\\bord6\\blur8\\3c&H{hc}&\\3a&H{ha}&\\1a&HFF&}}{text}',
            f'Dialogue: 1,{_ts(a)},{_ts(b)},{style},,0,0,0,,{{{f}\\blur0.5{ink}}}{text}']


def _event(style, a, b, text, spans=None, fade=(220, 320)):
    """one line, split at the edges of high-key spans so the ink flips exactly at the picture cut (light ink + dark halo on
    normal shots, dark ink + light halo on high-key ones); the fades stay on the line's outer edges only"""
    edges = sorted({a, b, *[x for sp in (spans or []) for x in sp if a < x < b]})
    pieces = [(x, y) for x, y in zip(edges, edges[1:]) if y - x > 0.02]
    out = []
    for i, (x, y) in enumerate(pieces):
        mid = (x + y) / 2
        dark = any(p <= mid < q for p, q in (spans or []))
        out += _event1(style, x, y, text, dark, (fade[0] if i == 0 else 0, fade[1] if i == len(pieces) - 1 else 0))
    return out


def read_lyrics(path):
    """aligned lyric table (start,end,ja,zh[,style]) -> [(a, b, ja, zh, style)]; rows without text are skipped"""
    if not path or not os.path.exists(path):
        return []
    rows = []
    for r in csv.DictReader(open(path, encoding='utf-8')):
        ja, zh = (r.get('ja') or '').strip(), (r.get('zh') or '').strip()
        if ja or zh:
            rows.append((float(r['start']), float(r['end']), ja, zh, (r.get('style') or '').strip()))
    return sorted(rows)


def build(lyrics_csv, captions, out, dark=None, lyrics=None, hold=0.35, gap=0.30, min_dur=0.9):
    """captions: [(t0, t1, text)] spoken lines; lyric lines overlapping one are dropped. dark: [(t0, t1)] high-key spans.
    A line holds `hold` s past its sung end but clears `gap` s before the next starts (never two lyric lines at once)."""
    rows = lyrics if lyrics is not None else read_lyrics(lyrics_csv)
    caps = sorted(captions or [])
    rows = [r for r in rows if not any(r[0] < c1 and r[1] > c0 for c0, c1, _ in caps)]
    ev = []
    for i, (a, b, ja, zh, st) in enumerate(rows):
        nxt = rows[i + 1][0] if i + 1 < len(rows) else None
        b2 = max(b + hold if nxt is None else min(b + hold, nxt - gap), a + min_dur)
        if st == 'big':
            ev += _event('BIG', a, b2, ja or zh, dark, fade=(420, 520))
            continue
        if ja:
            ev += _event('JA', a, b2, ja, dark)
        if zh:
            ev += _event('ZH', a + 0.12, b2, zh, dark, fade=(320, 320))
    for (c0, c1, text) in caps:
        ev += _event('CAP', c0, c1, text, dark, fade=(160, 200))
    head = ['[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {W}', f'PlayResY: {H}', 'WrapStyle: 2',
            'ScaledBorderAndShadow: yes', 'YCbCr Matrix: TV.709', '', '[V4+ Styles]',
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, '
            'StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
            *[_style_line(k, v) for k, v in STYLES.items()], '',
            '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    open(out, 'w', encoding='utf-8').write('\n'.join(head + ev) + '\n')
    return out


def render(ass, total_frames, out, force=False):
    """transparent qtrle/argb overlay of exactly total_frames frames (the format fx.assemble already overlays)"""
    out, ass = os.path.abspath(out), os.path.abspath(ass)
    key = hashlib.sha1(open(ass, 'rb').read() + str(total_frames).encode() + open(__file__, 'rb').read()).hexdigest()[:16]
    if not force and os.path.exists(out) and os.path.exists(out + '.key') and open(out + '.key').read().strip() == key:
        return out
    dirs = sorted({os.path.dirname(out), os.path.dirname(ass)})
    vols = [x for d in dirs for x in ('-v', f'{d}:{d}')]
    subprocess.run(['docker', 'run', '--rm', *vols, IMAGE, 'ffmpeg', '-v', 'error', '-y',
                    '-f', 'lavfi', '-i', f'color=c=black@0.0:s={W}x{H}:r={FPS},format=rgba',
                    '-vf', f"ass='{ass}':alpha=1", '-frames:v', str(total_frames), '-c:v', 'qtrle', '-pix_fmt', 'argb',
                    out + '.tmp.mov'], check=True)
    os.replace(out + '.tmp.mov', out)
    open(out + '.key', 'w').write(key)
    return out


if __name__ == '__main__':   # smoke test: python lyrics_ass.py lyrics.csv out_dir [seconds]
    import sys
    os.makedirs(sys.argv[2], exist_ok=True)
    n = int(float(sys.argv[3] if len(sys.argv) > 3 else 20) * 24000 / 1001)
    ass = build(None, [(1.0, 3.0, '你……你是谁？')], f'{sys.argv[2]}/test.ass', dark=[(6.0, 9.0)], lyrics=read_lyrics(sys.argv[1]))
    print(render(ass, n, f'{sys.argv[2]}/test.mov'))
