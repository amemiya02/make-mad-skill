# make-mad · v1.1.0

**面向高质量 AMV/MAD 的导演—剪辑—后期工作流 skill，附实际可运行的基础媒体工具。**

适用：单动画、单集、综漫、静止系、漫画与动画混合；从构思到审片，也可接手已有工程精修。

核心入口是 [SKILL.md](SKILL.md)。它不把“随机切片+节拍检测+转场预设”当成制作，也不声称一个脚本可以替代导演判断。复杂效果应积极探索，但必须有表达目的、真实技术路线、实看片段和回退设计。

## 交付内容

| 路径 | 用途 |
|---|---|
| `SKILL.md` | 触发条件、行为准则、G0–G7制作与审片流程 |
| `references/` | 制作指南、BGM获取、逐集1080p片源获取、参考审计与可核验来源 |
| `templates/` | 创作简报、选曲、镜头库、音乐地图、VFX卡、审片表、严格时间线schema |
| `scripts/mad.py` | 11个CLI命令：素材、音乐、时间线、基础渲染、质检 |
| `scripts/sources.py` | 检索任务/逐集覆盖表规划、实际下载文件收据；不冒充已搜索 |
| `tests/` | 67项契约测试与合成素材端到端测试 |
| `examples/` | 环境、真实测试输出、原创导演练习，不含未授权动画/音乐 |
| `evals/` | 25个agent工作流评估案例；测试定义，不冒充已经跑过的模型评测 |
| `TEST_REPORT.md` | 实测范围、结果、修复项与未验证边界 |

## 安装与调用

### 通过 npx 安装（推荐）

