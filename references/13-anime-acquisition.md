# 动画：逐作品、逐集寻找和取得1080p洁净画面

与 [素材协议](03-sources.md) 配合使用。本文的“生肉”指所用画面没有烧录字幕、台标和Logo；含可分离软字幕轨的容器可以是候选。文件名、发布组名称和网页标签不能代替实看。

## 1. 先确认每一部作品的身份和所需集数

在 `templates/acquisition-brief.json` 逐部登记：内部ID、日文原名、罗马字、英文/中文别名、年份、季/篇章、TV/剧场版/OVA、所需集数或事件。优先从作品官网核对；[AniList](https://anilist.co/)等目录用于名称交叉检索，不能替代发行版本确认。

- 同名重制、分割季度、S02与第二cour、TV合集与总集篇不能混为一份片源。
- 事件尚未对应到集数时，先检索故事/镜头信息并实查；`episodes=[]`标 `needs_episode_mapping`，不能编出集数后下载。
- 需求是全季时，先用官方集数表列出每一集，包括真正需要的特别篇；不把全集种子的标题当作集数完整性证明。
- 每个所需作品/集数都有 `anime-coverage.csv` 一行。先取得关键事件对应的少量集数用于原型，再按分镜覆盖缺口；不默认每部下载全集。

## 2. 实际寻找入口和顺序

| 路线 | 入口与搜索方法 | 核对重点 |
|---|---|---|
| 用户已有素材 | 用户指定的本地盘、NAS、已有工程源文件 | 实际文件、原始版本、是否1080p、清洁区间、现有使用范围；不扫描未授权的私人目录 |
| 官方与发行版 | 作品官网的Blu-ray/DVD、映像特典、配信与下载页；官方作者/发行商视频频道 | BD卷与收录集数、是否提供普通文件/洁净特典。NCOP/NCED是无字片头片尾候选，不代表有全正片 |
| Nyaa社区索引 | [站点](https://nyaa.si/)；Anime–Raw常用分类参数`c=1_4`；英文翻译候选`c=1_2`可能含软字幕 | 搜日文/罗马字/英文别名与集数、1080p、BD/WEB版本；进入发布页看文件清单、组名、大小、更新版与可下载性 |
| 发布组页面 | [Erai-raws](https://www.erai-raws.info/)和[SubsPlease](https://subsplease.org/)作为补充检索入口 | 按作品归档找实际版本；“Raws”或组名不证明没有硬字幕、台标或压缩问题；不能预设每部作品都在站内 |
| 元数据/镜像交叉检查 | [Anime Tosho](https://animetosho.org/)：搜索作品、集数、1080p，查发布条目、嵌入字幕、截图和下载方式 | 其官方说明主要覆盖英文翻译分类等来源，**不是完整RAW库**；镜像、轨道和截图只能辅助筛选[A09] |

社区页面用于发现、交叉核对发行版本及可取得的候选；来源页面能访问不自动证明下载、剪辑和发布范围。执行下载仍需已有的使用依据。索引可能出现广告、挑战、失效镜像或无种条目；记录访问结果，不安装“资源解锁器”，不编造成功获取。

本站点名单是路线，不是“所有动画均有1080p生肉”的保证。平台接口在运行时核实；Nyaa/发布组的当次访问范围见 [来源记录](SOURCES.md) A10。

## 3. 从宽到窄搜索，不把所有条件堆在第一条查询里

以确认后的别名替换`作品名`，每一集独立搜索：

```text
作品名 01 1080p
作品名 1080p BDRip
作品名 1080p BD Remux
作品名 1080p WEB-DL
作品名 01 RAW
作品名 NCOP NCED creditless
"日文原名" Blu-ray 第1巻 収録話 公式
```

零结果时依次：换罗马字/英文别名 → 去掉季号或组名并到页面核实 → 比较`01`/`S01E01`/`EP01`和绝对集数 → 查批次包文件清单 → 查其他版本与来源。不要同时要求RAW+BD+Remux+无字OP，让本来存在的WEB正片被排除。

用 `scripts/sources.py plan` 生成上述逐集检索任务。它只生成URL、候选表和覆盖表；agent需要用实际搜索工具/浏览器执行任务、读发布页，并回填结果证据。没有搜索/浏览能力时保留任务，不把生成的URL当作已找到的片源。

## 4. 候选筛选：先选对，再下载

在 `source-candidates.csv` 记录发布页、发布名/组、季/集、来源版本、容器/编码、声轨/字幕、尺寸、大小、文件清单、下载途径和可用性。每个必需集数尽量留一主一备；只有一份可得候选时如实标记。

1. **身份和完整性**：确认是正确作品、季度与集数；不是预告、AMV、总集篇、重复集或少音轨文件。同集BD/WEB剪辑可能不同，不能跨版混用时间码。
2. **图像质量**：优先比较真实细节、干净画面和素材完整性，通常先看可得的合格BD/Remux或高质量BDRip，再比较WEB-DL。Remux并非永远优于其他来源，特别是本身有缺陷、过大或版本不匹配时。
3. **尺寸与格式**：实际尺寸至少1920×1080；不靠文件名达标。H.264/H.265、8/10-bit和HDR按本机解码/SDR制作能力处理；不能把HDR未经转换硬当SDR，也不为兼容而覆盖原文件。
4. **字幕**：外置字幕或MKV独立字幕轨可以不导入；硬字幕/台标/烧录特效文字不符合清洁源要求。不能仅凭“English translated”排除软字幕版本，也不能凭“RAW”直接放行。
5. **可取得性**：核对真实文件大小、存储空间、种子/链接状态。零种不是绝对不可能完成，但不得当作已有可用源；保存备选和下一次检查条件。

通过以上筛选仅是 `selected_for_download`。原生质量、作品集数匹配和无烧录文字最终需要回看实际文件。

## 5. 下载分流与逐集文件组织

建议布局：`assets/video/<work-id>/<edition>/E01-original.mkv`，原件保留。每集一份收据，批次包也逐文件登记；代理、去软字幕副本和转码另起路径。下载默认进隔离目录，完成后再归档，绝不覆盖已用于时间线的源。

### A. 本地原件或平台正常文件下载

对用户文件仅按授权路径读/复制。官方/提供者提供普通文件或ZIP时使用其实际下载入口，保存来源和文件清单；ZIP不运行附带程序。流媒体应用的离线缓存不等于可编辑文件，遇到DRM/登录/付费限制沿用正常入口或换其他允许取得的来源，不把工具能力写成已绕过限制。

### B. 公开HTTPS直链

填 `templates/source-download.json` 后下载单个已选文件：

```bash
python scripts/mad.py fetch /path/to/E01-download.json --out /path/to/project/assets/video/work-id/BD/E01-original.mkv --max-mb 8192
```

大小上限根据已查到的文件大小和磁盘空间设置；不把8GiB当所有Remux都能通过的固定值。网页URL、`.torrent`和磁力链接不能交给这个直链媒体命令。

### C. 可下载、无DRM的公开媒体页

先列格式，再选择不会退到720p的流。用于已经确认可下载的页面，不把任何官方频道视频自动当成全剧正片。

```bash
yt-dlp --ignore-config --no-playlist --list-formats "实际允许下载的页面URL"
yt-dlp --ignore-config --no-playlist --no-overwrites --retries 3 --fragment-retries 3 --abort-on-unavailable-fragments --write-info-json -f "bv[width>=1920][height>=1080]+ba/b[width>=1920][height>=1080]" --merge-output-format mkv -o "/path/to/project/assets/video/work-id/WEB/%(id)s.%(ext)s" "实际允许下载的页面URL"
```

没有符合尺寸的格式时让下载失败，返回候选筛选；不加一个不带尺寸约束的`/best`兜底。下载后仍需用ffprobe验证实际尺寸，并检查画面是否原生、清洁。

### D. 已确认可取得的BT/磁力条目

使用本机已有的qBittorrent/Transmission，或可选 [aria2](https://aria2.github.io/manual/en/html/aria2c.html)[A08]。先在客户端取得元数据、看文件列表和实际大小，只勾选需要的集数。BT在下载时会与其他peer交换数据；客户端行为须在用户已有授权和项目使用范围内。

```bash
# 本地.torrent先显示文件列表；选中的索引必须来自本次列表，不猜索引。
aria2c --show-files "/path/to/confirmed.torrent"
aria2c --dir="/path/to/project/downloads/work-id" --select-file=2,3 --seed-time=0 --bt-stop-timeout=120 --stop=7200 "/path/to/confirmed.torrent"

# 磁力链接先只取元数据；若未保存.torrent，使用客户端正常的文件选择界面。
aria2c --dir="/path/to/project/downloads/metadata" --bt-metadata-only=true --bt-save-metadata=true --bt-stop-timeout=120 --stop=300 "实际确认的magnet链接"
```

示例将媒体任务总时长限制为7200秒、元数据任务为300秒；按文件大小和项目预算调整，超时保留未完成状态。同一目录重启同一任务可以续传；`--bt-stop-timeout`控制连续零速度，不代替总时长限制。

下载完成后核对所选文件实际完成、客户端校验完成、没有`.part/.aria2`残留标记，不把“元数据已取得/开始下载/返回0”当作媒体完整。`--seed-time=0`控制下载完成后的继续做种，**不会禁止下载过程中的peer上传**。避免同时开多个客户端重复下载同一文件；无peer/超时就记录阻塞，改查备选，不无限后台等待。

## 6. 下载后：文件收据 → 技术检查 → 实看 → 入库

填 `templates/download-record.json` 的实际来源、集数、版本、方法和已有授权，为浏览器/yt-dlp/BT/本地取得的文件写统一收据：

```bash
python scripts/sources.py record "/path/to/project/assets/video/work-id/BD/E01-original.mkv" --manifest /path/to/E01-record.json --out /path/to/project/analysis/acquisition/E01-receipt.json
python scripts/mad.py probe "/path/to/project/assets/video/work-id/BD/E01-original.mkv" --out /path/to/project/analysis/E01-probe.json
ffmpeg -v error -xerror -i "/path/to/project/assets/video/work-id/BD/E01-original.mkv" -map 0:v:0 -map '0:a?' -sn -dn -f null -
python scripts/mad.py contact "/path/to/project/assets/video/work-id/BD/E01-original.mkv" --out /path/to/project/analysis/E01-contact --interval 30 --limit 60
```

`record`验证存在、非空、哈希和媒体流/尺寸，保留所有人工检查为pending；完整解码命令可能耗时，逐个选定文件执行并保存退出状态。随后核实片头/内容确实匹配季集，按 [素材协议](03-sources.md) 完整看所有入选区间和余量，登记 `clean_ranges`。

若确实需要没有软字幕轨的剪辑副本，使用另一路径的流复制，不改变原画面：

```bash
ffmpeg -n -i "E01-original.mkv" -map 0:v:0 -map '0:a?' -sn -dn -c copy "E01-edit.mkv"
```

这只排除独立字幕轨，不能消除烧录文字；日本语音轨按真实流索引选择，不能把第一条默认配音当日语。源字幕/OP字幕仍须实看；NCOP替代OP段落不能证明整集正片洁净。

回填覆盖表：`not_searched → candidates_found → selected_for_download → downloaded → technical_verified → clean_verified → indexed`。失败保留 `download_failed`、`rejected` 或 `blocked`，写原因和可执行下一步。未完成的集数不计入覆盖率；换源/换版后旧时间码、代理和clean审查失效。

## 7. 缺口与完成报告

逐作品报告：所需集数、候选数、已取得数、技术通过数、实际清洁审查数、可剪镜头与阻塞。只有所有**必需**集数/事件满足要求才能声明 `SOURCES_READY`；可选镜头的替代方案单独列出。

只有720p、烧录字幕、错误季集、不可取得或根本没有原生1080p时，不伪造达标。按需求依次换发行版/来源/镜头、修改分镜，确需降低原始约束时取得用户明确变更。完成搜寻流程不保证现实中存在每部作品的合格源。
