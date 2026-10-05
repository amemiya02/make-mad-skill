# 台词/对白隔离：把角色声音从剧集混音里干净地取出来

本文件来自一次真实返工：成片里的台词是直接从剧集音轨截取的，用户一听就发现 **台词下面还躺着原作 BGM**——一条台词刚说完，底下是另一首曲子的残响，和成片 BGM 打架，整个"歌里插台词"的设计就破了。台词是 MAD 里最贵的稀缺资源，它必须是"干声"。

## 一、为什么必须做

- 剧集音轨 = 对白 + BGM + 音效 + 环境声（+混响）。成片自己有 BGM，叠上原作 BGM 就是两首曲子同时响；即使压低，原曲的和声/鼓点/持续音也会和成片调性冲突、遮蔽节奏。
- 人耳对"台词停顿处突然安静/突然有底噪"极敏感。门限做得糙（硬切）会掐字尾，不做门限则停顿里全是原作环境声。
- 目标（专业剪辑师用 UVR5 + Audition/iZotope RX 得到的结果）：**说话时只有人声；非说话处接近静音（≤ -80 dB，实际是数字零）；字头字尾完整；无金属味。**

## 二、专业工具链 ⇄ 本地等价物

| 剪辑师做法 | 本地等价 | 作用 |
|---|---|---|
| UVR5 + Mel-Band RoFormer 人声模型 | `mel_band_roformer_vocals_becruily.ckpt`（audio-separator 后端，44.1 kHz，MPS/CPU） | 第一阶段：分出人声，BGM/SFX 主体在此被去除 |
| RX Dialogue Isolate / Voice De-noise / Dialogue Contour | DeepFilterNet3（`deepfilternet`，48 kHz，全强度），**hybrid 用法**（见下） | 第二阶段：去掉人声干里残留的平稳成分（持续音/和弦底/空调/混响底） |
| Audition/RX 的 Gate / Expander + 手工包络 | Silero-VAD + 能量尾延 + 余弦斜坡门限 | 第三阶段：非说话处压到 -80 dB，词尾保留 |
| 试听、频谱图检查 | `analysis/dialogue-iso/spec_*.png`（librosa 频谱 + 10 ms 能量曲线） | 验收（agent 听不了，必须看图+数字） |

模型对比（均为 E14/E12 实测；`analysis/dialogue-iso/shootout/` 有全部 stem）：
- `mel_band_roformer_vocals_becruily`（Mel-RoFormer）：干净、无乐器残留，**默认选用**；人声段保真度最高。
- `model_bs_roformer_ep_317_sdr_12.9755`（BS-RoFormer 1297）：保真，但会把持续的和声垫/钟声当人声保留（E14 间隙仅压 ~15 dB）。只用作**独立验收模型**。
- `vocals_mel_band_roformer`、`mel_band_roformer_vocals_fv4_gabox`：与 becruily 近似，间隙更脏。
- htdemucs：整体偏脏，间隙残留明显（-60~-80 dB 级），不用。
- `denoise_mel_band_roformer_aufr33`（RoFormer Denoise）：**对"音乐残留"几乎无效**（E12 实测与输入差 <0.001），它只去噪声。保留为 `--denoise roformer` 选项，但默认不用（省 20 s/条）。
- `mel_band_roformer_denoise_debleed_gabox` / `UVR-DeNoise`：取错 stem 会得到近静音或不变，注意按文件名括号取 stem；不作默认。
- DeepFilterNet3：E12 917.96 实测词间隙 -50 → -92 dB，语音段 ±1 dB，无明显金属味。**但对喊叫/非词汇人声会吃掉 7–18 dB**（全程 DFN 时 E14 1337.39 -17.9 dB、E11 1264.64 -7.6 dB、E12 987.55 -6.7 dB）。
- **默认 `hybrid`**：先测 DFN 在强语音帧上的 250–4000 Hz 损失，≤1.5 dB 则全程用 DFN；否则只在"人声 stem 电平 < 语音 p95 − 15 dB"的弱帧（词间/尾音/底噪）用 DFN 输出（30 ms 交叉淡化），语音本身保留未降噪的人声 stem。结果：15 条的 `sp_delta` 全部在 -2.0…0 dB，词间隙 <-110 dB。

## 三、命令与参数

```bash
# 依赖：audio-separator（numpy>=2）所在 venv；DeepFilterNet（numpy<2）另一个 venv，以子进程调用
AUDIO_PY=/path/.venv-audio/bin/python
export DIALOGUE_DFN_PYTHON=/path/.venv-dfn/bin/python
$AUDIO_PY scripts/fxkit/dialogue_clean.py 14 1335.51 1338.95 out.wav --src 14=/path/ep14.mkv
$AUDIO_PY scripts/fxkit/dialogue_clean.py --list lines.tsv      # 每行: ep a b out.wav ；批处理只加载一次模型
```

