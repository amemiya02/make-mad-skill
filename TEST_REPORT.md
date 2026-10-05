# make-mad v1.0.0 — 实际验证报告

日期：2026-09-30。验证对象：当前包内Python脚本、schema、模板与本地FFmpeg执行链。**不是完整参考作品的观片报告，也不是成片艺术质量评测。**

## 环境

Python 3.13.5；FFmpeg/ffprobe 7.1.5；jsonschema 4.26.0；Pillow 12.3.0；NumPy 2.3.5；librosa 0.11.0。完整实际输出见 [environment.json](examples/environment.json)。外部AE/Fusion/Blender、PySceneDetect和OTIO未被本次脚本调用测试。

## 结果概览

| 检查 | 实际结果 | 证据 |
|---|---|---|
| Python契约测试 | **43/43通过** | [unit-tests.log](examples/unit-tests.log) |
| 24fps端到端交付规格测试 | **通过**；1920×1080；144帧；6.000秒；H.264/AAC；48kHz | [结果](examples/validation/24fps/result.json)、[QA](examples/validation/24fps/qa.json) |
| 24000/1001fps端到端草稿测试 | **通过**；1280×720；144帧；6.006秒；H.264/AAC；48kHz | [结果](examples/validation/24000-1001fps/result.json)、[QA](examples/validation/24000-1001fps/qa.json) |
| 编码后响度测量 | 24fps：-16.03 LUFS / -6.87 dBTP；分数帧率：-16.02 LUFS / -6.71 dBTP | 上述QA的`input_i/input_tp` |
| 节拍/起音/能量分析 | 实际生成JSON、CSV；合成120BPM素材得到约120.185BPM候选，15个beat候选，均待人工确认 | [analysis.json](examples/validation/music-analysis/analysis.json)、[beats.csv](examples/validation/music-analysis/beats.csv) |
| 渲染预览与指纹 | 实际输出6秒1080p合成测试视频，SHA256记录可重算 | [视频](examples/validation/synthetic-pipeline-test-1080p.mp4)、[渲染日志](examples/validation/24fps/smoke.render.json) |
| 参考作品研究 | 2原页元数据、1官方搜索摘要、2待核；完整观片/听音0 | [参考审计](references/10-reference-audit.md) |
| 18个agent工作流案例 | 已编写，**未执行模型评测** | [评估说明](evals/README.md) |

上述LUFS不是给真实MAD推荐的固定听感值；测试声音是原创合成信号。技术返回状态为`technical_checks_pass_human_review_required`，不是艺术签核。

## 软件测试覆盖

契约测试检查：合法与非法切换/溶解时间线、空工程、缺素材、重复ID、帧数不符、越界源/音轨、过长淡入淡出、未知效果字段、非正常变速、错误有理数、非零起点、HDR拒绝、720p交付源拒绝、预合成溯源字段、未审核清洁源与区间、pending交付门、静图/视频运动字段、帧率数学、拍点四舍五入、网络路径约束、初始化保护，以及分数帧率片尾抽帧边界。

两次真实端到端测试均覆盖：合成视频+高分辨率静图+原创合成声音；含空格文件名；常量1.5倍速；硬切后接12帧溶解；之后再硬切；静图镜头运动；两个独立音频层、音量和包络；ASS字幕；两遍响度处理；H.264/AAC编码；实际解码帧数；场景候选CSV；切单CSV；PNG抽帧与联系表。

合成画面、正弦音与点击音由测试脚本现场创建，未使用用户所给作品的音视频。示例的review=pass明确是测试fixture状态；真实项目不允许依此自动签核。

## 保留的警告

两组源验证均报告部分合成源缺少transfer元数据解释，保留了人工解释字段和fixture声明。此项不被隐藏为“完全无警告”。

分数帧率测试有意使用draft，QA保留“不是项目交付分辨率”的警告。其通过只表示相应草稿技术检查通过，不应被改写成1080p交付通过。24fps最终编码QA没有错误或警告。

黑场/静止检测是候选检查。动画长停顿可能合理，不会因为候选被找到就强行删帧。本包没有把这种检测当作闪烁风险认证。

## 测试中发现并修复的问题

1. 硬切concat之后接xfade时，时间戳处理导致滤镜输入缺少可靠帧率：修正为明确重建fps/timebase，再进行溶解。修复后两个帧率均实际输出正确144帧。
2. 部分草稿帧在MJPEG缩略图编码中触发色彩范围限制：中间缩略图改为RGB PNG，联系表再由Pillow输出JPEG。
3. 6.006秒视频按2秒间隔尝试在6.000秒抽帧时，可能已超过最后一帧的显示起点：采样上限扣除一帧，并加入3项边界测试。分数帧率完整测试重新执行通过。

## 未验证，不能声称已完成

真实动画/歌曲下载的在线成功路径、需要账户的服务；所有操作系统与FFmpeg版本；AE/Fusion/Blender工程、真实2.5D/3D/速度坡道；复杂CJK字体覆盖；HDR完整调色链；真实参考作品连续播放和音频聆听；烧录字幕/Logo自动识别；完整闪烁规范；实际受众情绪反馈；真实成片发布权限。

基础renderer的单画轨和H.264中间编码边界仍然存在，不因单元测试通过变成专业合成器或无损母版工具。网络下载保护只测试了部分输入约束，不应宣称完整安全审计。

本次看过部分测试联系表，只可说明被抽到的静态画面可见；不把它描述为已完整播放或听过混音。

## 复现

