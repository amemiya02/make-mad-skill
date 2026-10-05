"""Export a build module's edit as OpenTimelineIO, so a person can open and polish it in an NLE
(DaVinci Resolve 18.5+: File > Import > Timeline; Kdenlive: File > Import > OTIO).

usage: python edit/tools/export_otio.py edit/build_v9.py out.otio
Tracks:
  V1  every shot, as a clip of the original episode file (source range = src … src + duration × speed); dissolves as transitions
  A1  the song (work master)
  A2  dialogue lines at their song times (source = the episode file's audio; the cleaned stems stay in renders/…/audio-dialogue.wav)
Grades, glow and text layers are not carried over: they live in fx.py/grades.py and the rendered gfx layer.
"""
import sys, os, json, subprocess, importlib.util
# opentimelineio 0.18 wheels throw "bad any cast" on Python 3.14, so the OTIO side runs in a py3.12 env (OpenAdobe's venv):
#   ../.venv/bin/python edit/tools/export_otio.py edit/build_v9.py out.otio      (dumps the plan, then re-runs itself under OTIO_PY)
OTIO_PY = os.environ.get('OTIO_PY', os.path.expanduser('~/vscode/OpenAdobe/.venv/bin/python'))   # any py≤3.13 env with opentimelineio
if sys.argv[1] == '--dump':
    spec = importlib.util.spec_from_file_location('b', sys.argv[2]); b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
    import fx
    plan = [dict(id=s['id'], ep=s['ep'], src=s['src'], grade=s['grade'], fx={k: str(x) for k, x in s['fx'].items()}, speed=s.get('speed', 1),
                 n=n, head=head, file=None if s['ep'] == 'BLK' else fx.epfile(s['ep'])) for (s, a, n, head) in fx.plan(b.SHOTS, b.END)]
    eps = {str(d[0]): fx.epfile(d[0]) for d in getattr(b, 'DIALOGUE', [])}
    print(json.dumps(dict(FF=fx.FF, END=b.END, MUSIC=b.MUSIC, plan=plan, dialogue=getattr(b, 'DIALOGUE', []), eps=eps)))
    sys.exit()
if not sys.argv[1].endswith('.json'):
    here = os.path.abspath(__file__)
    dump = subprocess.run([sys.executable, here, '--dump', sys.argv[1]], capture_output=True, text=True, check=True).stdout
    jp = sys.argv[2] + '.plan.json'; open(jp, 'w').write(dump)
    sys.exit(subprocess.run([OTIO_PY, here, jp, sys.argv[2]]).returncode)
import opentimelineio as otio
P = json.load(open(sys.argv[1])); os.remove(sys.argv[1])
R = P['FF']
rt = lambda frames: otio.opentime.RationalTime(frames, R)
tr = lambda start_s, dur_s: otio.opentime.TimeRange(otio.opentime.RationalTime(round(start_s * R), R),
                                                     otio.opentime.RationalTime(max(1, round(dur_s * R)), R))
tl = otio.schema.Timeline(name=os.path.splitext(os.path.basename(sys.argv[2]))[0])
v = otio.schema.Track(name='V1', kind=otio.schema.TrackKind.Video)
refs = {}


def ref(path):
    if path not in refs:
        refs[path] = otio.schema.ExternalReference(target_url='file://' + path)
    return refs[path]


for s in P['plan']:
    n, head, sp = s['n'], s['head'], s['speed']
    if s['ep'] == 'BLK':
        v.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(rt(0), rt(n))))
        continue
    if head and len(v):
        v.append(otio.schema.Transition(transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                                        in_offset=rt(head // 2), out_offset=rt(head - head // 2)))
    # source_range.duration is the clip's length on the track; a LinearTimeWarp tells the NLE to consume n×speed of media
    c = otio.schema.Clip(name=s['id'], media_reference=ref(s['file']), source_range=otio.opentime.TimeRange(
        otio.opentime.RationalTime(round(s['src'] * R), R), rt(n)))
    if sp != 1:
        c.effects.append(otio.schema.LinearTimeWarp(time_scalar=sp))
    c.metadata['mad'] = dict(grade=str(s['grade']), fx=s['fx'])
    v.append(c)
a1 = otio.schema.Track(name='A1 song', kind=otio.schema.TrackKind.Audio)
a1.append(otio.schema.Clip(name='song', media_reference=ref(P['MUSIC']), source_range=tr(0, P['END'])))
a2 = otio.schema.Track(name='A2 dialogue', kind=otio.schema.TrackKind.Audio)
pos = 0.0
for (ep, s0, s1, t, gain, fade) in sorted(P['dialogue'], key=lambda r: r[3]):
    if t > pos:
        a2.append(otio.schema.Gap(source_range=tr(0, t - pos)))
    a2.append(otio.schema.Clip(name=f'E{ep} {s0:.2f}', media_reference=ref(P['eps'][str(ep)]), source_range=tr(s0, s1 - s0)))
    pos = t + (s1 - s0)
tl.tracks.extend([v, a1, a2])
otio.adapters.write_to_file(tl, sys.argv[2])
print('wrote', sys.argv[2], 'clips', len([x for x in v if isinstance(x, otio.schema.Clip)]), 'duration', round(tl.duration().to_seconds(), 2))
