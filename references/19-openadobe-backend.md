# 19 OpenAdobe 作为可选后端（实测结论与接法）

OpenAdobe（github.com/amemiya02/OpenAdobe）把 MLT、Blender、Lottie(glaxnimate)、Ardour、ffmpeg(+libass) 装进一个版本锁定的
Docker 镜像，前面是带校验、可撤销的 JSON 操作 API（CLI / MCP）。它面向口播、vlog、短视频，不是 MAD 工具。2026-10-02 实测
（commit eeec40d，仓库当天创建，API 可能变化；接入时锁定 commit）。

## 安装与自检（实测通过）
```bash
git clone https://github.com/amemiya02/OpenAdobe && cd OpenAdobe
uv sync --extra asr --extra mcp --extra otio --extra analysis
uv run openadobe doctor --build --verify      # golden render ok，约 15 s（镜像已缓存时）
```
- 镜像 `openadobe/engines:dev` 内含：melt 7.30、ffmpeg 7.1（含 libass）、Blender 4.3、Ardour 8.12、Noto Sans/Serif CJK。
- zsh 下不要把 `uv run openadobe` 存进变量再展开（不分词）。用 bash 函数或脚本。

## 对 MAD 有用的部分（按价值排序）
| 能力 | 用法 | 实测结论 |
|---|---|---|
| **libass 字幕渲染（镜像内 ffmpeg）** | 歌词/台词写成 `.ass`，在镜像里渲成**透明叠加层**，作为 gfx 层叠到成片：`docker run --rm -v $PWD:$PWD -w $PWD openadobe/engines:dev ffmpeg -f lavfi -i color=c=black@0.0:s=1920x1080:r=24000/1001,format=rgba -vf "ass=lyrics.ass:alpha=1" -t DUR -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le lyrics.mov` | 可用。本机 Homebrew ffmpeg 没有 libass，这是实际增量。ASS 支持 `\fad`、`\blur`、`\bord`、`\k/\kf` 卡拉OK、`\t` 变换、逐字/逐行动画。`.ass` 可交给用户在 Aegisub 里改时间轴和样式。Noto Serif CJK JP/SC 可直接用；其他字体用 `ass=...:fontsdir=/path`。 |
| **Blender 合成（glow 模板）** | `comp.add engine=blender template=glow inputs={"clip":"mN"}`，或直接在镜像里跑自写的 Blender compositor 脚本 | 可用。阈值式 bloom 只让高光（火焰）发光，其余画面不动，比 ffmpeg 的 gblur+screen 更干净。1080p 约 2.7 fps。只给真实光源镜头用。 |
| **OTIO 导出** | `openadobe export-otio DIR out.otio` | 可用。OpenAdobe 只导出它自己的项目；我们的 SHOTS 可直接用 opentimelineio 生成 OTIO，交给 DaVinci Resolve / Kdenlive 手工精修。 |
| **RVM 人像抠像** | `asset.matte` | 在动画角色上**不合格**：艾莉丝剪影大致对，但发丝糊、剑被切掉。不要拿来做可见的抠像特效；最多做柔和遮罩（且需逐帧验证）。 |
| Lottie 模板 | title / lower_third / callout / cta / progress_bar / kinetic_text | 口播包装风格（下三分之一、按钮、标注），不是 MAD 语言。kinetic_text 是逐字弹出，不适合抒情歌词。 |
| MLT 时间线 / 转场 / montage | clip.*、transition.*、edit.montage every=N | 与我们的逐镜头 fx.py 重复。`edit.montage`“每 N 拍一切”正是 MAD 的反模式。不作为主剪辑器。 |
| 音频修复 / ducking / Ardour | asset.process、mix.ducking | RNNoise 级降噪弱于本 skill 的 RoFormer+DeepFilterNet 台词清洗（15-dialogue-isolation.md）。 |