安装依赖并运行README中的两次`tests/smoke.py`和`analyze-audio`命令。源文件会在指定测试目录重新生成。帧数/时长应与报告一致；不同库/编码器版本可能产生不同字节、指纹或少量测量差异，应记录实际结果。

任何对代码、schema、音频母带或时间线的修改都应使相关旧测试记录失效并重跑。

## 公开仓库安装验证（2026-10-01）

保留以上 2026-09-30 的原始测试证据；此次发布仅补充安装说明、运行环境提示和文件校验清单，未修改制作脚本、schema 或模板。

- 使用 Skills CLI 1.7.0 的 `npx skills add <本地仓库路径> --list`，成功发现唯一的 `make-mad` skill。
- 在独立测试项目中，以 `--skill make-mad --agent codex --copy --yes` 实际安装；核对入口、agent 元数据、依赖文件、脚本、模板、引用资料和测试，共 33 个必要文件与仓库内容一致。
- 在安装后的目录运行契约测试，**43/43 通过**。
- 使用 Agent Skills 官方 `skills-ref` 参考校验器验证安装后的 `make-mad` 目录，**通过**，包括标准支持的 `compatibility` 字段。
- 核对原始包的 61 个 SHA256 条目及相对 Markdown 链接，均通过；文档变更后重新生成仓库的 `MANIFEST.sha256`。

此次本地环境为 Python 3.14.4、FFmpeg/ffprobe 8.1.2、jsonschema 4.26.0、Pillow 12.3.0。该 FFmpeg 构建缺少 `subtitles` 滤镜，因此带 ASS 字幕的完整 `tests/smoke.py` 在字幕步骤失败，不能记为完整端到端通过。使用同一合成测试时间线、仅清空 `caption_file` 后，实际完成 24000/1001fps 草稿渲染。此项验证不覆盖字幕烧录、可选音乐分析或艺术审片。

## v1.1.0：BGM与逐集1080p片源获取（2026-10-01）

本次新增两份获取指南、检索规划/收据脚本、候选与覆盖模板；初始化和doctor接入新入口，`fetch`补上音频流/正时长检查、媒体类型约束及已有来源侧车保护。渲染器、时间线schema和音乐分析算法未改动。以上v1.0的渲染/音乐分析记录仍是历史版本证据，本次没有将它们重新记为v1.1完整端到端通过。

| 检查 | 本次实际结果 | 证据/边界 |
|---|---|---|
| Python契约测试 | **67/67通过**：原43项及新增24项 | [日志](examples/acquisition-validation/unit-tests.log)；新测试用合成元数据和模拟HTTPS，不访问第三方媒体 |
| 初始化与检索规划 | 实际生成新模板；示例简报生成64个planned任务、2个逐集需求；CLI退出0 | [结果](examples/acquisition-validation/result.json)；示例不是实际查到的动画资源 |
| 真实音频文件收据 | 现场FFmpeg生成2秒48kHz FLAC，探测及可信hash匹配，CLI退出0 | 原创合成测试音，不是真实歌曲；试听/版本人工审查仍pending |
| 在线公开HTTPS下载 | 实际下载本仓库已公开的原创合成1080p视频，7,521,540字节，SHA256与发布原件匹配 | 同一结果记录；仅验证公开直链路径，不证明任一歌曲/动画提供者下载成功 |
| 真实视频收据与完整解码 | 1920×1080 H.264；完整FFmpeg解码退出0；收据clean/原生/季集审查保留pending | 同一结果记录；没有自动签核clean source |
| yt-dlp格式筛选 | 本机2026.08.19；合成格式元数据选中音频/1080p，720p无匹配 | 仅验证格式选择器，不是平台页面下载或账户流程验收 |
| 本地npx安装/格式校验 | copy模式安装成功，73个SHA256条目一致；官方skills-ref验证通过；安装目录的plan CLI实际成功 | 安装不自动装可选下载器；没有操作用户全局skill目录 |
| 25个agent工作流案例 | 原18项加7项获取场景；**未运行模型评测** | [案例](evals/cases.json)；不能把软件测试结果当作agent选曲/搜源质量 |

新测试覆盖逐作品/逐集不漏项、未知集数不编造、用户锁曲、社区入口可关闭、Unicode查询、已有证据保护、音频/视频流类型、720p与封面图拒绝、可信hash不符、零/NAN时长、部分文件与aria2控制文件、有限体积、失败临时文件清理与人工审查保持待审。

提供者条件/工具说明与实际首页分类已联网核对，范围见 [A01–A10](references/SOURCES.md)。本机未安装aria2，因此BT/磁力路径依据官方手册编写，未做真实BT下载；也未购买、使用账户、取得真实歌曲或动画正片。宿主联网检索、实际聆听、逐选段原生/烧录字幕检查仍需真实项目执行。

## v1.2.0（2026-10-05）：无职转生Ⅲ 实际项目回写
**测试**
- `python -m unittest discover -s tests`：67 项全部通过。
- 仓库内所有相对 Markdown 链接都能解析。
- 新脚本 `py_compile` 通过。
- `fetch_lyrics.py --search-only` 实测能检索到候选。

**新增内容的出处**
新增的 reference 与 fxkit 工具来自一个实际 MAD 项目的 v5–v10 迭代，以及其中逐轮的真人审片意见。经验与根因记在 `references/20-retrospective.md`。

**未验证边界**
- 语料笔记基于静帧和测量数据，不是观看或聆听。
- fxkit 是项目里实际用过的工具，但还没有为它单独写契约测试。
