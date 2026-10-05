"""Per-shot FX compositor for the MAD (FFmpeg-based, frame-exact).

A cut spec (python module) defines SHOTS (ordered), END, and optional per-shot fx.
Each shot is rendered to an intermediate clip with exactly the planned frame count
(+ head handle for dissolves), then all clips are joined (cut / xfade dissolve),
then a light layer (screen blend) and a graphics layer (alpha overlay) are composited.

Motion uses the `perspective` filter (float corners, cubic interpolation) so zooms,
drifts, punches and shakes are sub-pixel smooth instead of integer-stepped.
"""
import glob, os, subprocess, json, hashlib, sys
from fractions import Fraction as F
from concurrent.futures import ThreadPoolExecutor

FPS = F(24000, 1001)
FF = float(FPS)
W, H = 1920, 1080
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grades import GRADES


# ---- source resolution (set by the caller; keys are whatever the cut spec uses, e.g. episode ids) ----
SOURCES = {}
def set_sources(mapping):
    """mapping: key -> media path. A key that is already an existing path resolves to itself."""
    SOURCES.update(mapping)
def epfile(ep):
    if ep == 'BLK':
        return _black()
    if ep in SOURCES:
        return SOURCES[ep]
    if os.path.exists(str(ep)):
        return str(ep)
    raise KeyError(f'unknown source {ep!r}; call set_sources()')
def _black():
    import tempfile, subprocess
    p = os.path.join(tempfile.gettempdir(), 'fxkit_black_1920.png')
    if not os.path.exists(p):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1920x1080', '-frames:v', '1', p], check=True)
    return p

def fr(t):
    return int(round(F(str(round(t, 6))) * FPS))

# ---------------------------------------------------------------- motion expr
def motion_exprs(fx, n, t0_song):
    """Perspective corner expressions. T = in/FPS (seconds into the clip incl. head).
    fx: z0,z1 push; cx0,cx1,cy0,cy1 focus drift; ease io|o|i|lin;
        punch [(song_t, amount, frames)]; settle (amount, frames); shake [(song_t, px, frames, hz)];
        jitter px; rot0, rot1 degrees."""
    T = f'(in/{FF:.6f})'
    D = max(n / FF, 1e-3)
    u = f'min(max({T}/{D:.6f},0),1)'
    ease = fx.get('ease', 'io')
    e = {'io': f'({u}*{u}*(3-2*{u}))', 'o': f'(1-(1-{u})*(1-{u}))', 'i': f'({u}*{u})'}.get(ease, u)
    z0, z1 = fx.get('z0', 1.0), fx.get('z1', fx.get('z0', 1.0))
    Z = f'({z0}+({z1}-{z0})*{e})'
    for (pt, amt, frames) in fx.get('punch', []):
        s = pt - t0_song
        tau = frames / FF / 3.0
        Z += f'*(1+{amt}*gte({T},{s:.4f})*exp(-({T}-{s:.4f})/{tau:.4f}))'
    if fx.get('settle'):
        amt, frames = fx['settle']
        tau = frames / FF / 3.0
        Z += f'*(1+{amt}*exp(-{T}/{tau:.4f}))'
    Z = f'({Z})'  # wrap: punch/settle factors must bind before the division below
    cx0, cy0 = fx.get('cx0', 0.5), fx.get('cy0', 0.5)
    cx1, cy1 = fx.get('cx1', cx0), fx.get('cy1', cy0)
    cx = f'({cx0}+({cx1}-{cx0})*{e})'
    cy = f'({cy0}+({cy1}-{cy0})*{e})'
    dx, dy = '0', '0'
    for k, (st, px, frames, hz) in enumerate(fx.get('shake', [])):
        s = st - t0_song
        tau = frames / FF / 2.5
        env = f'gte({T},{s:.4f})*exp(-({T}-{s:.4f})/{tau:.4f})'
        dx += f'+{px}*{env}*sin(2*PI*{hz}*({T}-{s:.4f})+{0.7*k+0.3:.2f})'
        dy += f'+{px*0.7:.2f}*{env}*sin(2*PI*{hz*1.37:.2f}*({T}-{s:.4f})+{1.9+0.5*k:.2f})'
    if fx.get('jitter'):
        j = fx['jitter']
        dx += f'+{j}*sin(2*PI*7.3*{T})+{j*0.6:.2f}*sin(2*PI*13.1*{T}+1.1)'
        dy += f'+{j*0.8:.2f}*sin(2*PI*9.7*{T}+0.4)+{j*0.5:.2f}*sin(2*PI*15.3*{T}+2.2)'
    r0, r1 = fx.get('rot0', 0.0), fx.get('rot1', fx.get('rot0', 0.0))
    th = f'(({r0}+({r1}-{r0})*{e})*PI/180)'
    hw, hh = f'({W/2}/{Z})', f'({H/2}/{Z})'
    # keep the sampling window inside the source (no edge smear); rotation gets extra margin
    m = 1.0 + (abs(max(abs(r0), abs(r1))) * 0.012)
    X = f'clip({cx}*{W}+({dx}),{W/2}*{m}/{Z},{W}-{W/2}*{m}/{Z})'
    Y = f'clip({cy}*{H}+({dy}),{H/2}*{m}/{Z},{H}-{H/2}*{m}/{Z})'
    def corner(sx, sy):
        ox, oy = f'({sx}*{hw})', f'({sy}*{hh})'
        if r0 == 0 and r1 == 0:
            return f'{X}+{ox}', f'{Y}+{oy}'
        return (f'{X}+{ox}*cos({th})-{oy}*sin({th})', f'{Y}+{ox}*sin({th})+{oy}*cos({th})')
    return [corner(-1, -1), corner(1, -1), corner(-1, 1), corner(1, 1)]

