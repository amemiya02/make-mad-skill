# BGM：从搜索、试听、试配到取得工作音源

与 [音乐设计](02-music.md) 配合使用。本文解决实际入口和文件取得；音乐是否成立仍由真实聆听和镜头试配决定。入口核对记录见 [来源](SOURCES.md) 的 A01–A08。网站、曲目和下载按钮会变化，每次执行记录实际访问时间。

## 1. 把创作需求变成搜索条件

从简报抽取情绪的起点/转折/终点、作品时长、台词密度、人声语言、可接受的歌词视角、曲式空间、预算和发布平台。不知道BPM时先按情绪和结构搜索，找到曲目后再分析，不先用一个BPM锁死创作。

- 未锁曲：同时探索两个不同的音乐方向，例如克制的钢琴/后摇与有主歌—副歌对比的人声摇滚。初筛可从每个方向若干首开始，保留至少三首实际可试听的候选。
- 已锁曲：搜索指定作者、曲名和**确切录音版本**的获取方式；不要以同名翻唱、Live、加速、混剪版或“免版权替代曲”偷偷换掉用户选择。
- 只有参考MAD：从原作者简介/曲目表找线索，回到音乐作者或唱片公司的发行页核实。听歌识别结果只是线索，不能代替版本核对。

可复制的搜索组合，替换关键词后实际搜索：

| 方向 | 中/日/英文检索例 |
|---|---|
| 孤独到希望 | `钢琴 后摇 情绪递进 无人声`；`切ない 希望 ピアノ 盛り上がる`；`emotional post rock piano crescendo instrumental` |
| 动作与抉择 | `摇滚 交响 主歌 副歌 爆发`；`ロック 壮大 疾走感 静かなイントロ`；`orchestral rock quiet intro powerful chorus` |
| 悬疑与释放 | `悬疑 紧张 停顿 释放`；`緊張 不穏 ブレイク 解放`；`tension suspense break release cinematic` |
| 确定曲目 | `"作者" "曲名" "版本" official`；`"曲名" 配信 ダウンロード レーベル`；`"artist" "track" Bandcamp download` |

“燃/虐/神曲榜单”可作发现线索，不作为最终选曲依据。不能从标签或歌词文本推断自己已经听过音乐。

## 2. 去哪里找，以及各入口能解决什么

