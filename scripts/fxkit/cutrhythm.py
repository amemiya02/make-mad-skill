"""cut-density curve of a build module vs the song's sections (references/17-top-mad-craft.md).
usage: cutrhythm.py build_module.py sections.csv
  sections.csv: section,start_s,end_s[,lo,hi]   (lo/hi = target cuts/min; defaults by section name below)
Flags: section outside its target band, peak/trough ratio < 2.5, no shot >= 3 s, shots < 0.25 s.
A flat curve (every section ~20-25 cpm) is the classic amateur rhythm: the energy must come from density contrast."""
import sys, csv, json, importlib.util

DEFAULT = {'intro': (6, 30), 'verse': (10, 26), 'pre': (20, 40), 'lift': (30, 55), 'chorus': (35, 60), 'final': (40, 72),
           'post': (10, 30), 'break': (8, 30), 'bridge': (6, 22), 'death': (6, 24), 'outro': (4, 22)}

def band(name):
    for k, v in DEFAULT.items():
        if name.lower().startswith(k):
            return v
    return (10, 50)

spec = importlib.util.spec_from_file_location('b', sys.argv[1]); b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
ts = sorted(s['t'] for s in b.SHOTS) + [b.END]
dur = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
rows, flags = [], []
for r in csv.DictReader(open(sys.argv[2], encoding='utf-8-sig')):
    name, a, c = r['section'], float(r['start_s']), float(r['end_s'])
    lo, hi = (float(r['lo']), float(r['hi'])) if r.get('lo') else band(name)
    k = sum(1 for t in ts[1:-1] if a <= t < c)
    d = [dur[i] for i in range(len(dur)) if a <= ts[i] < c] or [0]
    cpm = 60 * k / max(c - a, 1e-6)
    rows.append(dict(section=name, cpm=round(cpm, 1), target=[lo, hi], mean_shot=round(sum(d) / len(d), 2), max_shot=round(max(d), 2)))
    if not lo <= cpm <= hi:
        flags.append(f'{name}: {cpm:.1f} cpm outside {lo}-{hi}')
cp = [r['cpm'] for r in rows if r['cpm'] > 0]
ratio = max(cp) / min(cp) if cp else 0
if ratio < 2.5:
    flags.append(f'peak/trough {ratio:.1f} < 2.5 (flat rhythm)')
if not any(x >= 3.0 for x in dur):
    flags.append('no shot >= 3 s (no room to breathe)')
short = [round(ts[i], 3) for i, x in enumerate(dur) if x < 0.25]
if short:
    flags.append(f'shots < 0.25 s at {short} (only if the source itself flashes)')
print(json.dumps(dict(sections=rows, peak_trough=round(ratio, 2), total_cpm=round(60 * (len(ts) - 2) / b.END, 1), flags=flags),
                 ensure_ascii=False, indent=1))