先安装 [Node.js](https://nodejs.org/)（含 npm 和 npx），在希望使用 skill 的项目目录运行：

```bash
npx skills add amemiya02/make-mad-skill
```

按提示选择 agent 和安装方式。仓库遵循 [Agent Skills](https://agentskills.io/specification) 的 `SKILL.md` 目录格式；[Skills CLI](https://github.com/vercel-labs/skills) 会发现名为 `make-mad` 的 skill，并安装脚本、模板和引用资料。

仅查看可安装的 skill，不写入安装目录：

```bash
npx skills add amemiya02/make-mad-skill --list
```

安装到 Codex 用户目录，供所有项目使用：

```bash
npx skills add amemiya02/make-mad-skill --skill make-mad --agent codex --global --yes
```

安装到 Claude Code 用户目录：

```bash
npx skills add amemiya02/make-mad-skill --skill make-mad --agent claude-code --global --yes
```

去掉 `--global` 即安装到当前项目。安装后重新加载 agent 的 skill 列表，或开启新会话。

`npx` 安装的是 skill 文件；运行媒体脚本还需下文的 Python 依赖及 FFmpeg。

### 手动安装

也可下载仓库完整目录并命名为 `make-mad`，再安装到 agent 支持的本地发现路径。Codex 本地发现与显式调用的来源见 [T10/T11](references/SOURCES.md)。

在包含解压后`make-mad`文件夹的目录中，可这样安装到本地Codex用户目录（macOS/Linux shell示例；不覆盖已有同名skill）：

```bash
mkdir -p "$HOME/.agents/skills"
test ! -e "$HOME/.agents/skills/make-mad" && cp -R make-mad "$HOME/.agents/skills/make-mad"
```

### 调用

在Codex中使用：

```text
$make-mad 为我制作一部90秒左右的AMV。先提出两种真正不同的音乐—叙事方案，再选曲和找素材。
我的重点是情绪共鸣与镜头内部动作卡点；允许必要的高级合成，但不接受为炫技而堆叠效果。
只使用原生1080p以上、无烧录字幕和Logo的合格素材。先完成关键段落试剪，再推进全片。
```

不支持自动发现skill的文件型agent，也可显式要求：

```text
读取 /实际路径/make-mad/SKILL.md，并按其中的阶段链接加载材料。
先报告实际可用的素材、听音、看片、剪辑与合成能力，再执行制作；不得虚构已观看或已渲染。
```

**保留整个目录。**只复制`SKILL.md`会丢失其引用的指南、模板、schema与脚本。

## 运行环境

Python 3.10+；`ffmpeg`与`ffprobe`需已安装并在PATH。需要H.264软件编码器和相关滤镜，先运行`doctor`核实。本次实际版本见 [环境记录](examples/environment.json)，并不保证所有历史或未来版本完全兼容。

渲染 ASS 字幕及运行完整的 `tests/smoke.py` 需要 FFmpeg 的 `subtitles` 滤镜（libass 支持）。若 `doctor` 显示 `subtitles: false`，请使用支持该滤镜的 FFmpeg 构建；无字幕时间线仍可渲染。

```bash
cd /实际安装路径/make-mad
python -m venv .venv
# macOS/Linux；Windows请使用相应虚拟环境激活方式
. .venv/bin/activate
python -m pip install -r requirements-core.txt
# 音乐分析另外需要；其余基础流程不依赖librosa
python -m pip install -r requirements-analysis.txt
python scripts/mad.py doctor
```

依赖文件是兼容范围，不是完整可复现锁文件；实际项目应保存`doctor`和自己的环境锁定文件。网络下载需要真实可用的网络，不会自动建立账户连接。

## 从空项目开始

以下命令在skill根目录运行；路径中的`my-mad`是新项目，不是本包。项目初始化不会写入你的原始素材。

```bash
python scripts/mad.py init ../my-mad --name "站起来之前" --fps 24000/1001
python scripts/mad.py probe /实际路径/clean-source.mkv --out ../my-mad/analysis/source.json
python scripts/mad.py contact /实际路径/clean-source.mkv --out ../my-mad/analysis/contact --interval 30 --limit 60
python scripts/mad.py scenes /实际路径/clean-source.mkv --out ../my-mad/analysis/scenes.csv
python scripts/mad.py analyze-audio /实际路径/music-work-master.wav --out ../my-mad/analysis/music --fps 24000/1001
```

此时必须由agent/剪辑师建立实际的音乐—叙事设计，核实源、选择镜头并填写`edit/timeline.json`。**空模板有意不可渲染**；它没有假装存在的示例素材，也不会自动把所有拍点变成剪点。

```bash
python scripts/mad.py validate ../my-mad/edit/timeline.json
python scripts/mad.py render ../my-mad/edit/timeline.json --out ../my-mad/renders/rough.mp4 --profile draft
python scripts/mad.py qa ../my-mad/renders/rough.mp4 --timeline ../my-mad/edit/timeline.json --out ../my-mad/reviews/qa-rough.json --scan
python scripts/mad.py cutlist ../my-mad/edit/timeline.json --out ../my-mad/edit/cutlist.csv
```

审片与来源检查确实完成以后，才进入交付检查。不能批量改`pending`来绕过它们：

```bash
python scripts/mad.py validate ../my-mad/edit/timeline.json --final
python scripts/mad.py render ../my-mad/edit/timeline.json --out ../my-mad/renders/delivery.mp4 --profile delivery
python scripts/mad.py qa ../my-mad/renders/delivery.mp4 --timeline ../my-mad/edit/timeline.json --out ../my-mad/reviews/qa-delivery.json --scan
```

已有输出默认不覆盖；明确需要时传入`--overwrite`。渲染日志含时间线与输出指纹。`--normalize`是可选的两遍响度归一化，不默认改动混音；使用后仍需聆听和检查编码后的音频。

## BGM与逐部动画的搜寻、选定和下载

完整方案分为 [BGM获取指南](references/12-bgm-acquisition.md) 与 [逐集1080p片源获取指南](references/13-anime-acquisition.md)。前者列出作者/发行商、Bandcamp、OpenTracks、BGMer、MusMus、YouTube Audio Library等实际入口，以及三首候选、两首同段试配、录音版本锁定和下载路线；后者覆盖作品别名/季度/集数、官方发行页、Nyaa RAW与软字幕分类、发布组、镜像交叉核对、版本比较与逐集验收。

初始化会复制 `analysis/acquisition-brief.json`。先替换示例为真实曲目方向、动画名称/版本和所需集数，再生成一个新的取得工作目录：

```bash
python scripts/sources.py plan ../my-mad/analysis/acquisition-brief.json --out ../my-mad/analysis/acquisition
```

输出 `search-jobs.csv`、`music-shortlist.csv`、`source-candidates.csv`、`anime-coverage.csv` 和原始简报。**plan只规划检索URL**，联网agent/浏览器还需执行搜索、读取来源页和回填真实结果。每个必需集数独立计数；未知集数标为待确认。

下载按实际来源分流：提供者正常文件按钮或本地原件 → 公开HTTPS媒体直链 → 已确认允许下载的无DRM公开页面用可选yt-dlp → 已确认可取得的BT用已有客户端或aria2。BGM保存原件并另建WAV工作母带；动画保存逐集原件、去软字幕副本和代理的独立路径。

公开HTTPS媒体直链分别填写 `templates/bgm-download.json` 或 `templates/source-download.json`：

```bash
python scripts/mad.py fetch ../my-mad/bgm-download.json --out ../my-mad/assets/audio/originals/bgm.flac --max-mb 512
python scripts/mad.py fetch ../my-mad/E01-download.json --out ../my-mad/assets/video/work-id/BD/E01-original.mkv --max-mb 8192
```

扩展名和大小上限按实际文件设置。`fetch`验证真实音频流或至少1920×1080的视频流、正时长、体积和可选可信SHA256，写 `.source.json`；它不把网页、磁力或种子解析成媒体。其他下载方式取得的文件填写 `templates/download-record.json` 后统一登记：

```bash
python scripts/sources.py record ../my-mad/assets/video/work-id/BD/E01-original.mkv --manifest ../my-mad/E01-record.json --out ../my-mad/analysis/acquisition/E01-receipt.json
```

文件存在、技术通过、正确版本、原生细节和无烧录文字分别检查。收据不自动通过人工审查；有缺口的作品/集数保持未完成，不能用720p放大补齐。歌曲的试听与试配同样不能由元数据代替。

可选下载工具：

```bash
python -m pip install -r requirements-download.txt
yt-dlp --version
# aria2为独立程序；使用本机包管理器或其官方安装包，随后核实
aria2c --version
```

完整格式选择、文件选择、有限重试和验证命令在两份获取指南中。安装skill不会自动安装这些程序，也不会提供账户、购买或受限平台的下载通道。文件指纹不是独立的来源真实性证明；可信预期SHA256缺失时如实保留未独立验证状态。

## 时间线契约

`timeline.schema.json`拒绝未知字段，避免把“写了高级效果名”误认为“效果已执行”。

- 项目fps使用有理数字符串，如`24000/1001`，时间线坐标使用整数帧；区间统一左闭右开。
- `source_in`以秒或有理秒表示；`speed`是常量源播放速度，1正常、3/2加速、1/2减速。
- 切换：下一镜头`start_frame = 上一镜头start_frame + duration_frames`。
- 溶解：下一镜头起点提前`transition_in.duration_frames`；时长确实重叠，不先串起来再额外添加一段特效。禁止三镜头同时重叠。
- 最后画面结束必须等于`duration_frames`。源时间、音轨长度、淡入淡出、文件存在性均被检查，不用冻结尾帧或静默截断掩盖越界。
- 画面当前是一条顺序轨；静图可用`motion`做推拉和平移。`motion`的x/y为变焦后可移动范围内0–1相对位置，不等于任意世界坐标。
- 音轨独立起始位置、长度、音量和淡入淡出；此基线不提供自动ducking、音频变速曲线或对白语义判断。
- 复杂效果作为外部已完成的`precomp`导入。其`source_lineage`是必须填写的溯源记录，脚本不递归验证外部合成里的每个原始文件；编辑师仍须核查上游。

参考 [工程指南](references/08-engineering-color.md)；真实可复现的填充时间线由`tests/smoke.py`生成。

## 质量与渲染边界

`draft`输出1280×720，`delivery`输出1920×1080。交付前要求入选视频/图像至少1920×1080且有真实清洁源检查记录；元数据无法证明是否720p放大、是否烧录字幕和台标，必须逐选段复核。静止系还须核实最大推镜时有效像素密度。

基线渲染器支持切换、溶解、常量变速、单张静图推移、独立音轨混合和已写好的字幕。它**不等于**专业NLE/合成器：不支持真实多层视差、复杂跟踪遮罩、3D、速度坡道、粒子、复杂动态文字或直接生成`.aep/.drp`。这些能力由真实可用的工具承接，详见 [后端](references/11-backends.md)。

H.264片段中间文件再合成为H.264成片存在有损代际；它适合基础审片/发布输出，不冒充高质量无损归档母版。专业项目应保留NLE/合成工程和适当中间母版，不反复压缩最终MP4。

项目默认-16 LUFS、归一化目标真峰值-1.5 dBTP和编码后检查上限-1.0 dBTP，是可讨论的项目默认值，不是B站/所有平台强制标准。`qa`中的技术通过不代表艺术、来源、听感、文字或完整闪烁阈值已经审查。

## 复现软件测试

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/smoke.py --out ../make-mad-smoke-24 --fps 24 --delivery
python tests/smoke.py --out ../make-mad-smoke-rational --fps 24000/1001
python scripts/mad.py analyze-audio "../make-mad-smoke-24/synthetic music.wav" --out ../make-mad-smoke-24/music-analysis --fps 24
```

测试只生成色条/图案与原创合成声音，**不是一部AMV，也不证明参考级艺术质量**。测试源文件不随包分发，运行测试会在指定目录重建；目录不要指向真实作品素材。

测试记录见 [TEST_REPORT.md](TEST_REPORT.md)。五个用户参考的查证层级见 [参考审计](references/10-reference-audit.md)：本次没有把“读到网页”写成“看完视频”。
