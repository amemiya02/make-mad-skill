#!/usr/bin/env python3
"""make-mad: local, auditable AMV/MAD production utilities (Python 3.10+).

The renderer is deliberately bounded: one picture track, constant retimes,
cut/dissolve, still-image camera moves, independent audio layers, optional ASS.
Advanced composites must be rendered in a compositor and re-ingested as assets.
No shell commands from media metadata or model-generated filters are executed.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.metadata
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from fractions import Fraction
from typing import Any
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.1.0'

class MadError(Exception):
    pass

def run(args: list[str], *, binary: bool = False, timeout: int = 1800,
        cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        p = subprocess.run([str(a) for a in args], capture_output=True,
                           text=not binary, timeout=timeout, cwd=cwd, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise MadError(str(e)) from e
    if p.returncode:
        err = p.stderr.decode(errors='replace') if binary else p.stderr
        raise MadError(f'{args[0]} exited {p.returncode}: {err[-5000:]}')
    return p

def ff(args: list[str], *, cwd: Path | None = None, level: str = 'error'):
    return run(['ffmpeg', '-hide_banner', '-nostdin', '-y', '-loglevel', level,
                '-filter_threads', '2', '-filter_complex_threads', '2'] + args, cwd=cwd)

def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise MadError(f'Cannot read JSON {path}: {e}') from e

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def frac(value: Any) -> Fraction:
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError, TypeError) as e:
        raise MadError(f'Invalid rational number: {value!r}') from e
    return result

def frame_seconds(frame: int, fps: str | Fraction) -> Fraction:
    rate = frac(fps)
    if rate <= 0:
        raise MadError('fps must be positive')
    return Fraction(frame, 1) / rate

def nearest_frame(seconds: Any, fps: str) -> int:
    """Round positive absolute timestamps half up, never sum rounded beat lengths."""
    x = frac(seconds) * frac(fps)
    if x < 0:
        raise MadError('Negative time')
    return (2*x.numerator+x.denominator)//(2*x.denominator)

def secstr(value: Any) -> str:
    return f'{float(value):.12f}'

def probe(path: Path, *, count: bool = False) -> dict:
    cmd = ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json']
    if count:
        cmd += ['-count_frames']
    return json.loads(run(cmd+[str(path)]).stdout)

def media_duration(meta: dict, kind: str | None = None) -> float:
    if kind:
        for s in meta.get('streams', []):
            if s.get('codec_type') == kind and s.get('duration') not in (None, 'N/A'):
                return float(s['duration'])
    return float(meta.get('format', {}).get('duration', 0))

def media_path(base: Path, value: str) -> Path:
    if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', value):
        raise MadError('Timeline assets must be local files, not network URLs')
    p = Path(value).expanduser()
    return (base / p).resolve() if not p.is_absolute() else p.resolve()

def csv_write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def doctor() -> dict:
    report = {'make_mad': VERSION, 'python': sys.version, 'binaries': {}, 'optional_python': {}}
    for name in ['ffmpeg', 'ffprobe']:
        report['binaries'][name] = run([name, '-version']).stdout.splitlines()[0] if shutil.which(name) else None
    report['optional_download_tools'] = {name: shutil.which(name) for name in ['yt-dlp', 'aria2c']}
    for name in ['numpy', 'librosa', 'Pillow', 'jsonschema', 'opentimelineio']:
        try:
            report['optional_python'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report['optional_python'][name] = None
    if shutil.which('ffmpeg'):
        text = run(['ffmpeg', '-hide_banner', '-filters']).stdout
        report['filters'] = {k: bool(re.search(r'\s'+k+r'\s', text)) for k in
                             ['xfade','zoompan','loudnorm','subtitles','blackdetect','freezedetect']}
        report['h264_encoder'] = 'libx264' in run(['ffmpeg','-hide_banner','-encoders']).stdout
    return report

def init_project(directory: Path, name: str, fps: str) -> dict:
    if directory.exists() and any(directory.iterdir()):
        raise MadError('Refusing to overwrite a non-empty project directory')
    if frac(fps) <= 0:
        raise MadError('Invalid fps')
    for folder in ['assets/video','assets/audio','assets/stills','assets/precomps','analysis',
                   'edit','renders','reviews','delivery','references']:
        (directory/folder).mkdir(parents=True, exist_ok=True)
    for name_in in ['brief.md','acquisition-brief.json','source-candidates.csv','anime-coverage.csv',
                    'music-shortlist.csv','reference-ledger.csv','shot-log.csv',
                    'music-map.csv','effect-plan.csv','review.md','release-checklist.md']:
        dest = directory/('reviews' if name_in in ['review.md','release-checklist.md'] else 'analysis')/name_in
        shutil.copy2(ROOT/'templates'/name_in, dest)
    t = read_json(ROOT/'templates/timeline.json')
    t['name'], t['fps'] = name, fps
    write_json(directory/'edit/timeline.json', t)
    (directory/'PROJECT.md').write_text(f'# {name}\n\nStatus: BRIEF\nFPS: {fps}\n\n'
       'Timeline asset paths are relative to edit/timeline.json, e.g. ../assets/video/source.mkv.\n'
       'Never overwrite source masters. Update analysis/brief.md before selecting footage.\n', encoding='utf-8')
    return {'project': str(directory.resolve()), 'status': 'BRIEF'}

def validate_data(t: dict, base: Path, *, final: bool = False, inspect: bool = True) -> dict:
    errors, warnings = [], []
    try:
        import jsonschema
    except ImportError as e:
        raise MadError('Install requirements-core.txt (jsonschema) for contract validation') from e
    for e in sorted(jsonschema.Draft202012Validator(read_json(ROOT/'templates/timeline.schema.json')).iter_errors(t),
                    key=lambda e: str(e.path)):
        errors.append('/'.join(str(x) for x in e.path)+': '+e.message)
    if errors:
        return {'ok': False, 'errors': errors, 'warnings': warnings}
    rate = frac(t['fps'])
    if rate <= 0 or rate > 120:
        errors.append('FPS must be >0 and <=120')
        return {'ok': False, 'errors': errors, 'warnings': warnings}
    assets = {a['id']: a for a in t['assets']}
    if len(assets) != len(t['assets']):
        errors.append('Duplicate asset IDs')
    ids = [s['id'] for s in t['shots']]
    if len(ids) != len(set(ids)):
        errors.append('Duplicate shot IDs')
    if not t['shots']:
        errors.append('No shots: an initialized template is not a renderable film')
    previous = None
    metas = {}
    used: dict[str, list[tuple[float,float]]] = {}
    for s in t['shots']:
        trans = s['transition_in']
        overlap = trans['duration_frames']
        if (trans['type'] == 'cut' and overlap != 0) or (trans['type'] == 'dissolve' and overlap <= 0):
            errors.append(f'{s["id"]}: invalid cut/dissolve duration')
        if previous is None:
            if s['start_frame'] != 0 or overlap != 0:
                errors.append('First shot must start at frame 0 with a cut')
        else:
            expected = previous['start_frame']+previous['duration_frames']-overlap
            if s['start_frame'] != expected:
                errors.append(f'{s["id"]}: start must be {expected}; gaps, unintended overlap or triple overlap are forbidden')
            if overlap >= min(s['duration_frames'], previous['duration_frames']):
                errors.append(f'{s["id"]}: dissolve consumes an entire shot')
            if overlap+previous['transition_in']['duration_frames'] >= previous['duration_frames'] and overlap:
                errors.append(f'{s["id"]}: adjacent dissolves overlap; precompose this sequence')
        if s['asset_id'] not in assets:
            errors.append(f'{s["id"]}: unknown asset {s["asset_id"]}')
        else:
            a = assets[s['asset_id']]
            if a['kind'] not in ('video','image','precomp'):
                errors.append(f'{s["id"]}: picture requires video/image/precomp')
            speed = frac(s['speed'])
            start = frac(s['source_in'])
            if speed < Fraction(1, 8) or speed > 8 or start < 0:
                errors.append(f'{s["id"]}: source_in >=0 and 1/8 <= speed <=8 required')
            if a['kind'] == 'image' and (start != 0 or speed != 1):
                errors.append(f'{s["id"]}: still images require source_in=0 and speed=1')
            if 'motion' in s and a['kind'] != 'image':
                errors.append(f'{s["id"]}: camera motion only supports stills; precompose video moves')
            used.setdefault(a['id'], []).append((float(start),float(start+frame_seconds(s['duration_frames'],rate)*speed)))
        previous = s
    end = previous['start_frame']+previous['duration_frames'] if previous else 0
    if end != t['duration_frames']:
        errors.append(f'Duration mismatch: timeline says {t["duration_frames"]}, picture ends {end}')
    for tr in t['audio']:
        if tr['asset_id'] not in assets:
            errors.append(f'Audio: unknown asset {tr["asset_id"]}')
            continue
        if assets[tr['asset_id']]['kind'] == 'image':
            errors.append('An image cannot be used as an audio source')
        if tr['start_frame']+tr['duration_frames'] > end:
            errors.append('Audio extends past picture: trim explicitly, never silently truncate')
        if tr['fade_in_frames']+tr['fade_out_frames'] > tr['duration_frames']:
            errors.append('Audio fades exceed clip length')
        start = frac(tr['source_in'])
        if start < 0:
            errors.append('Audio source_in cannot be negative')
        used.setdefault(tr['asset_id'], []).append((float(start),float(start+frame_seconds(tr['duration_frames'],rate))))
    if not t['audio']:
        errors.append('No audio: a silent render cannot be called an AMV/MAD delivery')
    if t.get('caption_file'):
        if not media_path(base,t['caption_file']).is_file():
            errors.append('Caption file is missing')
        if final and t['reviews']['captions'] != 'pass':
            errors.append('Captioned delivery requires caption review')
    if final:
        for field in ['music_map','story','rhythm','sound','color','effects','flash_review']:
            if t['reviews'][field] != 'pass':
                errors.append('Final gate requires review: '+field)
    for aid, ranges in used.items():
        a = assets[aid]
        p = media_path(base,a['path'])
        if not p.is_file():
            errors.append(f'{aid}: missing local asset {p}')
            continue
        if not inspect:
            continue
        try:
            m = probe(p)
            metas[aid] = m
        except MadError as e:
            errors.append(f'{aid}: {e}')
            continue
        videos = [x for x in m.get('streams',[]) if x.get('codec_type') == 'video']
        audio_streams = [x for x in m.get('streams',[]) if x.get('codec_type') == 'audio']
        if any(tr['asset_id'] == aid for tr in t['audio']) and not audio_streams:
            errors.append(f'{aid}: no audio stream')
        if a['kind'] in ('video','image','precomp'):
            if not videos:
                errors.append(f'{aid}: no picture stream')
            else:
                v = videos[0]
                if v.get('color_transfer') in ('smpte2084','arib-std-b67'):
                    errors.append(f'{aid}: HDR must be properly transformed to reviewed SDR before this baseline renderer')
                if v.get('field_order') not in (None,'unknown','progressive'):
                    errors.append(f'{aid}: interlaced source requires a reviewed progressive conform')
                if final and (v['width'] < 1920 or v['height'] < 1080):
                    errors.append(f'{aid}: native raster below 1920x1080; no implicit upscaling exception')
                if v.get('color_transfer') in (None, 'unknown'):
                    warnings.append(f'{aid}: unspecified transfer metadata; inspect/record color interpretation')
            if final:
                if a['kind'] == 'precomp' and not a.get('source_lineage','').strip():
                    errors.append(f'{aid}: precomp requires its upstream source lineage manifest')
                for field in ['native_quality','no_burned_subtitles','no_logos','color_interpretation']:
                    if a['review'].get(field) != 'pass':
                        errors.append(f'{aid}: source review pending: {field}')
                if not a['review'].get('evidence'):
                    errors.append(f'{aid}: clean-source review needs evidence, not a filename assumption')
                coverage = a['review'].get('clean_ranges',[])
                if a['kind'] != 'image':
                    for lo,hi in ranges:
                        if not any(float(frac(r[0])) <= lo+1e-6 and float(frac(r[1])) >= hi-1e-6 for r in coverage):
                            errors.append(f'{aid}: source interval {lo:.4f}..{hi:.4f} not covered by clean review')
        if a['kind'] != 'image':
            kind = 'audio' if a['kind'] == 'audio' else 'video'
            dur = media_duration(m,kind)
            for lo,hi in ranges:
                if hi > dur+0.001:
                    errors.append(f'{aid}: requested {hi:.6f}s exceeds source duration {dur:.6f}s')
        if final and (not a['usage_basis'].strip() or not a['provenance'].strip()):
            errors.append(f'{aid}: record provenance and usage basis before delivery')
    return {'ok': not errors, 'errors': errors, 'warnings': warnings,
            'duration_frames': end, 'duration_seconds': float(frame_seconds(end,rate)),
            'review_status': 'declared_by_editor_not_independently_verified'}

def loudness(path: Path, target: dict) -> dict:
    p = ff(['-i',str(path),'-vn','-af',
            f'loudnorm=I={target["integrated_lufs"]}:TP={target["true_peak_dbtp"]}:LRA={target["lra"]}:print_format=json',
            '-f','null','-'], level='info')
    matches = re.findall(r'\{\s*"input_i".*?\}',p.stderr,re.S)
    if not matches:
        raise MadError('Cannot parse loudnorm measurements')
    return json.loads(matches[-1])

def video_encode_args(draft: bool) -> list[str]:
    return ['-c:v','libx264','-threads','2','-preset','veryfast' if draft else 'medium',
            '-crf','18' if draft else '14','-pix_fmt','yuv420p',
            '-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv']

def render(tpath: Path, output: Path, *, draft: bool, normalize: bool, overwrite: bool) -> dict:
    t, base = read_json(tpath), tpath.parent
    check = validate_data(t,base,final=not draft)
    if not check['ok']:
        raise MadError(json.dumps(check,ensure_ascii=False,indent=2))
    if output.exists() and not overwrite:
        raise MadError('Output exists: use --overwrite explicitly')
    if output.suffix.lower() != '.mp4':
        raise MadError('Baseline delivery must use .mp4')
    output.parent.mkdir(parents=True,exist_ok=True)
    assets = {a['id']:a for a in t['assets']}
    fps = t['fps']; rate = frac(fps)
    w,h = (1280,720) if draft else (t['width'],t['height'])
    total = secstr(frame_seconds(t['duration_frames'],rate))
    renderlog = {'timeline_sha256': sha(tpath), 'version': VERSION, 'draft': draft,
                 'limitations': ['one picture track','constant retimes only','SDR only',
                                'H.264 review/delivery render, not an archival mezzanine',
                                'advanced VFX must be precomposed'], 'validation': check}
    with tempfile.TemporaryDirectory(prefix='make-mad-',dir=output.parent) as d:
        tmp = Path(d)
        parts=[]
        for i,s in enumerate(t['shots']):
            a=assets[s['asset_id']]; p=media_path(base,a['path']); duration=frame_seconds(s['duration_frames'],rate)
            if a['kind']=='image':
                inputargs=['-loop','1','-framerate',fps,'-i',str(p)]
                if s.get('motion'):
                    m=s['motion']; n=max(1,s['duration_frames']-1)
                    u=f'min(on/{n},1)'; e=f'({u})*({u})*(3-2*({u}))'
                    interp=lambda k: f'{m[k+"_start"]}+({m[k+"_end"]}-{m[k+"_start"]})*({e})'
                    filt=f"pad=ceil(max(iw\\,ih*{w}/{h})/2)*2:ceil(max(ih\\,iw*{h}/{w})/2)*2:(ow-iw)/2:(oh-ih)/2,zoompan=z='{interp('zoom')}':x='(iw-iw/zoom)*({interp('x')})':y='(ih-ih/zoom)*({interp('y')})':d=1:s={w}x{h}:fps={fps}"
                else:
                    filt=f'scale={w}:{h}:force_original_aspect_ratio=decrease:out_range=tv:out_color_matrix=bt709,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2'
            else:
                inputargs=['-ss',secstr(frac(s['source_in'])),'-i',str(p)]
                filt=f'setpts=(PTS-STARTPTS)/({s["speed"]}),fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease:out_range=tv:out_color_matrix=bt709,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2'
            filt+=f',setsar=1,format=yuv420p,trim=end_frame={s["duration_frames"]},setpts=PTS-STARTPTS'
            part=tmp/f'shot_{i:05d}.mp4'
            ff(inputargs+['-map','0:v:0','-an','-sn','-dn','-vf',filt,
                          '-frames:v',str(s['duration_frames']),'-r',fps]+video_encode_args(draft)+[str(part)])
            actual=probe(part,count=True)
            nv=int(next(x for x in actual['streams'] if x['codec_type']=='video').get('nb_read_frames',0))
            if nv!=s['duration_frames']:
                raise MadError(f'{s["id"]}: decoded {nv} instead of {s["duration_frames"]} frames; no silent freeze padding')
            parts.append(part)
        picture=tmp/'picture.mp4'
        inputargs=[]; graph=[]
        for i,p in enumerate(parts):
            inputargs+=['-i',str(p)]
            graph.append(f'[{i}:v]setpts=PTS-STARTPTS,fps={fps},settb=AVTB[v{i}]')
        current='v0'
        for i,s in enumerate(t['shots'][1:],1):
            nxt=f'p{i}'
            tr=s['transition_in']
            if tr['type']=='cut':
                graph.append(f'[{current}][v{i}]concat=n=2:v=1:a=0[raw{nxt}]')
                graph.append(f'[raw{nxt}]setpts=PTS-STARTPTS,fps={fps},settb=AVTB[{nxt}]')
            else:
                graph.append(f'[{current}][v{i}]xfade=transition=fade:duration={secstr(frame_seconds(tr["duration_frames"],rate))}:offset={secstr(frame_seconds(s["start_frame"],rate))}[{nxt}]')
            current=nxt
        if t.get('caption_file'):
            cap=media_path(base,t['caption_file']); ext=cap.suffix.lower()
            if ext not in ('.ass','.srt'):
                raise MadError('caption_file supports .ass or .srt only')
            shutil.copy2(cap,tmp/('captions'+ext))
            graph.append(f'[{current}]subtitles=filename=captions{ext}[subbed]')
            current='subbed'
        ff(inputargs+['-filter_complex',';'.join(graph),'-map',f'[{current}]','-an',
                      '-frames:v',str(t['duration_frames']),'-r',fps]+video_encode_args(draft)+[str(picture)],cwd=tmp)
        inputs=[]; filters=[]; labels=[]
        for i,tr in enumerate(t['audio']):
            p=media_path(base,assets[tr['asset_id']]['path'])
            inputs+=['-ss',secstr(frac(tr['source_in'])),'-i',str(p)]
            dur=frame_seconds(tr['duration_frames'],rate)
            delay=nearest_frame(frame_seconds(tr['start_frame'],rate),'48000')
            chain=f'[{i}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=duration={secstr(dur)},asetpts=PTS-STARTPTS,volume={tr["gain_db"]}dB'
            if tr['fade_in_frames']:
                chain+=f',afade=t=in:st=0:d={secstr(frame_seconds(tr["fade_in_frames"],rate))}'
            if tr['fade_out_frames']:
                fade=frame_seconds(tr['fade_out_frames'],rate)
                chain+=f',afade=t=out:st={secstr(dur-fade)}:d={secstr(fade)}'
            label=f'a{i}'
            chain+=f',adelay={delay}S:all=1[{label}]'
            filters.append(chain); labels.append(f'[{label}]')
        filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0:duration=longest,apad,atrim=duration={total}[mix]')
        mix=tmp/'mix.wav'
        ff(inputs+['-filter_complex',';'.join(filters),'-map','[mix]','-c:a','pcm_f32le','-ar','48000',str(mix)])
        measured=loudness(mix,t['audio_target']); renderlog['pre_encode_loudness']=measured
        audio=mix
        if normalize:
            if not all(math.isfinite(float(measured[k])) for k in ['input_i','input_tp','input_lra','input_thresh','target_offset']):
                raise MadError('Cannot normalize silent/non-finite audio')
            a=t['audio_target']; audio=tmp/'normalized.wav'
            nf=(f'loudnorm=I={a["integrated_lufs"]}:TP={a["true_peak_dbtp"]}:LRA={a["lra"]}'
                f':measured_I={measured["input_i"]}:measured_TP={measured["input_tp"]}'
                f':measured_LRA={measured["input_lra"]}:measured_thresh={measured["input_thresh"]}'
                f':offset={measured["target_offset"]}:linear=true:print_format=json')
            second=ff(['-i',str(mix),'-af',nf,'-ar','48000','-c:a','pcm_s24le',str(audio)],level='info')
            renderlog['normalization_log']=second.stderr[-3000:]
        staged=tmp/'delivery.mp4'
        ff(['-i',str(picture),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','copy',
            '-c:a','aac','-b:a','320k','-ar','48000','-t',total,'-sn','-dn','-map_metadata','-1',
            '-movflags','+faststart',str(staged)])
        actual=probe(staged,count=True)
        nv=int(next(x for x in actual['streams'] if x['codec_type']=='video').get('nb_read_frames',0))
        if nv!=t['duration_frames']:
            raise MadError(f'Render frame count mismatch: {nv}; expected {t["duration_frames"]}')
        os.replace(staged,output)
    renderlog['output']=str(output.resolve()); renderlog['output_sha256']=sha(output)
    renderlog['status']='rendered_not_quality_approved'
    write_json(output.with_suffix('.render.json'),renderlog)
    return renderlog

def qa(path: Path, timeline: Path | None, out: Path, scan: bool) -> dict:
    m=probe(path,count=True); errors=[]; warnings=[]
    vs=[s for s in m['streams'] if s['codec_type']=='video']
    aus=[s for s in m['streams'] if s['codec_type']=='audio']
    if len(vs)!=1: errors.append('Expected exactly one video stream')
    if len(aus)!=1: errors.append('Expected exactly one audio stream')
    if any(s['codec_type']=='subtitle' for s in m['streams']):
        warnings.append('Container contains subtitle streams; distinguish these from intentional authored captions')
    t=read_json(timeline) if timeline else None
    if t and vs:
        v=vs[0]
        if int(v.get('nb_read_frames',0))!=t['duration_frames']: errors.append('Frame count mismatch')
        if frac(v.get('avg_frame_rate','0'))!=frac(t['fps']): errors.append('FPS mismatch')
        if (v['width'],v['height'])!=(t['width'],t['height']): warnings.append('Not project delivery raster (possibly an intentional draft)')
        expected=float(frame_seconds(t['duration_frames'],t['fps']))
        if aus and abs(media_duration(m,'audio')-expected)>max(1/float(frac(t['fps'])),1024/48000)+0.005:
            errors.append('Audio duration differs by more than one frame/AAC packet tolerance')
    target=t['audio_target'] if t else {'integrated_lufs':-16,'true_peak_dbtp':-1.5,'lra':11}
    measure=loudness(path,target) if aus else {}
    if measure:
        tp=float(measure['input_tp']); integrated=float(measure['input_i'])
        if tp>-1.0: errors.append(f'Encoded true peak {tp:.2f} dBTP exceeds the project QC ceiling -1.0 dBTP')
        if not math.isfinite(integrated): errors.append('Silent/non-finite audio loudness')
        elif abs(integrated-target['integrated_lufs'])>2:
            warnings.append('Loudness differs from chosen target; listening review, not automatic normalization, decides')
    events=[]
    if scan:
        p=ff(['-xerror','-i',str(path),'-vf','blackdetect=d=0.08:pix_th=0.05,freezedetect=n=-55dB:d=0.5',
              '-an','-f','null','-'],level='info')
        events=[x.strip() for x in p.stderr.splitlines() if 'black_start:' in x or 'freeze_' in x]
        if events: warnings.append('Black/hold candidates require editorial review; deliberate holds are not automatically errors')
    else:
        ff(['-v','error','-xerror','-i',str(path),'-map','0:v:0','-map','0:a:0?', '-f','null','-'])
    result={'automated_status':'fail' if errors else 'technical_checks_pass_human_review_required',
            'errors':errors,'warnings':warnings,'loudness':measure,'candidate_events':events,
            'not_checked':['burned-in subtitles/logos','native source detail','story and emotion',
                           'caption meaning/reading speed','all flash thresholds','VFX edge stability',
                           'listening experience','permissions for publication'],
            'file_sha256':sha(path),'probe':m}
    write_json(out,result)
    return result

def analyze_audio(path: Path, output: Path, fps: str) -> dict:
    try:
        import numpy as np
        import librosa
    except ImportError as e:
        raise MadError('Install requirements-analysis.txt for music analysis') from e
    meta=probe(path)
    if media_duration(meta)>1800:
        raise MadError('Analyze a selected <=30 minute music workfile, not an unbounded recording')
    sr=22050; hop=256
    p=run(['ffmpeg','-v','error','-i',str(path),'-vn','-ac','1','-ar',str(sr),'-f','f32le','-'],binary=True)
    y=np.frombuffer(p.stdout,dtype='<f4').copy()
    if not y.size:
        raise MadError('Empty audio')
    onset=librosa.onset.onset_strength(y=y,sr=sr,hop_length=hop)
    tempo,beats=librosa.beat.beat_track(onset_envelope=onset,sr=sr,hop_length=hop,units='time')
    onset_times=librosa.onset.onset_detect(onset_envelope=onset,sr=sr,hop_length=hop,units='time')
    rms=librosa.feature.rms(y=y,hop_length=hop)[0]
    output.mkdir(parents=True,exist_ok=True)
    beatrows=[{'seconds':f'{float(b):.6f}','frame':nearest_frame(str(float(b)),fps),'kind':'beat_proposal','review':'pending'} for b in beats]
    csv_write(output/'beats.csv',['seconds','frame','kind','review'],beatrows)
    csv_write(output/'onsets.csv',['seconds','frame','kind','review'],[
        {'seconds':f'{float(b):.6f}','frame':nearest_frame(str(float(b)),fps),'kind':'onset_proposal','review':'pending'} for b in onset_times])
    csv_write(output/'energy.csv',['seconds','rms'],[
        {'seconds':f'{i*hop/sr:.6f}','rms':f'{float(r):.8f}'} for i,r in enumerate(rms)])
    result={'audio_sha256':sha(path),'duration_seconds':len(y)/sr,'fps':fps,
            'estimated_bpm':float(np.asarray(tempo).reshape(-1)[0]),'beat_proposals':len(beatrows),
            'status':'unreviewed_proposals','limitations':['not downbeats','not phrase boundaries','tempo octave errors possible',
            'RMS is not emotion','re-run on the locked edited music master after any structural music edit']}
    write_json(output/'analysis.json',result)
    return result

def scenes(path: Path, out: Path, threshold: float) -> dict:
    if not 0<threshold<1:
        raise MadError('scene threshold must be between 0 and 1')
    p=ff(['-i',str(path),'-an','-vf',f"select='gt(scene,{threshold})',showinfo",'-fps_mode','vfr','-f','null','-'],level='info')
    starts=sorted({0.0}|{float(x) for x in re.findall(r'pts_time:([0-9.]+)',p.stderr)})
    end=media_duration(probe(path),'video')
    rows=[{'candidate_id':f'C{i+1:05d}','source_in':f'{lo:.6f}','source_out':f'{hi:.6f}',
           'duration_seconds':f'{hi-lo:.6f}','review':'pending'} for i,(lo,hi) in enumerate(zip(starts,starts[1:]+[end])) if hi>lo]
    csv_write(out,['candidate_id','source_in','source_out','duration_seconds','review'],rows)
    return {'candidates':len(rows),'method':'FFmpeg scene-score proposals; flashes/pans can create false boundaries'}

def contact_times(duration: float, interval: float, limit: int, rate: Fraction) -> list[float]:
    """Do not seek into the tail after the last frame's presentation timestamp."""
    if not math.isfinite(duration) or duration <= 0:
        return [0.0]
    margin=1/float(rate) if rate>0 else 0.1
    last=max(0.0,duration-margin)
    return [i*interval for i in range(min(limit,max(1,math.floor(last/interval)+1)))]

