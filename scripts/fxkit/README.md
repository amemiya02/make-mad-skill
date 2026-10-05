# fxkit — per-shot FX compositor + layers + mix (FFmpeg/numpy/Pillow)

Proven on a 4:30 1080p MAD (104 shots). See `references/14-polish-fx.md` for the red lines it enforces.

```python
import sys; sys.path.insert(0, '<skill>/scripts/fxkit')
import fx, layers as L, mix
fx.set_sources({'12': '/abs/E12.mkv', '13': '/abs/E13.mkv'})       # key -> media
SHOTS = [  # t = SONG seconds where the shot starts; src = source seconds at that moment
  dict(id='K5', t=195.756, ep='12', src=990.449, grade='amber', join=('cut', 0),
       fx=dict(z0=1.04, z1=1.10, glow=(0.55, 36, 0.66), grain=3)),
  dict(id='R1', t=200.26, ep='12', src=996.955, grade='mourn', join=('dissolve', 12),
       fx=dict(z0=1.0, z1=1.06)),
]
P, outs = fx.render_all(SHOTS, END, 'work/shots', preview=True)  # 960x540 first, then preview=False
if L.stale('gfx.mov', GFX, total): L.render_gfx(GFX, total, 'gfx.mov'); L.stamp('gfx.mov', GFX, total)   # spec-hash cache
fx.assemble(P, outs, 'picture.mp4', light='light.mp4', gfx='gfx.mov', preview=True)   # final: CRF16, maxrate 24M
mix.build(music_wav, seconds, DIALOGUE, DUCKS, SFX, 'work/audio')   # never duck over singing
# python finalize.py picture.mp4 work/audio-mix.wav out.mp4   (two-pass loudnorm -14 LUFS)
```

fx keys: `z0 z1 cx0 cx1 cy0 cy1 ease(io|o|i|lin)` push/drift · `settle=(amt,frames)` impact at head ·
`punch=[(song_t,amt,frames)]` · `shake=[(song_t,px,frames,hz)]` · `jitter=px` · `rot0 rot1` ·
`glow=(strength,sigma,threshold)` (RGB screen) · `dblur=[(song_t,frames,radius,angle)]` whip ·
`rgb=[(t0,t1,px)]` · `glitch=[(t0,t1,px)]` · `flash=[(song_t,amp,decay_s)]` · `head_fade/tail_fade=(color,frames)` ·
`letterbox=True|'in'|'out'` · `grain` · `tmix=n` (tame source flicker) · `ramp=(a,b,factor)` slow window ·
`ink_in=(prev_last_frame_png, mask_pattern, frames)` (mask from `layers.make_ink_mask`) · shot-level `speed`.

Rules baked in: sub-pixel `perspective` motion with sampling window clamped inside the source (no edge smear);
zoom expression parenthesised (punch/settle are zoom-IN); glow blended in gbrp (no magenta); dissolve handles are
frozen first frames (never pull frames across a source cut); xfade offset half a frame early (no 1-frame drift);
every intermediate verified for exact frame count; content-hash cache (shot code only, so assembly tweaks don't re-render);
layer files cached by spec hash (`L.stale/L.stamp`), never by existence.

Text: `L.Lyric(..., dark=([(t_on, t_off)], xfade))` / `L.Caption(..., dark=...)` cross-fade to sumi ink over high-key shots;
on letterboxed shots put dialogue captions inside the bar (y≈972 for the 132 px bar).

`textcheck.py picture-clean.mp4 build.py` — luminance under every text box on the text-free render; flags illegible text.

`cutguard.py edl.csv --sources sources.json` — frame-accurate hard-cut detection inside every shot range.

Production additions (v7):
- `dialogue_clean.load_clean(ep, a, b)` → BGM-free voice, float32 (n,2) @48 kHz (Mel-RoFormer → DeepFilterNet hybrid → VAD gate; cached).
  Pass `dialogue_loader=load_clean` to `mix.build`. Calibrate: voice active level −17…−19 dBFS, ≥9 dB over the ducked music;
  a line's tail must end before the vocal re-entry (shift the line *and* its lip-synced shots, don't clip the tail).
- Precomp hero shots: `ae.py spec.json out.mp4` then use the mp4 path as the shot's `ep` with `src=0.0` (cache keyed on file stamp).
- Camera policy: keep a `MOVES` whitelist (≈5–10% of shots) and strip z/cx/cy/rot keys from every other shot.
- Cold open: build it as its own module, join with concat `-c copy`, then `redline.py ... --offset S` and per-part `textcheck.py ... gfx-dark.json`.

v8 additions:
- `cutrhythm.py build.py sections.csv` — cuts/min per section vs target bands, peak/trough ratio (≥2.5), holds ≥3 s, shots <0.25 s.
- `guard_spec.py` / `cutguard.py` snap to the source frame grid (first frame = pts ≥ src, mkv ms-rounded) and test the tail up to the
  last frame + ½ frame; the old half-frame shave let 1-frame strays at a shot tail through. Known false positives = in-shot
  flashes/whips: confirm each with a frame strip of the raw source, never by assumption.
- Delivery: `assemble(..., crf=21, maxrate="8M", preset="veryfast")` → 4:30 at ≈3.5 Mbps / ≈130 MB, no visible artefacts.

## v9–v10 新增（无职转生Ⅲ 项目）
**文字与歌词**
- `fetch_lyrics.py`：从网易云取带时间轴的原文和中文翻译，失败时退到 lrclib，只写文件、不打印歌词；用 `--q`、`--id` 指定歌曲。拿到后要用第二来源（如酷狗）核对行数。
- `lrc_align.py`：把 LRC 时间戳吸附到人声片段（`lyrics-timed.csv`），输出 `lyrics-aligned.csv`（start,end,ja,zh,style,slots），一屏一行。
- `lyrics_ass.py`：歌词和台词写成同一个 `.ass`，用 libass（OpenAdobe 引擎镜像）渲成 gfx 层。
  - 浅色字配暗晕。
  - 字幕跨到高亮镜头时，在切点处换成深色字。
  - 用户可以在 Aegisub 里修改。

**审片与交接**
- `protoboard.py`：成片里每个镜头取首/中/尾三帧拼成审片板，可用 `t0-t1` 只看一段。
- `export_otio.py`：SHOTS 导出为 OTIO 时间线，给 Resolve / Kdenlive 精修。用 `OTIO_PY` 指定 py≤3.13 的环境。

**相关脚本（在本目录之外）**
- 素材索引：`../smeboard.py` 为源镜头索引出首/中/尾帧审片板（`EPINDEX` 环境变量），`../analyze_mad.py` 做镜头切分与指标。
- 语料研究：`../corpus/` 下有 `harvest.py`（B 站搜索候选）、`fetch_corpus.sh`（逐个下载并校验时长）、`run_analyze.sh`（批量拆解）。

**节拍**
- 用 OpenAdobe 的 Beat This!（`openadobe ai run beats`）测拍号和小节线，见 `references/02` 与 `references/19`。
