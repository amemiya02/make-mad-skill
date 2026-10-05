"""first/mid/last frame of every shot of a rendered prototype, labelled. usage: python protoboard.py build.py rendered.mp4 out.jpg [t0-t1]"""
import sys, importlib.util, cv2, numpy as np
import os
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.abspath(sys.argv[1]))]   # fx.py beside this file; the build's own dir
import fx
spec = importlib.util.spec_from_file_location('b', sys.argv[1]); b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
P = fx.plan(b.SHOTS, b.END)
cap = cv2.VideoCapture(sys.argv[2]); N = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
def frame(i):   # seek (a full decode of a 4-minute 1080p render would not fit in memory as thumbnails list anyway)
    cap.set(cv2.CAP_PROP_POS_FRAMES, min(i, N - 1)); ok, f = cap.read()
    return cv2.resize(f, (256, 144)) if ok else np.zeros((144, 256, 3), np.uint8)
lo, hi = (float(x) for x in sys.argv[4].split('-')) if len(sys.argv) > 4 else (-1, 1e9)
tiles = []
for (s, a, n, h) in P:
    if not lo <= s['t'] < hi:
        continue
    im = np.hstack([frame(i) for i in (a, a + n // 2, a + n - 1)])
    cv2.rectangle(im, (0, 0), (768, 16), (0, 0, 0), -1)
    cv2.putText(im, f"{s['id']} t={s['t']:.2f} ep{s['ep']} {s['src']} {n}f{' x%.2f' % s['speed'] if s.get('speed') else ''}", (4, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    tiles.append(cv2.copyMakeBorder(im, 0, 4, 0, 6, cv2.BORDER_CONSTANT, value=(40, 40, 40)))
while len(tiles) % 2: tiles.append(np.zeros_like(tiles[0]))
img = np.vstack([np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)])
cv2.imwrite(sys.argv[3], img, [cv2.IMWRITE_JPEG_QUALITY, 80]); print(sys.argv[3], img.shape)