| 入口 | 实际操作 | 取得音源的路线 |
|---|---|---|
| 作者/唱片公司官网；[Bandcamp](https://bandcamp.com/) | 搜作者、曲名、类型；从作者发行页核实版本、试听和曲目表 | 使用作者提供的免费下载、已购买下载或经授权的购买入口；Bandcamp下载页可选FLAC/WAV等格式[A02] |
| [OpenTracks（旧DOVA-SYNDROME）](https://opentracks.com/) | 用站内情绪、曲风、乐器、人声与速度标签；点进曲目页试听完整结构 | 曲目页的实际下载入口；同时保存曲目和作者条件。旧DOVA入口已迁移，不再假定旧链接永远有效[A03] |
| [BGMer](https://bgmer.net/) | 按情绪/场景找曲目，比较完整段落，不只听首页短预览 | 曲目页下载；记录当时适用的[条款](https://bgmer.net/terms/)[A04] |
| [MusMus](https://musmus.main.jp/) | 找适合场景的器乐曲，再验证能否承接高潮和结尾 | 官方曲目下载；从[使用条件](https://musmus.main.jp/info.html)保存需要的署名内容[A05] |
| [YouTube Audio Library](https://www.youtube.com/audiolibrary) | 在Studio内按情绪、类型、时长、作者和署名要求筛选，实际播放 | 官方DOWNLOAD按钮取得MP3；需要署名的曲目复制官方署名文本。跨平台使用范围单独核对[A01] |
| [SoundCloud](https://soundcloud.com/) | 找作者的原始发布页，核实录音版本 | 作者启用下载时使用正常的Download file入口；没有按钮时查作者外链，不把流播放缓存当原始文件[A06] |
| [网易云音乐](https://music.163.com/)、[QQ音乐](https://y.qq.com/)、[Spotify](https://open.spotify.com/)、作者官方视频频道 | 发现曲目、作者、专辑、不同版本及相关歌曲；回到发行来源 | 查看当前平台是否实际提供可导出的音频文件。应用内“离线可听”不证明有可用于剪辑的普通媒体文件 |

不默认免费器乐更适合MAD，也不默认流行歌更适合。音乐获取成本、可剪辑的结构和作品表达一起比较。下载允许、剪辑使用、公开发布和署名分别记在台账；未知项保留未知。购买、账号使用或外部联系按用户已有授权执行。

## 3. 初筛 → 深听 → 同段试配 → 选定

在 `analysis/acquisition/music-shortlist.csv` 逐曲写真实来源、版本、试听范围和听到的结构：

1. 先排除错误版本、预览长度不足、无法取得工作文件及与角色视角冲突的曲目。仅知道曲名的候选标 `metadata_only`。
2. 对至少三首可信候选，实际聆听开头、推进、高潮和结尾；有条件时完整听。记录哪一段容纳对白、哪里有动态变化、尾音是否能自然结束。评分理由指向真实乐段。
3. 对至少两首用同一关键叙事事件做真实试配，约8–20秒可作为初始长度。用相近的监听响度比较，记录实际输出和听看片的证据。
4. 选择与人物意义、镜头内部动作和整片结构最匹配的曲目。保留另两首的落选理由；已锁曲时改为对比剪曲方案。
5. 得到完整可用的确切音源后制作工作母带。冻结音源版本和SHA256，再做节拍/乐段表。改曲或重剪母带后使旧分析和剪点失效。

`decision=selected` 要有选择理由；`MUSIC_LOCK` 还需要实际音源、完成的工作母带及试配证据。文件存在、试听、试配和锁定是四个不同状态。

## 4. 下载路线：先平台正常导出，再按真实URL选工具

先在项目中建 `assets/audio/originals/`、`assets/audio/work/`、`analysis/acquisition/`。一次处理已选的单首/单版本，保留原始下载文件，不反复转码。

### A. 作者/商店/素材库下载按钮

使用曲目页的真实下载按钮或已获授权的购买下载，选可得的原始高质量文件；FLAC/WAV优先是取得选择，不代表文件一定来自无损母版。ZIP先列目录，只取音频和说明文件。记录来源页、文件名、版本、下载时间、条款与署名；对本地文件执行下文 `record`。

### B. 公开HTTPS媒体直链

复制 `templates/bgm-download.json`，填真实媒体URL、曲名、作者、版本、来源和已获得的下载依据；`expected_sha256`没有可信值时保持空，不填自行猜出的值。

```bash
python scripts/mad.py fetch /path/to/bgm-download.json --out /path/to/project/assets/audio/originals/bgm.flac --max-mb 512
```

扩展名按实际文件选择。该命令验证音频流并写 `.source.json`；它不把页面URL解析成媒体URL。过期签名链接从正常下载页面重新取得，不修改签名、协议或认证限制。

### C. 提供者允许取得文件的公开媒体页面

平台有原始文件按钮时优先A。对允许下载、没有DRM且被当前工具支持的页面，可使用可选 [yt-dlp](https://github.com/yt-dlp/yt-dlp)[A07]。先核实本机工具和格式：

```bash
python -m pip install -r requirements-download.txt
yt-dlp --version
yt-dlp --ignore-config --no-playlist --list-formats "实际允许下载的页面URL"
yt-dlp --ignore-config --no-playlist --no-overwrites --retries 3 --fragment-retries 3 --abort-on-unavailable-fragments --write-info-json -f "ba/b" -x --audio-format best -o "/path/to/project/assets/audio/originals/%(id)s.%(ext)s" "实际允许下载的页面URL"
```

`--ignore-config`防止继承机器上的批量、cookies或其他隐含配置；不自动导出浏览器cookies。`--no-playlist`避免误下整张列表。`--audio-format best`用于保留合适的现有音频编码，不能把有损流称为无损原音。若作者只允许试听或页面下载条件不成立，回到A或其他候选；不以yt-dlp支持某站点推断允许任何操作。

### D. 已有本地文件

使用用户指定的文件，核实它确实是选定录音。不要从文件名“FLAC/320k”推断质量。任何复制/转换都保留原件和指纹。

## 5. 取得后的证据与工作文件

从 `templates/download-record.json` 生成音频记录：`kind=audio`，填 `track_title`、`artist`、`exact_version`；删除示例的 `episode`，填写真实 `retrieval_method`（browser/https-direct/yt-dlp/user-local）、来源和既有授权。记录工具不会替你授权或聆听。

```bash
python scripts/sources.py record "/path/to/project/assets/audio/originals/bgm.flac" --manifest /path/to/music-record.json --out /path/to/project/analysis/acquisition/bgm-receipt.json
ffmpeg -v error -xerror -i "/path/to/project/assets/audio/originals/bgm.flac" -map 0:a:0 -vn -sn -dn -f null -
ffmpeg -n -i "/path/to/project/assets/audio/originals/bgm.flac" -map 0:a:0 -c:a pcm_s24le "/path/to/project/assets/audio/work/bgm-work.wav"
python scripts/mad.py analyze-audio "/path/to/project/assets/audio/work/bgm-work.wav" --out /path/to/project/analysis/music --fps 24000/1001
```

WAV是剪辑工作副本，转换不会恢复原文件没有的细节。依据实际工程统一采样率时另记转换参数。检查完整时长、原版本是否正确、是否混入提示音/广告、是否缺头尾、爆音或错误声道；实际听过才更新试听字段。带凭证、签名或个人购买信息的下载元数据留在项目私有区，分享前清理。

## 6. 失败和完成条件

HTTP 403/登录/地区/费用、下载格式不可用、短预览、错误版本、哈希不符和解码失败分别记入台账。工具的有限重试耗尽就停止该次任务；重新打开来源页确认变化，再决定是否重试同一版本或选择备选，不无限重下或悄悄换曲。

完成记录包括：真实候选及落选理由、实际试听/试配证据、选定版本的来源和取得依据、原文件与工作母带指纹、署名/发布待办。未拿到正确版本时 `download_failed` 或 `blocked`，不把搜索结果记成音乐已锁定。