def needs_motion(fx):
    return any(k in fx for k in ('z0', 'z1', 'punch', 'shake', 'jitter', 'settle', 'rot0', 'cx0', 'cy0'))

# ---------------------------------------------------------------- per shot
def frame_window(t, k=0):
    a = t + k / FF
    return f'between(t,{a-0.002:.4f},{a+1/FF-0.004:.4f})'

def shot_filter(s, n, head):
    fx = s.get('fx', {})
    t0_song = s['t'] - head / FF          # song time of clip frame 0
    chain = []
    sp = s.get('speed', 1)
    ramp = fx.get('ramp')                  # (src_rel_a, src_rel_b, factor) slow-mo window
    if ramp:
        a, b, k = ramp
        chain.append(f"setpts='(if(lt(T,{a}),T,if(lt(T,{b}),{a}+(T-{a})/{k},{a}+({b}-{a})/{k}+(T-{b}))))/TB'")
    elif sp != 1:
        chain.append(f'setpts=(PTS-STARTPTS)/{sp}')
    else:
        chain.append('setpts=PTS-STARTPTS')
    chain.append(f'fps={FPS.numerator}/{FPS.denominator}')
    if fx.get('tmix'):  # temporal average to tame source flicker (photosensitivity)
        chain.append(f"tmix=frames={fx['tmix']}")
    if head:  # dissolve handle = frozen first frame (never pull frames from across a source cut)
        chain.append(f'tpad=start={head}:start_mode=clone')
    chain.append(f'scale={W}:{H}:flags=lanczos')
    if s.get('grade'):
        chain.append(GRADES[s['grade']])
    if fx.get('grade_extra'):
        chain.append(fx['grade_extra'])
    if needs_motion(fx):
        c = motion_exprs(fx, n + head, t0_song)
        args = ':'.join(f"{k}='{v}'" for k, v in zip(['x0', 'y0', 'x1', 'y1', 'x2', 'y2', 'x3', 'y3'], [e for p in c for e in p]))
        chain.append(f'perspective={args}:interpolation=cubic:sense=source:eval=frame')
    parts = [f"[0:v]{','.join(chain)}[m]"]
    cur = 'm'
    glow = fx.get('glow')
    if glow:
        strength, sigma, thr = glow if isinstance(glow, (list, tuple)) else (glow, 28, 0.6)
        parts.append(f"[{cur}]format=gbrp,split[ga][gb];[gb]curves=all='0/0 {thr}/0 1/1',gblur=sigma={sigma}[gc];[ga][gc]blend=all_mode=screen:all_opacity={strength}[g]")
        cur = 'g'
    post = []
    for (st, frames, radius, ang) in fx.get('dblur', []):
        s0 = st - t0_song
        for k in range(frames):
            r = max(2, int(radius * (1 - k / frames)))
            post.append(f"dblur=angle={ang}:radius={r}:enable='{frame_window(s0, k)}'")
    for (st, en, amt) in fx.get('rgb', []):
        a, b = st - t0_song, en - t0_song
        post.append(f"rgbashift=rh=-{amt}:bh={amt}:rv={max(1,amt//3)}:bv=-{max(1,amt//3)}:enable='between(t,{a:.4f},{b:.4f})'")
    for (st, en, amt) in fx.get('glitch', []):
        a, b = st - t0_song, en - t0_song
        post.append(f"rgbashift=rh={amt}:gh=-{amt//2}:bh=-{amt}:edge=wrap:enable='between(t,{a:.4f},{b:.4f})*lt(mod(n,4),2)'")
        post.append(f"rgbashift=rh=-{amt*2}:bh={amt}:edge=wrap:enable='between(t,{a:.4f},{b:.4f})*eq(mod(n,4),3)'")
    pulses = fx.get('flash', [])
    if pulses:
        terms = '+'.join(f'{amp}*gte(t,{st - t0_song:.4f})*exp(-(t-{st - t0_song:.4f})/{dec:.4f})' for (st, amp, dec) in pulses)
        post.append(f"eq=brightness='min({terms},0.85)':contrast='1-0.35*min({terms},1)':eval=frame")
    if fx.get('fade_lum'):  # (song_t_start, song_t_end, from, to) brightness ramp e.g. dimming
        a, b, v0, v1 = fx['fade_lum']
        a, b = a - t0_song, b - t0_song
        post.append(f"eq=brightness='{v0}+({v1}-{v0})*min(max((t-{a:.4f})/{b-a:.4f},0),1)':eval=frame")
    post.append('format=yuv420p')
    hf = fx.get('head_fade')
    if hf:
        post.append(f'fade=t=in:st={head/FF:.4f}:d={hf[1]/FF:.4f}:color={hf[0]}')
    tf = fx.get('tail_fade')
    if tf:
        post.append(f'fade=t=out:st={(head + n - tf[1])/FF:.4f}:d={tf[1]/FF:.4f}:color={tf[0]}')
    lb = fx.get('letterbox')
    if lb:
        hb = 132
        if lb in ('in', 'out'):
            for k in range(6):
                f = (k + 1) / 6 if lb == 'in' else 1 - k / 6
                hk = max(1, int(hb * f))
                t = head / FF if lb == 'in' else (head + n - 6) / FF
                post.append(f"drawbox=x=0:y=0:w={W}:h={hk}:color=black:t=fill:enable='{frame_window(t, k)}'")
                post.append(f"drawbox=x=0:y={H-hk}:w={W}:h={hk}:color=black:t=fill:enable='{frame_window(t, k)}'")
            if lb == 'in':
                a = (head + 6) / FF
                en = f"gte(t,{a-0.002:.4f})"
            else:
                a = (head + n - 6) / FF
                en = f"lt(t,{a-0.002:.4f})"
            post.append(f"drawbox=x=0:y=0:w={W}:h={hb}:color=black:t=fill:enable='{en}'")
            post.append(f"drawbox=x=0:y={H-hb}:w={W}:h={hb}:color=black:t=fill:enable='{en}'")
        else:
            post.append(f'drawbox=x=0:y=0:w={W}:h={hb}:color=black:t=fill,drawbox=x=0:y={H-hb}:w={W}:h={hb}:color=black:t=fill')
    grain = fx.get('grain', s.get('grain', 0))
    if grain:
        post.append(f'noise=alls={grain}:allf=t')
    ink = fx.get('ink_in')   # (prev_frame_png, mask_pattern, frames)
    if ink:
        prev, pattern, nf = ink
        parts.append(f"[{cur}]{','.join(post)}[pre]")
        parts.append(f"[1:v]scale={W}:{H},format=gbrp[pv];[2:v]scale={W}:{H},format=gray,negate,tpad=stop={max(0,n+head-nf)}:stop_mode=add:color=black[mk];[pv][mk]alphamerge[pa];[pre]format=gbrp[pb];[pb][pa]overlay=0:0:shortest=0:eof_action=pass,format=yuv420p[out]")
        return ';'.join(parts)
    parts.append(f"[{cur}]{','.join(post)}[out]")
    return ';'.join(parts)