## 已接好的两条管线（fxkit）
- **`lyrics_ass.py`：歌词和台词字幕写成同一个 `.ass`，经镜像 libass 渲成 gfx 层。**
  - `build(lyrics_csv, CAPTIONS, out.ass, dark=layers.bright_spans(...))` 生成字幕文件，`render(ass, total_frames, gfx.mov)` 渲成 gfx 层。
  - 输出 qtrle/argb，帧数精确，`fx.assemble(gfx=...)` 直接叠加。
  - 按 `.ass` 内容、帧数和脚本自身的哈希缓存，20 s 测试约 2 s。
  - 样式：
    - 日文行：Noto Serif CJK JP 50px，位于下三分之一。
    - 中文行：Noto Serif CJK SC 34px，在日文行下方。
    - 台词（CAP 样式）与歌词同一字体。
    - BIG 样式：居中大字，全片最多一两次，用于一个关键词。
  - 浅色字下垫柔和暗晕（layer 0：`\bord5\blur7`，黑色 α≈0x78），上面是清晰字（layer 1）。
    - 实测：白色辉光在中灰画面上会吃掉对比，不要用。
  - 一行跨过高亮镜头（占比 >35%）时，自动换成深色字加浅色晕。
  - 一屏只有一句；与台词时间重叠的歌词行让位。
  - 交付时把 `.ass` 一起给用户，用 Aegisub 可改时间轴和样式。
- **歌词来源与对齐（实测：光の唄）**
  - `fetch_lyrics.py` 从网易云取带时间轴的原文和译文。
  - 网易云与酷狗两个独立来源的行数一致（20/21 行），说明这首歌词本身就稀疏：每行约 11 字，唱 3–4 口气，约 11 s。行数少不代表歌词不全，先用第二来源核对再下结论。
  - 时间戳已落在人声起音上（±0.15 s）时，不需要强制对齐。用 `lrc_align.py` 吸附到 `lyrics-timed.csv` 的人声片段：每行起点吸到最近的片段起点，终点为下一行开始前最后一个片段的结束。
  - 一行一屏。
  - 实测排版：日文 50px 描边 1.3；中文 35px 描边 1.2；暗晕 α≈0x50、bord6、blur8。暗晕 α 0x78 在夕阳、火焰、白衣画面上太淡。
- **`export_otio.py`**：SHOTS → OTIO（V1 镜头 + 变速 + 溶解，A1 歌，A2 台词），给 Resolve 或 Kdenlive 精修。opentimelineio 0.18 在 py3.14 上报 "bad any cast"，所以 OTIO 部分在 OpenAdobe 的 py3.12 venv 里跑，脚本会自动切换。

## 本地 AI 任务（2026-10-05，本地 OpenAdobe 工作区的新版）
- 入口：`openadobe ai doctor` 看本机会用哪个模型，`openadobe ai run TASK --input k=v` 直接跑（文件进、JSON 出）。
- 在 Apple M2 / MPS 上都有可用模型。

| 任务 | 模型 | 对 MAD 的用处 |
|---|---|---|
| **beats** | Beat This!（MIT） | **必用**。实测「光の唄」：librosa 给 115 BPM，Beat This! 给 85.8 BPM 并带小节线，librosa 是 4:3 速度误判，按它切的点大多落在拍与拍之间。约 54 s。 |
| shots | TransNetV2 | 比亮度差检测器更少把源画面闪光当切点，可用来重做逐集镜头索引与 cutguard |
| embed | SigLIP 2 | 用文字搜镜头，如“艾莉丝在雪中挥剑” |
| interpolate | RIFE 4.25 | 慢放补帧（现在的变速是重复帧）。动画是一拍二/一拍三，必须逐镜对照后再用 |
| ocr | RapidOCR | 检查烧录字幕和台标 |
| review | Qwen3.5-9B VLM | 对成片抽帧给带时间码的问题单，可作为额外一轮审片，不能代替人看 |
| segment / matte / depth / upscale / separate / enhance | SAM 2.1 / BiRefNet / Depth-Anything / Real-ESRGAN / Demucs·RoFormer / MossFormer2 | 抠像和视差在抒情 MAD 里慎用；台词分离已有更强流程 |

- 规则：音乐分析先用 Beat This! 定拍号与小节线。`analyze-audio` 的 librosa 节拍只作参考，两者不一致时以 Beat This! 为准，并逐段抽查。

## 接入原则
- 主流程仍是 fx.py 逐镜头渲染 + cutguard，便于帧级控制和缓存。OpenAdobe 只作为**按需调用的引擎**：
  - libass 文字层
  - Blender 合成单镜头
  - OTIO 交接
- 任何经它渲染的镜头，都要和原镜头做并排帧对比，确认有增益再用。
- 已知怪行为：
  - 无音轨的工程，`render` 会把 master gain 拉到 +56 dB 去追响度，然后 QC 因响度失败。只用来出画面时可以忽略。
  - 导入时会把素材转成 CFR 夹层（.mov），会占磁盘。