主工程里（主 venv 没有 audio-separator）：

```python
import dialogue_clean
dialogue_clean.set_sources({'14': '/path/ep14.mkv'})   # 或 set_resolver(fn) / DIALOGUE_EPISODE_GLOB
x = dialogue_clean.load_clean('14', 1335.51, 1338.95)  # (n,2) float32 @48 kHz, n == round((b-a)*48000)
```

`load_clean` 缓存命中直接读 WAV；未命中则用 `DIALOGUE_AUDIO_PYTHON` 的解释器子进程跑完整流程，失败**直接抛异常**，绝不回退到原始音频。缓存键 = hash(片源文件名, a, b, 上下文, 模型名, 降噪方式, 门限参数, 版本号)，改模型/参数/版本自动失效。

| 参数 | 默认 | 说明 |
|---|---|---|
| `pad` | 6.0 s | 两侧上下文。分离模型需要音乐语境；上下文太短时开头会残留/吞字。处理后裁回 [a,b] |
| `model` | becruily | 第一阶段人声模型 |
| `denoise` | `hybrid` | `hybrid` / `dfn` / `roformer` / `none`；`hybrid_db`(15) 为弱帧阈值 |
| `overlap` | 2 | RoFormer 重叠窗，4–8 更平滑但慢 2–4 倍 |
| `vad_threshold` | 0.35 | Silero 语音概率阈值（低一点更不易漏尾音） |
| `tail_db` / `tail_max` | 30 dB / 0.40 s | 门限边缘向外延伸，直到能量低于语音 p95−30 dB，最多 0.4 s（保词尾） |
| `preroll` / `hold` | 0.04 / 0.12 s | 提前开门（辅音爆发）/ 延后关门（尾音混响） |
| `merge` | 0.25 s | 短于此的间隔不关门（避免字间"抽吸"） |
| `attack` / `release` | 25 / 40 ms | 余弦斜坡，禁止硬切 |
| `floor_db` | -80 | 非说话处增益 |

裁剪回 [a,b] 时首尾各 3 ms 淡变去爆音。输出长度严格 `round((b-a)*48000)` 采样。

## 四、实测结果（15 条台词，M 系列 Apple Silicon，机器负载很高时）

见 `analysis/dialogue-iso/metrics_final.json`（脚本 `final_metrics.py`），摘要表在本文末"实测表"。耗时：每条约 32–53 s（vocal 模型 ~20–30 s，DFN ~8–12 s，其余 <5 s；机器负载 >100 时）；整批 15 条约 9–10 分钟，缓存命中 <0.1 s。

## 五、陷阱

1. **掐字尾**：把字幕时间码或 VAD 边界直接当门。VAD 在气声、拖音、"ん…"处提前结束。必须有 tail 延伸 + hold + 斜坡；检查看 10 ms 能量曲线在词尾是否平滑衰减而不是悬崖。
2. **金属味/水声**：对已分离的人声再叠多次强降噪（RoFormer×N、DFN×N）会出现谐波丢失。单次 DFN、语音段能量变化应在 ±2 dB 内（`sp_delta`）。
3. **混响/房间声**：人声 stem 里会带角色所处空间的混响，门限 hold 太短会把混响尾巴切断，太长又把 BGM 残留放进来；0.12 s + 能量尾延是折中。
4. **叠在对白上的音效（金属撞击、爆炸、脚步、笑声）**：与人声同频段的 SFX 会被模型当作人声保留；只能靠换更靠前/靠后的区间或字幕代替。若 SFX 持续到整句，不要硬救。
5. **非词汇人声（惨叫、喘息）**：Silero-VAD 可能判为非语音（E14 1337.39–1338.95 就是），按 VAD 做门限会整段被静音。本工具的尾延依赖能量；验收指标里用"VAD ∪ 能量"定义说话区，不要只信 VAD。
6. **上下文不足**：只切 [a,b] 送进模型，开头 0.5 s 常带着 BGM 或被吞；必须两侧各 ≥6 s，且不同 [a,b] 即使重叠也分别处理（缓存键含 a、b）。
7. **标题卡/音乐 sting 与台词重叠**（E14 1337.27+）：BGM sting 与人声同时出现。becruily + DFN 后看频谱：sting 的低频持续音和宽带冲击应消失；必须逐条看图而不是只信数字。
8. **相邻台词共用上下文**：不同行的 BGM 状态不同，单独处理每条而不是整段处理后再切。
9. **门限只在 -80 dB**：不是 -∞，拼接成片时与 BGM 混合没有问题；但不要再对台词做大幅增益（+20 dB 会抬出残留），增益交给 mix。
10. **别用 normalization**：分离时 `normalization_threshold=1.0`，保持不同 stem/不同台词的相对电平可比。

