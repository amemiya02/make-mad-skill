# AE 级特效：抠像、拉镜、定格、光线（开源等价方案与实测）

起因：成片被批“特效太少，AE 能做的拉镜、抠图都没看到”。FFmpeg 滤镜链（`fxkit/fx.py`，见 14）做不到**角色级**操作：它不知道人物在哪、背景后面是什么、画面里哪块更近。本文件给出 AE 技法 → 开源等价物，以及封装好的预合成渲染器 `scripts/fxkit/ae.py`。

**使用原则：只给英雄镜头（hero beats）用，一片通常 3–6 处。** 每个镜头要能回答“这个效果替这一拍说了什么”。全片铺满等于把 14 里的“无动机推镜”红线换个名字再犯一次。ae.py 的产物是**预合成素材**（1920x1080、24000/1001、帧数精确），在 build 里当普通镜头源（src=0）使用。

## 一、AE 技法 ↔ 开源等价物

| AE 技法 | 本管线等价物 | 说明 / 注意 |
|---|---|---|
| Roto Brush / Roto Brush 3 | anime-seg（skytnt ISNet `isnetis.onnx`，CoreML ≈0.4 s/帧）→ 引导滤波贴边 → 光流补偿的时域平滑；更难的镜头换 BiRefNet / SAM2（逐帧 prompt，需要 GPU，慢） | 通用人像抠像模型会把赛璐璐线稿吃掉，anime 专用模型对线稿友好。时域平滑把边缘闪烁减半（见 QA） |
| Content-Aware Fill（视频） | 静机位：抠像掩膜外像素的**时间中值** + LaMa（big-lama TorchScript，CPU）补“每帧都被遮挡”的洞；运动镜头：单帧 LaMa；更强：ProPainter（光流引导视频补全，慢，内存大） | 洞越大越糊；洞 ≤ 画面 35% 时 LaMa 在动漫背景（格栅、天空渐变）上可用 |
| 3D 摄像机 / 视差（Parallax） | 2.5D 分层：前景（抠像）+ 干净背景板，各自仿射，前景速率 > 背景速率，运动模糊按位移自适应子采样 | `parallax`；背景外扩 overscan 防露边 |
| Depth Map 置换摄像机 | Depth Anything V2 Small（MPS）→ 引导滤波对齐边缘 → 按深度的位移/缩放 remap（定点迭代取源像素深度） | `depth_dolly`，适合风景/无人物；近景缩放多于远景 |
| Stroke / Outer Glow / Drop Shadow | 掩膜形态学外扩得描边；高斯模糊+着色叠加（screen）得外发光 | `freeze_pop` 的 fg 参数 |
| 定格（Time Remap hold / Freeze Frame）+ Levels/Blur 背景 | 解码一帧，背景板去色/压暗/模糊/偏色，人物 ease-out-back 弹出；保持期缓推 | 保持期**吞掉**源时间，之后接上实时运动，总长不变 |
| CC Radial Blur / Zoom 转场 | 径向多采样模糊（缩放核）+ 缩放曲线 + 色散 + 闪白；A 尾加速放大、B 头减速缩回 | `zoom_through`，两镜头各自的运动要匹配方向 |
| CC Light Rays / Trapcode Shine / God Rays | 亮部阈值 → 径向模糊 → screen；再叠一层按火焰亮度门控的角向光束（light_burst）才能看出“光柱” | 单纯径向模糊只会得到光晕，小光源看不出射线（实测） |
| 文字在主体后（Text behind subject） | 文字层夹在背景与抠像之间合成，文字可轻微视差（比场景慢=更远） | `text_behind`；中文用明朝（见 `layers.py FONTS`） |
| Twixtor / 时间重映射 | RIFE（光流插帧）。**动漫警告**：作画常为 2/3 拍的跳帧，线稿高对比、运动不连续，RIFE 会把线稿揉成鬼影，大位移处整块撕裂 | 只对慢推镜/背景使用；打斗和作画镜头用重复帧或原节奏，不要插帧。检查：逐帧看线稿是否双线 |
| Particles（Particular） | 本管线暂无；可用 `speed_lines`/`light_burst`，或程序化 Pillow/numpy 粒子（火星、雪、花瓣）screen 叠加，随机种子固定 | 粒子必须写固定 seed 才可复现 |
| Displacement Map / Turbulent Displace | `cv2.remap` + 噪声/深度图位移；热浪、水面 | 幅度 ≤ 6 px，否则线稿抖成果冻 |

## 二、ae.py 接口

```
# 环境：独立 venv（例：<workspace>/.venv-vfx） （torch+MPS、onnxruntime、transformers、opencv 5）
python ae.py spec.json out.mp4        # 末行打印 frames=N；同时写 out.mp4.json（s/帧、分段耗时、闪烁指标）
```
Python：`render_precomp(spec, out_path) -> 帧数`；`zoom_through(clip_a, clip_b, out, frames)`。`.mp4`=H.264 CRF10，`.mov`=ProRes 422 HQ。片源：`ep`（在 `$MAD_ROOT` 或当前目录向上找 `downloads/*/*- NN [*.mkv`）或 `video` 直接给路径。`src`=源起点秒，`dur`=秒（帧数 = round(dur×24000/1001)）。模型首次使用从 HF 取，缓存在 `$AE_CACHE`（默认 `~/.cache/ae-precomp`，原始抠像/背景板/深度按 源+参数 哈希缓存，改特效参数重渲不重算）。