def contact(path: Path, output: Path, interval: float, limit: int) -> dict:
    try:
        from PIL import Image, ImageDraw
    except ImportError as e:
        raise MadError('Install Pillow for contact sheets') from e
    if interval<=0 or limit<1 or limit>500:
        raise MadError('interval >0, 1<=limit<=500 required')
    meta=probe(path)
    duration=media_duration(meta,'video')
    v=next((s for s in meta.get('streams',[]) if s.get('codec_type')=='video'),{})
    rate=frac(v.get('avg_frame_rate','0'))
    times=contact_times(duration,interval,limit,rate)
    output.mkdir(parents=True,exist_ok=True)
    entries=[]; thumbs=[]
    for i,t in enumerate(times):
        frame=output/f'frame_{i:04d}.png'
        ff(['-ss',f'{t:.6f}','-i',str(path),'-map','0:v:0','-frames:v','1',
            '-vf','scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2,format=rgb24',str(frame)])
        if not frame.is_file():
            raise MadError(f'No frame at {t:.6f}s; inspect source timing and retry a smaller interval/range')
        entries.append({'index':i,'seconds':t,'path':frame.name})
        thumbs.append(frame)
    for page in range(0,len(thumbs),20):
        chunk=thumbs[page:page+20]
        im=Image.new('RGB',(480*4,300*math.ceil(len(chunk)/4)),(24,24,24)); draw=ImageDraw.Draw(im)
        for j,p in enumerate(chunk):
            x=(j%4)*480;y=(j//4)*300
            with Image.open(p) as pic: im.paste(pic,(x,y))
            draw.text((x+8,y+276),f'{times[page+j]:.3f}s',fill='white')
        im.save(output/f'contact_{page//20+1:03d}.jpg',quality=90)
    write_json(output/'index.json',{'source':str(path.resolve()),'samples':entries,
               'warning':'Sparse samples cannot certify absence of burned-in subtitles or logos in selected intervals'})
    return {'sampled_frames':len(times),'output':str(output)}

# Explicit HTTPS direct downloads only. No cookies, DRM, login bypass or search scraping.
def check_public_https(url: str) -> None:
    u=urllib.parse.urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password:
        raise MadError('An HTTPS media URL without embedded credentials is required')
    try:
        addresses=socket.getaddrinfo(u.hostname,u.port or 443,type=socket.SOCK_STREAM)
    except OSError as e:
        raise MadError(f'DNS lookup failed: {e}') from e
    for address in addresses:
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise MadError('Private/local-network download targets are not permitted')

class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        check_public_https(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(manifest: Path, output: Path, max_mb: int) -> dict:
    m=read_json(manifest)
    for field in ['url','provenance','usage_basis']:
        if not isinstance(m.get(field),str) or not m[field].strip():
            raise MadError('Download manifest requires '+field)
    if m.get('download_authorized') is not True:
        raise MadError('Manifest must record download_authorized=true; this is a user attestation, not a legal verification')
    if m.get('kind') not in ('audio','video','precomp'):
        raise MadError('Download kind must be audio, video or precomp')
    if m.get('expected_sha256') and (not isinstance(m['expected_sha256'],str) or not re.fullmatch(r'[a-fA-F0-9]{64}',m['expected_sha256'])):
        raise MadError('expected_sha256 must be a trusted 64-character SHA256, or omitted')
    if max_mb<=0 or output.exists() or output.with_suffix(output.suffix+'.source.json').exists():
        raise MadError('Positive size limit and a new output path are required')
    check_public_https(m['url'])
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,tmpname=tempfile.mkstemp(prefix='mad-download-',suffix='.part',dir=output.parent)
    os.close(fd); tmp=Path(tmpname); count=0
    try:
        opener=urllib.request.build_opener(PublicRedirect())
        with opener.open(urllib.request.Request(m['url'],headers={'User-Agent':f'make-mad/{VERSION}'}),timeout=30) as r,tmp.open('wb') as f:
            if int(r.headers.get('Content-Length','0'))>max_mb*1024*1024:
                raise MadError('Download exceeds size limit')
            while True:
                data=r.read(1024*1024)
                if not data: break
                count+=len(data)
                if count>max_mb*1024*1024: raise MadError('Download exceeds size limit')
                f.write(data)
        if m.get('expected_sha256') and sha(tmp).lower()!=m['expected_sha256'].lower():
            raise MadError('Downloaded SHA256 mismatch')
        meta=probe(tmp)
        kind='video' if m['kind']=='precomp' else m['kind']
        stream=next((x for x in meta.get('streams',[]) if x.get('codec_type')==kind
                     and not x.get('disposition',{}).get('attached_pic')),None)
        duration=media_duration(meta,kind)
        if not stream or not math.isfinite(duration) or duration<=0:
            raise MadError(f'Downloaded file has no usable {kind} stream/duration')
        if kind=='video':
            if stream.get('width',0)<1920 or stream.get('height',0)<1080:
                raise MadError('Downloaded video fails the >=1920x1080 raster gate')
        os.replace(tmp,output)
        result={'output':str(output.resolve()),'sha256':sha(output),'bytes':count,
                'source_manifest':m,'clean_source_status':'unreviewed','hash_independently_verified':bool(m.get('expected_sha256')),'probe':meta}
        write_json(output.with_suffix(output.suffix+'.source.json'),result)
        return result
    finally:
        tmp.unlink(missing_ok=True)

def cutlist(tpath: Path, out: Path) -> dict:
    t=read_json(tpath); fps=t['fps']; assets={a['id']:a for a in t['assets']}
    check=validate_data(t,tpath.parent,inspect=False)
    if not check['ok']: raise MadError(json.dumps(check,ensure_ascii=False))
    rows=[]
    for s in t['shots']:
        rows.append({'shot_id':s['id'],'asset_id':s['asset_id'],'path':assets[s['asset_id']]['path'],
            'fps':fps,'timeline_in_frame':s['start_frame'],'timeline_out_frame_exclusive':s['start_frame']+s['duration_frames'],
            'source_in_seconds':s['source_in'],'source_out_seconds_exclusive':secstr(frac(s['source_in'])+frame_seconds(s['duration_frames'],fps)*frac(s['speed'])),
            'speed':s['speed'],'transition_in':s['transition_in']['type'],'transition_frames':s['transition_in']['duration_frames'],
            'narrative_function':s['narrative_function'],'sync_anchor':s['sync_anchor']})
    fields=['shot_id','asset_id','path','fps','timeline_in_frame','timeline_out_frame_exclusive',
            'source_in_seconds','source_out_seconds_exclusive','speed','transition_in','transition_frames','narrative_function','sync_anchor']
    csv_write(out,fields,rows)
    return {'rows':len(rows),'format':'annotated conform CSV; NOT a native NLE project'}

def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version=VERSION)
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('doctor');s.add_argument('--out',type=Path)
    s=sub.add_parser('init');s.add_argument('directory',type=Path);s.add_argument('--name',default='Untitled MAD');s.add_argument('--fps',default='24000/1001')
    s=sub.add_parser('probe');s.add_argument('input',type=Path);s.add_argument('--out',type=Path,required=True)
    s=sub.add_parser('validate');s.add_argument('timeline',type=Path);s.add_argument('--final',action='store_true');s.add_argument('--out',type=Path)
    s=sub.add_parser('render');s.add_argument('timeline',type=Path);s.add_argument('--out',type=Path,required=True);s.add_argument('--profile',choices=['draft','delivery'],default='draft');s.add_argument('--normalize',action='store_true');s.add_argument('--overwrite',action='store_true')
    s=sub.add_parser('qa');s.add_argument('input',type=Path);s.add_argument('--timeline',type=Path);s.add_argument('--out',type=Path,required=True);s.add_argument('--scan',action='store_true')
    s=sub.add_parser('analyze-audio');s.add_argument('input',type=Path);s.add_argument('--out',type=Path,required=True);s.add_argument('--fps',default='24000/1001')
    s=sub.add_parser('scenes');s.add_argument('input',type=Path);s.add_argument('--out',type=Path,required=True);s.add_argument('--threshold',type=float,default=0.35)
    s=sub.add_parser('contact');s.add_argument('input',type=Path);s.add_argument('--out',type=Path,required=True);s.add_argument('--interval',type=float,default=30);s.add_argument('--limit',type=int,default=60)
    s=sub.add_parser('fetch');s.add_argument('manifest',type=Path);s.add_argument('--out',type=Path,required=True);s.add_argument('--max-mb',type=int,default=8192)
    s=sub.add_parser('cutlist');s.add_argument('timeline',type=Path);s.add_argument('--out',type=Path,required=True)
    return p

def main(argv: list[str] | None = None) -> int:
    a=parser().parse_args(argv)
    try:
        if a.command=='doctor': result=doctor()
        elif a.command=='init': result=init_project(a.directory,a.name,a.fps)
        elif a.command=='probe': result=probe(a.input)
        elif a.command=='validate': result=validate_data(read_json(a.timeline),a.timeline.parent,final=a.final)
        elif a.command=='render': result=render(a.timeline.resolve(),a.out.resolve(),draft=a.profile=='draft',normalize=a.normalize,overwrite=a.overwrite)
        elif a.command=='qa': result=qa(a.input,a.timeline,a.out,a.scan)
        elif a.command=='analyze-audio': result=analyze_audio(a.input,a.out,a.fps)
        elif a.command=='scenes': result=scenes(a.input,a.out,a.threshold)
        elif a.command=='contact': result=contact(a.input,a.out,a.interval,a.limit)
        elif a.command=='fetch': result=fetch(a.manifest,a.out,a.max_mb)
        elif a.command=='cutlist': result=cutlist(a.timeline,a.out)
        else: raise MadError('Unsupported command')
        if a.command in ('doctor','probe','validate') and getattr(a,'out',None): write_json(a.out,result)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 2 if result.get('ok') is False or result.get('automated_status')=='fail' else 0
    except (MadError, OSError, ValueError, KeyError, StopIteration) as e:
        print(f'make-mad: {e}',file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
