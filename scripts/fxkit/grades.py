# Grade presets (ffmpeg filter chains, applied on 1920x1080 yuv/rgb frames)
GRADES={
 # present-day warmth: lifted warmth, gentle S-curve, soft bloom handled separately
 'warm':   "colortemperature=temperature=5600:mix=0.55,eq=contrast=1.05:saturation=1.08:gamma=0.98,curves=all='0/0.02 0.25/0.22 0.75/0.79 1/0.98',vignette=angle=PI/5:mode=forward",
 # Eris training: punchy, crisp, slight teal/orange split
 'eris':   "eq=contrast=1.13:saturation=1.20,colorbalance=rs=-0.04:bs=0.06:rh=0.03:bh=-0.01,huesaturation=saturation=0.12:colors=c+b,curves=all='0/0 0.22/0.17 0.78/0.84 1/1',cas=0.4,vignette=angle=PI/4.6",
 # night / Man-God / basement: cold blue, slightly desaturated
 'night':  "colortemperature=temperature=8200:mix=0.6,eq=contrast=1.06:saturation=0.88:gamma=1.05,colorbalance=bs=0.05:bm=0.03,vignette=angle=PI/5",
 # Man-God white void: high-key, soft, slight cyan
 'void_soft': "eq=contrast=0.97:saturation=0.75,colorbalance=bh=0.03:bm=0.02",  # light-streak intro: keep highlights
 # (v6 fix) source is already near-white: pull mids/highlights down so lines and figures read
 'void':   "eq=contrast=1.06:saturation=0.85,curves=all='0/0 0.35/0.24 0.7/0.55 0.9/0.8 1/0.94',colorbalance=bh=0.03:bm=0.02,vignette=angle=PI/4.8",
 # old man in candlelight: amber, crushed shadows, heavy vignette
 'amber':  "colortemperature=temperature=4300:mix=0.5,eq=contrast=1.10:saturation=0.94:gamma=0.97,curves=all='0/0 0.2/0.14 0.7/0.72 1/0.97',vignette=angle=PI/4.4",
 # the diary's other timeline: memory/record — desaturated, cold, lifted blacks, keep reds
 'diary':  "huesaturation=saturation=-0.55:colors=y+g+c+b+m:strength=1,huesaturation=saturation=-0.15:colors=r,colortemperature=temperature=7200:mix=0.45,curves=all='0/0.045 0.3/0.29 0.7/0.72 1/0.95',eq=contrast=1.06:gamma=1.06,vignette=angle=PI/4.4",
 # after the death: dark night, cool shadows, warm embers survive
 'mourn':  "colortemperature=temperature=7600:mix=0.4,eq=contrast=1.05:saturation=0.92:gamma=1.06,curves=all='0/0.02 0.3/0.29 0.8/0.81 1/0.97',vignette=angle=PI/4.6",
 # resolve / dawn: golden, luminous
 'dawn':   "colortemperature=temperature=5400:mix=0.4,eq=contrast=1.06:saturation=1.0:gamma=1.0,curves=all='0/0.02 0.3/0.29 0.75/0.81 1/1',vignette=angle=PI/5",
}
