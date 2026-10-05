"""red-line QA on a render: stray frames near planned cuts, flash rate, vocal-band loss vs original, dialogue/music ratio.
usage: redline.py render.mp4 build_module.py [work_dir_with_stems] --vocals vocals.wav [--offset S]
   --offset: seconds of cold open/prologue before the song starts in render.mp4
   build module must define SHOTS, END, MUSIC, DIALOGUE (see fxkit/README.md)"""
import sys,subprocess,re,importlib.util,numpy as np,json
import os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import fx
args=[a for a in sys.argv[1:] if not a.startswith('--')]
VOC=sys.argv[sys.argv.index('--vocals')+1] if '--vocals' in sys.argv else None
if VOC in args: args.remove(VOC)
OFF=float(sys.argv[sys.argv.index('--offset')+1]) if '--offset' in sys.argv else 0.0
if '--offset' in sys.argv: args.remove(sys.argv[sys.argv.index('--offset')+1])
vid,mod=args[0],args[1]; work=args[2] if len(args)>2 else None
spec=importlib.util.spec_from_file_location('b',mod); b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
FPSf=fx.FF; P=fx.plan(b.SHOTS,b.END)
cuts=[p[1]/FPSf for p in P[1:]]
# 1) per-frame luma + diff
raw=subprocess.run(['ffmpeg','-v','error','-ss',f'{OFF:.4f}','-i',vid,'-vf','scale=96:54,format=gray','-f','rawvideo','-'],capture_output=True).stdout
F=np.frombuffer(raw,np.uint8).reshape(-1,54,96).astype(np.float32); d=np.abs(np.diff(F,axis=0)).mean(axis=(1,2)); y=F.mean(axis=(1,2))
res={'frames':len(F)}
# stray: a hard change within 1..4 frames after/before a planned cut AND the frames between differ from both sides
stray=[]
for c in cuts:
    k=int(round(c*FPSf))
    for j in list(range(k+1,k+5))+list(range(k-4,k)):
        if 0<j<len(d) and d[j-1]>18 and d[j-1]>3.5*max(np.median(d[max(0,j-8):j+8]),2):
            stray.append((round(c,3),j-k))
res['stray_suspects']=stray
off=[]
for (s_,a_,n_,h_) in P[1:]:
    if s_.get('join',('cut',))[0]!='cut' or s_['fx'].get('head_fade') or a_<4 or a_+3>len(d): continue
    w=d[a_-3:a_+3]
    if w.max()<15: continue
    k=int(np.argmax(w))-2
    if k!=0: off.append((s_['id'],k))
res['cut_misalign']=off
# 2) flashes
tr=[(i,v) for i,v in enumerate(np.diff(y)) if abs(v)>=25.5]
ev=[tr[k][0] for k in range(1,len(tr)) if np.sign(tr[k-1][1])!=np.sign(tr[k][1]) and tr[k][0]-tr[k-1][0]<FPSf]
res['max_flash_per_s']=max([sum(1 for j in ev if i-FPSf<j<=i) for i in ev] or [0])
res['flash_windows_ge3']=sorted({round(i/FPSf,1) for i in ev if sum(1 for j in ev if i-FPSf<j<=i)>=3})
# 3) vocal-band loss vs original
import librosa
import tempfile; _t=os.path.join(tempfile.gettempdir(),'redline.wav'); subprocess.run(['ffmpeg','-v','error','-y','-ss',f'{OFF:.4f}','-i',vid,'-vn','-ac','1','-ar','22050',_t],check=True); m,_=librosa.load(_t,sr=22050); o,_=librosa.load(b.MUSIC,sr=22050,duration=len(m)/22050)
n=min(len(m),len(o)); m,o=m[:n],o[:n]
def band(x):
    S=np.abs(librosa.stft(x,n_fft=2048,hop_length=11025)); f=librosa.fft_frequencies(sr=22050,n_fft=2048); bb=(f>300)&(f<3400)
    return 20*np.log10(S[bb].mean(0)+1e-9)
dd=band(m)-band(o); dd-=np.median(dd)
v,_=librosa.load(VOC,sr=22050,duration=n/22050) if VOC else (o,None)
vr=librosa.feature.rms(y=v,frame_length=11025,hop_length=11025)[0]; vdb=20*np.log10(vr+1e-9); vdb-=np.percentile(vdb,99)
loss=[(i*0.5,round(float(x),1)) for i,x in enumerate(dd) if x<-3 and i<len(vdb) and vdb[i]>-25]
res['vocal_loss_while_singing']=loss
# 4) dialogue / music ratio (stems)
if work:
    import soundfile as sf
    mu,sr=sf.read(f'{work}/audio-music.wav'); dl,_=sf.read(f'{work}/audio-dialogue.wav')
    rat=[]
    for (ep,a,bb,t,g,fd) in b.DIALOGUE:
        s0,s1=int(t*sr),int((t+bb-a)*sr); x=dl[s0:s1].mean(1); mm=mu[s0:s1].mean(1)
        fr=x[:len(x)//2400*2400].reshape(-1,2400); e=np.sqrt((fr**2).mean(1)); act=e[e>np.percentile(e,50)]
        rat.append((t,round(20*np.log10(np.sqrt((act**2).mean())+1e-12)-20*np.log10(np.sqrt((mm**2).mean())+1e-12),1)))
    res['dialogue_minus_music_db']=rat
print(json.dumps(res,ensure_ascii=False))
