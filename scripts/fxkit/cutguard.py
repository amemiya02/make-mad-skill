"""Frame-accurate cut guard: find hard cuts INSIDE each shot's source range.
usage: cutguard.py edl.csv --sources sources.json   (EDL columns: id,song_t,ep,src_in,speed; last row id=END)
A hard cut = frame diff that is both large in absolute terms and a spike vs local median.
"""
import csv,sys,glob,math,subprocess,numpy as np
FPS=24000/1001; W,H=96,54
import os,sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fx import epfile, set_sources
def frames(ep,a,b):
    raw=subprocess.run(['ffmpeg','-v','error','-ss',f'{a:.3f}','-i',epfile(ep),'-t',f'{b-a:.3f}','-vf',f'scale={W}:{H},format=gray','-f','rawvideo','-'],capture_output=True).stdout
    n=len(raw)//(W*H); return np.frombuffer(raw[:n*W*H],np.uint8).reshape(n,H,W).astype(np.float32)
def cuts_in(ep,a,b,pad=0.25):
    f=frames(ep,max(0,a-pad),b+pad)
    # an accurate -ss returns the first frame with pts >= a: snap t0 onto the source frame grid, or every cut time comes out
    # up to one frame early and a cut just inside a shot's tail is missed (v8: two 1-frame strays slipped past the guard)
    t0=math.ceil(max(0,a-pad)*FPS-0.05)/FPS   # 0.05 frame: mkv timestamps are ms-rounded (and may carry a start offset)
    if len(f)<3: return [],t0
    d=np.abs(np.diff(f,axis=0)).mean(axis=(1,2))
    # histogram distance for robustness
    hs=[np.histogram(x,bins=16,range=(0,255))[0]/x.size for x in f]
    hd=np.array([np.abs(hs[i+1]-hs[i]).sum() for i in range(len(hs)-1)])
    out=[]
    for i in range(len(d)):
        lo=max(0,i-6); loc=np.median(np.r_[d[lo:i],d[i+1:i+7]]) if len(d)>1 else 0
        if (d[i]>18 and d[i]>3.5*max(loc,2)) or (hd[i]>0.55 and d[i]>10):
            out.append(t0+(i+1)/FPS)   # time of first frame of new shot
    return out,t0
if __name__=='__main__':
    if '--sources' in sys.argv:
        import json; set_sources(json.load(open(sys.argv[sys.argv.index('--sources')+1])))
    rows=list(csv.DictReader(open(sys.argv[1])))
    fix='--fix' in sys.argv; outp=sys.argv[sys.argv.index('--fix')+1] if fix else None
    bad=0
    for i,r in enumerate(rows[:-1]):
        if r['ep'] in ('','BLK'): continue
        a=float(r['src_in']); dur=float(rows[i+1]['song_t'])-float(r['song_t']); b=a+dur*float(r.get('speed') or 1)
        cs,_=cuts_in(r['ep'],a,b)
        inside=[c for c in cs if a+0.5/FPS < c < b-0.5/FPS]
        edge=[c for c in cs if abs(c-a)<=0.5/FPS or abs(c-b)<=0.5/FPS]
        if inside:
            bad+=1
            print(f"{r['id']:4} E{r['ep']} [{a:.3f},{b:.3f}] cuts inside at "+', '.join(f'{c:.3f}({(c-a)*FPS:+.0f}f)' for c in inside))
            r['_cuts']=inside
    print('shots with internal cuts:',bad)
