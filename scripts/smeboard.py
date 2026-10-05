"""start/mid/end frames of a range of detected shots (from shots.csv), 3 shots per row, labelled idx/source time/duration.
usage: EPINDEX=<project>/analysis/epindex python smeboard.py E01 436 511 out.jpg"""
import sys, csv, cv2, numpy as np
ep, i0, i1, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
import os
base = os.environ.get('EPINDEX', 'analysis/epindex')   # <project>/analysis/epindex: E01.mp4 proxy + E01/shots.csv (analyze_mad.py)
rows = [r for r in csv.DictReader(open(f'{base}/{ep}/shots.csv')) if i0 <= int(r['idx']) <= i1]
cap = cv2.VideoCapture(f'{base}/{ep}.mp4')
TW, TH = 256, 144
def grab(t):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, f = cap.read()
    return cv2.resize(f, (TW, TH)) if ok else np.zeros((TH, TW, 3), np.uint8)
tiles = []
for r in rows:
    a, b = float(r['start_s']), float(r['end_s']); d = b - a
    ts = [a + min(0.04, d / 4), (a + b) / 2, b - min(0.06, d / 4)]
    im = np.hstack([grab(t) for t in ts])
    m, s = divmod(a, 60)
    cv2.rectangle(im, (0, 0), (TW * 3, 16), (0, 0, 0), -1)
    cv2.putText(im, f"#{r['idx']} {int(m)}:{s:05.2f} ({a:.2f}) {d:.2f}s mot{float(r['motion']):.0f}", (4, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    tiles.append(cv2.copyMakeBorder(im, 0, 4, 0, 6, cv2.BORDER_CONSTANT, value=(40, 40, 40)))
while len(tiles) % 3:
    tiles.append(np.zeros_like(tiles[0]))
img = np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)])
cv2.imwrite(out, img, [cv2.IMWRITE_JPEG_QUALITY, 82]); print(out, img.shape)
