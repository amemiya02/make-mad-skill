"""run the cut guard directly on a build module's SHOTS: guard_spec.py edit/build_v7.py [ID,ID]
reports any hard cut inside a shot's source range (incl. speed) — each one is a stray-frame bug."""
import sys, importlib.util
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import fx, cutguard
spec = importlib.util.spec_from_file_location('b', sys.argv[1]); b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
only = set(sys.argv[2].split(',')) if len(sys.argv) > 2 else None
bad = 0
for (s, a, n, head) in fx.plan(b.SHOTS, b.END):
    if s['ep'] == 'BLK' or str(s['ep']).startswith('/') or (only and s['id'] not in only):
        continue
    sp = s.get('speed', 1)
    src0, src1 = s['src'], s['src'] + n / fx.FF * sp
    cs, _ = cutguard.cuts_in(s['ep'], src0, src1, pad=0.1)
    # the shot holds the source frames g0, g0+sp/FF, … (g0 = first frame with pts >= src0, as an accurate -ss returns):
    # a cut at c leaks the frame before it iff c > g0 + ½ frame, and leaks the cut frame iff c < the last frame + ½ frame
    g0 = __import__('math').ceil(src0 * fx.FF - 0.05) / fx.FF
    last = g0 + (n - 1) / fx.FF * sp
    inner = [round(c, 3) for c in cs if g0 + 0.5 / fx.FF < c < last + 0.5 / fx.FF]
    if inner:
        bad += 1; print(f"CUT  {s['id']:5s} ep{s['ep']} src {src0:.3f}-{src1:.3f} -> cuts at {inner}", flush=True)
print('shots with inner cuts:', bad)