## 六、QA 清单（逐条台词，缺一不可）

- [ ] 缓存存在且长度 == round((b-a)*48000)，无 NaN，峰值 < -1 dBFS。
- [ ] 非说话处（距说话 ≥0.25 s）：中位 10 ms 帧电平 ≤ -80 dB（或相对原混音 ≥ 40 dB 下降）。
- [ ] 说话段 250–4000 Hz 电平相对原混音变化在 -3…0 dB 内（实测 -2.0…0）（过大说明吞字/过度处理）。
- [ ] 词间"门开"处的底噪比原混音低 ≥ 15 dB（`open_gap`；E12 917.96 DFN 前后 -50 → -92 dB）。
- [ ] 独立模型（BS-RoFormer 1297）对成品再分离：instrumental stem 相对 vocal stem ≤ -45 dB（`inst_rel`）。
- [ ] 看频谱图：成品里不应有水平的持续音线条、鼓点竖条，只有人声的谐波和辅音。
- [ ] 词头词尾：10 ms 能量曲线在 [字头 -40 ms，字尾 +120 ms] 内无断崖；人工对照字幕语音段。
- [ ] 特别台词（有标题卡/音乐 sting/SFX 的）单独看图。
- [ ] 失败即报错，从不静默回退原音。

## 七、实测表

（由 `analysis/dialogue-iso/final_metrics.py` 生成；列含义：`gap_mix/gap_out` 非说话处中位 10 ms 帧电平 dB（-200=数字零），`og_*` 门仍开的间隙处，`sp_delta` 说话段 250–4000 Hz 电平变化 dB，`inst_rel` 独立模型残留音乐相对人声 dB。）

| EP | a–b (s) | 说话 s | 间隙原混音 dB | 间隙成品 dB | sp_delta dB | inst_rel dB | 峰值 dBFS |
|---|---|---|---|---|---|---|---|
| E03 | 1261.69–1265.08 | 2.74 | -31.8 | <-120 | -0.9 | -55.8 | -9.9 |
| E03 | 1265.58–1267.84 | 1.71 | – | – | -2.0 | -56.9 | -11.4 |
| E03 | 1268.78–1272.55 | 2.43 | -36.0 | <-120 | -1.5 | -55.8 | -8.0 |
| E01 | 1244.73–1248.61 | 1.15 | -29.0 | <-120 | -0.7 | -61.4 | -9.1 |
| E01 | 1248.61–1251.80 | 2.60 | – | – | -1.1 | -61.2 | -8.0 |
| E12 | 897.60–903.00 | 3.30 | -49.9 | <-120 | -0.2 | -60.1 | -13.3 |
| E11 | 1264.64–1266.27 | 0.59 | -56.9 | <-120 | -0.1 | -60.9 | -10.6 |
| E11 | 1275.36–1278.25 | 2.49 | – | – | -0.1 | -60.3 | -9.5 |
| E11 | 1318.30–1321.50 | 2.12 | -50.8 | <-120 | -0.4 | -58.4 | -8.3 |
| E12 | 908.29–913.37 | 3.75 | – | – | -0.6 | -59.6 | -12.5 |
| E12 | 917.96–922.24 | 2.96 | -42.5 | <-120 | -0.7 | -23.9 | -13.0 |
| E12 | 981.40–984.00 | 1.95 | – | – | -1.3 | -60.0 | -12.8 |
| E12 | 987.55–991.55 | 2.88 | -34.5 | <-120 | -1.7 | -59.4 | -11.4 |
| E14 | 1335.51–1337.20 | 1.00 | -26.5 | <-120 | -0.8 | -60.5 | -5.1 |
| E14 | 1337.39–1338.95 | 0.85 | -26.9 | <-120 | -0.5 | -60.8 | -4.0 |

“–”＝该条几乎无非说话间隙（<0.1 s）。E12 917.96 的 inst_rel -23.9 dB 是独立模型把该条大量气声/喊叫判为"伴奏"所致（频谱图里词间已无持续音线条，词间隙 < -170 dB）；其余 14 条 ≤ -46 dB。E14 1337.39+（标题卡 sting 重叠）成品频谱只剩人声谐波，sting 的低频持续音/宽带冲击全部消失。

## Splicing a line (removing a pause, tightening to the music)

Clean the **whole take once** and slice the cleaned array; never call `load_clean` on each sub-range. The VAD gate (and the
separator's context) depends on the window, so a sub-range cleaned on its own can gate out a word onset (seen on E12 989.65–991.55:
the first 0.35 s of "可爱呢" was gated to −110 dB). Cut only inside measured silence (<−60 dB), fade 60–80 ms, and re-measure the
envelope of each piece at its new timeline position. If a line's tail would overlap the vocal re-entry, splice out pause time or move
the line earlier (when the speaker's mouth is not on screen) instead of extending the duck over the singing.
