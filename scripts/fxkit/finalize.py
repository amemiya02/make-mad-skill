"""two-pass loudnorm + mux. usage: finalize.py picture.mp4 mix.wav out.mp4 [I] [TP]"""
import sys,json,subprocess
pic,wav,out=sys.argv[1:4]; I=sys.argv[4] if len(sys.argv)>4 else '-14'; TP=sys.argv[5] if len(sys.argv)>5 else '-1.5'
r=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',wav,'-af',f'loudnorm=I={I}:TP={TP}:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True).stderr
d=json.loads(r[r.rfind('{'):r.rfind('}')+1])
af=f"loudnorm=I={I}:TP={TP}:LRA=11:measured_I={d['input_i']}:measured_TP={d['input_tp']}:measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}:offset={d['target_offset']}:linear=true,alimiter=limit=0.80:level=false"
subprocess.run(['ffmpeg','-v','error','-y','-i',pic,'-i',wav,'-map','0:v:0','-map','1:a:0','-dn','-map_metadata','-1','-map_chapters','-1','-c:v','copy','-af',af,'-ar','48000','-c:a','aac','-b:a','320k','-shortest','-movflags','+faststart',out],check=True)
r2=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',out,'-af','loudnorm=print_format=json','-f','null','-'],capture_output=True,text=True).stderr
d2=json.loads(r2[r2.rfind('{'):r2.rfind('}')+1])
print(json.dumps({'pre':{k:d[k] for k in ('input_i','input_tp','input_lra')},'out':{k:d2[k] for k in ('input_i','input_tp','input_lra')}}))
