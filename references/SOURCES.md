# 外部来源与证据范围

核验日期：**2026-09-30**。本包中的构思流程、质量门、评分、试剪时长与默认响度是项目设计建议，不伪称为某标准或参考作品的原作者结论。技术能力以本地`doctor`、测试与实际工具为准。

## 用户作品

五个用户URL及逐项证据等级见 [10-reference-audit.md](10-reference-audit.md)。R01/R04原页文本可读；R02仅官方搜索摘要；R03未确认；R05仅二级线索。没有完整视频/音频观看证据，也没有导入这些作品的片段。

## 技术与制作资料

| 编号 | 主来源 | 本包据此核对的范围 | 本次边界 |
|---|---|---|---|
| T01 | FFprobe官方文档：https://ffmpeg.org/ffprobe.html | 读取流、容器及JSON元数据 | 元数据不识别烧录字幕、台标或真正原生细节；实现有本地测试 |
| T02 | FFmpeg官方滤镜文档：https://ffmpeg.org/ffmpeg-filters.html | trim、时间戳、fps、xfade、zoompan、loudnorm、字幕与检测滤镜 | 部分能力实际调用；不是本包支持文档列出的所有滤镜；见测试报告 |
| T03 | librosa beat_track官方API：https://librosa.org/doc/main/api/generated/librosa.beat.beat_track.html | 节拍估计接口与输出含义 | main文档可变；本地实际使用并测试0.11.0，不把节拍结果当作乐句/歌词理解 |
| T04 | PySceneDetect官方文档：https://www.scenedetect.com/docs/latest/ | 可选镜头检测工具入口 | 本包未安装/调用它；`scenes`实际使用FFmpeg场景变化分数 |
| T05 | Adobe Roto Brush/Refine Matte官方文档：https://helpx.adobe.com/after-effects/desktop/roto-brush-and-refine-matte/roto-brush/roto-brush-refine-matte.html | 高级遮罩路线的能力依据 | 未在AE桌面环境执行或验证具体工程；不得声称本包已完成高级抠像 |
| T06 | W3C WCAG闪烁判据解释：https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold.html | 闪烁风险包含频率、面积与光/颜色变化条件 | 本包未实现完整阈值检测，不提供闪烁安全认证 |
| T07 | AnimeMusicVideos.org作者指南：https://www.animemusicvideos.org/guides/ ；AMV101：https://www.amv101.com/guides | 作者社区的进一步学习入口 | 核对的是索引入口；旧技术设置不能直接当作当前编码标准，未宣称读完全部文章 |
| T08 | YouTube官方上传建议：https://support.google.com/youtube/answer/1722171?hl=en | 平台交付规则应单独核验的示例 | 是YouTube自身建议，不能外推为B站要求；不据此宣称统一响度标准 |
| T09 | Blackmagic Design官方培训：https://www.blackmagicdesign.com/products/davinciresolve/training | Resolve/Fusion等实际后期工作流的官方学习入口 | 未在该桌面软件执行工程；按用户本地版本和可用功能选择 |
| T10 | Agent Skills开放格式规范：https://agentskills.io/specification | SKILL.md、name/description及按需加载文件结构 | 格式兼容不代表所有宿主已完成安装验收 |
| T11 | OpenAI官方Build skills：https://learn.chatgpt.com/docs/build-skills ；官方插件技能说明：https://developers.openai.com/plugins/build/skills | 本地Codex `.agents/skills` 位置、`$`调用、目录组成与可选metadata | 2026-09-30可读；本次创建了文件，未操作用户账户安装 |
| T12 | AKROSS作品目录：https://www.akross.ru/index.cgi?videos=ac2024 | 扩展参考检索入口 | 未核验任一作品的获奖排名或完整播放；不能以目录存在替代观片 |

## 使用这些来源时的纪律

外部材料说明“工具有什么能力”，不证明“这次工具已经完成”。执行证据在`TEST_REPORT.md`；元数据证据在参考审计；艺术结论必须来自实际作品审看。

使用升级后的工具时重新核验命令和接口，不把文档的`latest/main`当作本地版本。平台要求也应在真正交付前重新查官方来源。

仅在有实际原作者说明或工程证据时，将某种方法归于某位作者。普通截图只能证明该时刻的画面，不能证明声音、连续运动、插件或工作流。

## BGM与动画获取入口核对（2026-10-01）

以下为本次联网核对的第一方说明/入口，支撑 [BGM获取](12-bgm-acquisition.md) 和 [逐集片源获取](13-anime-acquisition.md)。核对文档与网页入口不等于取得了任何真实歌曲或动画正片；下载条件、曲目和具体条目每次执行重新检查。

| 编号 | 第一方来源 | 核对范围与本次边界 |
|---|---|---|
| A01 | [YouTube Audio Library官方帮助](https://support.google.com/youtube/answer/3376882?hl=en) | Studio筛选、MP3下载、部分曲目的署名；不能将平台自身说明外推为所有平台保证 |
| A02 | [Bandcamp下载格式说明](https://get.bandcamp.help/en/articles/15263234-in-which-formats-can-i-download-my-purchases) | 正常下载页可选格式；未购买歌曲、未操作账户，不凭FLAC扩展名确认真实无损 |
| A03 | [OpenTracks](https://opentracks.com/)、[使用条件](https://opentracks.com/help/articles/license/) | 第一方页面确认旧DOVA-SYNDROME于2026-09-15更名；查看当前曲目/作者条件，未逐曲下载 |
| A04 | [BGMer使用条件](https://bgmer.net/terms/) | 当前官方下载与使用条件入口；没有将曲库统一当作不需核对的发布许可 |
| A05 | [MusMus使用说明](https://musmus.main.jp/info.html) | 官方条件与署名入口；实际使用需记录适用曲目的要求 |
| A06 | [SoundCloud下载说明](https://help.soundcloud.com/hc/en-us/articles/115003448787-Downloading-tracks) | 作者启用文件下载的正常入口；试听流和应用离线不同于可导出原件 |
| A07 | [yt-dlp官方README](https://github.com/yt-dlp/yt-dlp) | 格式筛选、音频提取、配置隔离、下载范围与重试参数；工具支持不等于某条目允许下载，不保证网站长期可用 |
| A08 | [aria2官方手册](https://aria2.github.io/manual/en/html/aria2c.html) | torrent文件列表/选择、磁力元数据、超时和做种行为；seed-time不阻止下载过程上传，本机未安装aria2做真实BT验证 |
| A09 | [Anime Tosho官方About](https://animetosho.org/about) | 主要镜像范围、英文翻译分类及元数据入口；不是完整RAW目录，截图不等于逐选段clean验证 |
| A10 | [Nyaa](https://nyaa.si/)、[Erai-raws](https://www.erai-raws.info/)、[SubsPlease](https://subsplease.org/) | 本次HTTP读取三个首页成功；Nyaa当前分类实际含Raw=1_4、English-translated=1_2。仅核对入口/分类，未验证任一作品完整性、种子活性或媒体下载；不使用未找到的/faq/路径 |

AniList、网易云音乐、QQ音乐和Spotify在本包中仅列为发现/名称交叉检索入口；本次没有验证其账户下载流程。已取得文件的收据与来源声明仍需项目级复核。