| effect | 关键参数 |
|---|---|
| `freeze_pop` | `freeze_at`（秒，绝对源时间）、`hold`（秒，默认 0.6）、`behind` `burst`/`speedlines`/null、`bg{darken,blur,desat,tint,z1}`、`fg{stroke,glow_sigma,glow_color,s1,drift}`、`pop_frames`、`flash`、`resume_flash` |
| `parallax` | `cam{z0,z1,x0,x1,y0,y1,ease}`、`fg_rate`(1.5)、`bg_rate`(0.5)、`bg_blur`（σ 或 [起,止]）、`plate{mode:static/frame}`、`motion_blur{shutter,max_samples}` |
| `depth_dolly` | `cam{z0,z1,x0,x1}`、`depth_gain`、`focus`(0=地平线锁定)、`overscan`、`motion_blur` |
| `text_behind` | `text{text,font,size,color,stroke,pos,tracking}`、`anim{in_frames,from_scale,from_dy}`、`text_rate`(0.6)、`cam` |
| `godrays` | `center` [fx,fy] 或 `auto`（全片最亮小团，锁定）、`light{threshold,length,strength,tint,passes,ang}`、`shafts`、`flicker`、`bloom` |

`freeze_pop` 时间线：`live` 帧实时 → 弹出（闪白 + 背景压暗 + 人物描边弹出）→ 保持 `hold` 帧 → 回到源时间 `freeze_at+hold` 实时继续（首 3 帧带衰减闪白）。例：E01 src 1278.82、dur 1.88、freeze_at 1279.80、hold 0.6 → 45 帧。

## 三、实测（Apple Silicon，机器负载均值 >180，数字偏悲观）

| 镜头 | 效果 | s/帧 | 备注 |
|---|---|---|---|
| E01 1278.82 1.88s | freeze_pop | 6.3 | 45 帧；抠像 56 s + LaMa 73 s（一次性，缓存） |
| E14 1286.15 3.56s | parallax | 6.2 | 85 帧；抠像时域平滑后闪烁见下 |
| E14 同上 | text_behind | 2.9 | 抠像已缓存 |
| E03 1146.85 3.58s | depth_dolly | 1.6 | 86 帧；深度 1 帧 |
| E12 1310.70 1.56s | godrays | 2.4 | 37 帧 |

## 四、何时使用（英雄拍点）与参数取舍

- **定格抠像**：拍点=招式顶点/回头/宣言；0.4–0.7 s；之后必须立刻恢复动作。每片 ≤2 次。
- **拉镜（视差）**：拍点=情绪走向“看向远方”；推幅 z1 ≤ 1.15，`fg_rate/bg_rate` 约 3:1；只用于几乎静止的镜头（后背、凝视）。
- **深度拉镜**：纯风景过渡段；`depth_gain` 0.8–1.5，x 位移 ≤3% 宽；人物镜头不用（深度图会撕人物）。
- **字在主体后**：片名、主题词；字号别大到被主体整个吃掉（中间字符消失）；偏离主体中线放置。
- **体积光**：烛火/点光源亮起的瞬间；`strength` 先小后加，射线亮度随火焰亮度门控。
- **径向缩放转场**：两镜头轴线/运动方向一致时；每片 ≤3 次。

## 五、QA 检查（每个预合成必做，且要看图）

1. **抠像闪烁指标**（`out.json` 的 `flicker`）：光流补偿后的相邻帧掩膜差，`mad_flowcomp_edge`（边缘带）。参考：E06 低机位 0.0143 → 平滑后 0.0074（-48%）；E14 背影 0.0048 → 0.0034；E01 定格窗口 0.0262 → 0.0222。**>0.015 看图复核，>0.03 换镜头或改 roi**。
2. **光晕（halo）检查**：把抠像叠在洋红底上看 1:1 边缘（`matte` 效果 + `qa_matte_sheet`）；白边/发丝亮线=未去污染，调 `matte.choke`、`decontaminate`。
3. **补背景检查**：看背景板 `_plate` 或把前景位移到极端帧，找涂抹、重复纹理、线稿断裂；洞占比 >35% 要换镜头或改 `plate.mode`。
4. **帧数检查**：`frames=N` 必须等于 round(dur×24000/1001)，Writer 已强校验。
5. **接口检查**：预合成接入后再跑 `cutguard.py`，保持期结束的闪白不得被当作杂帧——设计性闪白 ≤3 帧并登记。

## 六、失败模式

- 抠像把**对手/第二角色**一并抠出（E01：小丑也被描边）——一般可接受（双人定格），否则用 `matte.roi`。
- 作画拖影帧（半透明动态模糊）抠像半透明，补背景后出现“幽灵腿”（E01 小丑的腿）：换相邻更干净的帧作为定格点（`freeze_at` ±1 帧）。
- 源画面自带闪白/光效帧上做定格，背景会发白：避开源的闪白帧。
- 小面积高光做径向模糊=只有光晕；射线需要角向调制层。
- 运动镜头用 `plate.mode=static` 会得到鬼影背景——必须用 `frame` 或不用视差。
- LaMa 在 CPU 上跑（MPS 缺 FFT）；批量英雄镜头先跑抠像缓存，再调参。
- 机器繁忙时（load>100）实际耗时翻倍；预合成放离线批处理，不要在剪辑迭代里重复触发。