def render_shot(s, n, head, out, preview=False):
    sp = s.get('speed', 1)
    fx = s.get('fx', {})
    src_in = float(s['src'])
    need = n / FF * sp + 0.6
    if s['ep'] == 'BLK':
        inargs = ['-loop', '1', '-framerate', f'{FPS.numerator}/{FPS.denominator}', '-t', f'{(n+head)/FF+0.5:.3f}', '-i', epfile('BLK')]
    else:
        inargs = ['-ss', f'{max(0, src_in):.4f}', '-t', f'{need:.3f}', '-i', epfile(s['ep'])]
    graph = shot_filter(s, n, head)
    if fx.get('ink_in'):
        prev, pattern, nf = fx['ink_in']
        inargs += ['-loop', '1', '-framerate', f'{FPS.numerator}/{FPS.denominator}', '-t', f'{(n+head)/FF+0.5:.3f}', '-i', prev,
                   '-framerate', f'{FPS.numerator}/{FPS.denominator}', '-i', pattern]
    if preview:
        graph += ';[out]scale=960:540[o2]'
        mp = '[o2]'
    else:
        mp = '[out]'
    enc = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18' if preview else '14', '-pix_fmt', 'yuv420p', '-threads', '3']
    cmd = ['ffmpeg', '-v', 'error', '-y'] + inargs + ['-filter_complex', graph, '-map', mp, '-an', '-frames:v', str(n + head),
           '-r', f'{FPS.numerator}/{FPS.denominator}'] + enc + [out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{s['id']}: {r.stderr[-1500:]}\nGRAPH: {graph[:4000]}")
    c = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', out], capture_output=True, text=True).stdout.strip()
    if int(c or 0) != n + head:
        raise RuntimeError(f"{s['id']}: frames {c} != {n+head}")
    return out

def plan(shots, end):
    t0 = shots[0]['t']
    out = []
    for i, s in enumerate(shots):
        a = fr(s['t'] - t0)
        b = fr((shots[i + 1]['t'] if i + 1 < len(shots) else end) - t0)
        j = s.get('join', ('cut', 0))
        head = j[1] if j[0] == 'dissolve' else 0
        out.append((s, a, b - a, head))
    return out

def _shot_src():
    """cache key covers only the per-shot render code (everything above assemble), so assembly tweaks don't re-render all shots"""
    src = open(__file__).read()
    return src[:src.index('\ndef assemble(')]

def key(s, n, head, preview):
    src_stamp = None
    if os.path.exists(str(s.get('ep'))):   # precomp source (e.g. an ae.py hero shot): re-render when the file changes
        st = os.stat(s['ep']); src_stamp = (st.st_size, int(st.st_mtime))
    return hashlib.sha1(json.dumps([s, n, head, preview, GRADES.get(s.get('grade'), ''), _shot_src(), src_stamp], sort_keys=True, default=str).encode()).hexdigest()[:12]

def render_all(shots, end, workdir, preview=False, jobs=4, only=None):
    os.makedirs(workdir, exist_ok=True)
    P = plan(shots, end)
    tasks = [(s, n, head, f"{workdir}/{s['id']}_{key(s, n, head, preview)}.mp4") for (s, a, n, head) in P]
    if only:
        tasks = [t for t in tasks if t[0]['id'] in only]
    def job(t):
        s, n, head, out = t
        if not os.path.exists(out):
            render_shot(s, n, head, out + '.tmp.mp4', preview)
            os.replace(out + '.tmp.mp4', out)
        return out
    with ThreadPoolExecutor(jobs) as ex:
        outs = list(ex.map(job, tasks))
    return P, outs

def assemble(P, outs, dest, light=None, gfx=None, preview=False, crf=21, maxrate='8M', clean_dest=None, preset='veryfast'):
    """concat/xfade all shots, screen the light layer, overlay gfx. clean_dest: also write the text-free version from the
    same decode/filter pass (split before the gfx overlay) instead of a second full assembly."""
    w, h = (960, 540) if preview else (W, H)
    inputs, g = [], []
    for i, o in enumerate(outs):
        inputs += ['-i', o]
        g.append(f'[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[v{i}]')
    cur, acc = 'v0', P[0][2]
    for i in range(1, len(P)):
        s, a, n, head = P[i]
        j = s.get('join', ('cut', 0))
        nxt = f'j{i}'
        if j[0] == 'dissolve':
            off = (acc - head - 0.5) / FF   # half-frame early: avoids pts rounding pushing the transition (and everything after) one frame late
            g.append(f"[{cur}][v{i}]xfade=transition={j[2] if len(j) > 2 else 'fade'}:duration={head/FF:.6f}:offset={off:.6f}[{nxt}]")
        else:
            g.append(f'[{cur}][v{i}]concat=n=2:v=1:a=0[{nxt}]')
        acc += n
        cur = nxt
    k = len(outs)
    if light:
        inputs += ['-i', light]
        g.append(f'[{k}:v]scale={w}:{h},format=gbrp[L];[{cur}]format=gbrp[B];[B][L]blend=all_mode=screen[lb];[lb]format=yuv420p[lt]')
        cur = 'lt'; k += 1
    clean = None
    if clean_dest:
        g.append(f'[{cur}]split[pre][cl]'); cur, clean = 'pre', 'cl'
    if gfx:
        inputs += ['-i', gfx]
        g.append(f'[{k}:v]scale={w}:{h}[G];[{cur}][G]overlay=0:0:format=auto[gt]')
        cur = 'gt'; k += 1
    enc = ['-frames:v', str(acc), '-r', f'{FPS.numerator}/{FPS.denominator}', '-c:v', 'libx264',
           '-preset', preset or 'veryfast',
           '-crf', '20' if preview else str(crf), '-maxrate', maxrate, '-bufsize', f'{2 * int(maxrate.rstrip("M"))}M', '-x264-params', 'aq-mode=3',  # temporal grain is incompressible: cap the rate (CRF14 alone gave 75 Mbps)
           '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-an']
    cmd = ['ffmpeg', '-v', 'error', '-y'] + inputs + ['-filter_complex', ';'.join(g), '-map', f'[{cur}]'] + enc + [dest]
    if clean:
        cmd += ['-map', f'[{clean}]'] + enc + [clean_dest]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-3000:])
    return acc
