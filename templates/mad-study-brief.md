# MAD study brief (for analysis subagents)

Goal: learn how top-quality Bilibili MADs are built, so that a 4.5-min single-series MAD of 无职转生 S3 set to the lyrical
pop-rock song 「光の唄」 (115 BPM, verse → chorus → bridge → final chorus, about Rudeus' regret, the old Rudeus' time-travel
warning, Eris' training, family, death and resolve) can be re-edited at that level. The user rejected the previous version:
- Eris' sword-training sequence felt badly connected ("镜头衔接太垃圾").
- The ending (after the last chorus) was weak.
- The whole thing had weak narrative, transitions and effects.
- Bolted-on effects were rejected: digital shake, punch-zoom pulses, white flash frames, glowing roto cut-outs, lens flares, glitch transitions.

## What you have, per video (all under the corpus working dir `$CORPUS_DIR`)
- `videos/<BV>.info.json` — title, uploader, view/like/favorite counts, description, tags.
- `study/<BV>/metrics.json` — measured numbers:
  - shots, cuts_per_min
  - hard_cut_share, dissolves, flashes, fades_to_black
  - shot_len quantiles
  - zoom_shots (scale change inside a shot; cannot tell source camera from digital)
  - shaky_shots
  - music:
    - cut_on_onset_1f vs chance_onset_1f
    - density_loudness_r
    - cpm_10s / rms_10s
  - overlay: text/logo edges that persist through cuts
- `study/<BV>/shots.csv` — every shot: start/end/duration, how it was entered (cut/dissolve/fade/flash), luma, saturation, motion, scale_per_s, shake.
- `study/<BV>/shotboard-N.jpg` — one frame per shot, in order, labelled `#idx m:ss.s duration [DIS/FADE/FLASH]`. This is your main view of narrative structure.
- `study/<BV>/transitions-N.jpg` — 8-frame strips:
  - every soft transition (dissolve/flash/fade)
  - 24 random hard cuts (`cut` rows: 3 frames before → 3 after)
- `study/<BV>/curve.png` — cuts per 10 s (blue bars), music RMS (orange), picture luma (yellow), hard cuts (white ticks), dissolves (green), flashes (white bars).

## Honesty rules (strict)
- You are looking at still frames and numbers. You did not watch the video or hear the audio. Never write "I watched/heard".
- Only state what the frames or metrics show. Mark inferences as "(推断)".
- Never invent timestamps; cite the `#idx`/time labels printed on the sheets.
- Note detector limits:
  - Source-animation flashes and explosions can count as cuts.
  - Effect-heavy openings inflate the cut count.
  - Zoom can be the source camera.
  - Some downloads are 480p.

## For each video, write `study/<BV>/notes.md` (Chinese), with these sections
1. **概况**：
   - 标题、UP、播放/收藏比
   - 时长、素材（单作/多作）、类型（剧情/燃/抒情…）
   - 一句话说明它讲了什么
2. **叙事结构**：
   - 按时间段划分 4–8 段（引子/主歌/副歌/间奏/高潮/尾声…）。
   - 每段写：时间、讲什么、用了哪些角色/场景、情绪如何变化。
   - 组织方式（时间顺序/平行剪辑/回忆插叙/对比/母题重复）。
3. **剪辑节奏**：
   - 各段剪辑密度（引用 cpm_10s 和镜头时长）。
   - 长镜头（>3 s）出现在哪、为什么。
   - 快切串在哪、为什么。
   - 动作衔接的具体例子：动作接动作、方向连续、视线匹配、形状/颜色匹配，引用 transitions 里的 cut 行或 shotboard 相邻镜头。
4. **转场**：
   - 硬切占比。
   - 逐条列出软转场（溶解/闪白/黑场）及其动机（回忆、时间流逝、光/形匹配、段落切换），并判断是否有效。
5. **特效与画面处理**：
   - 调色（统一色调？分段色调？）、遮幅、字卡、光效、速度变化、定格、缩放、抖动、叠化、文字。
   - 写出时间点。
   - 判断每一项是服务叙事还是装饰。
6. **文字/歌词**：
   - 有没有歌词字幕。
   - 语言、位置、字号（相对画面）、颜色、字体风格（宋/黑/手写）、动画（淡入/逐字/无）。
   - 歌词以外的文字（标题卡、章节字、台词）。
7. **与音乐的关系**：
   - cut_on_onset_1f 对比 chance（大于随机多少）。
   - density_loudness_r。
   - 从曲线看：副歌是否更密，安静段是否长镜头。
8. **可迁移到「光の唄」无职MAD的经验**：
   - 3–6 条，具体到可以执行，例如“艾莉丝修行段：…”“结尾：…”。
   - 另列 1–3 条不该学的。

Finally return to the caller a compact summary (≤250 words per video): the key numbers plus the 3 most important transferable lessons.
