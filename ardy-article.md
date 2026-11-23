<dl class="study-facts">
  <div><dt>语音 Demo</dt><dd>120 帧</dd></div>
  <div><dt>G1 动作生成</dt><dd>36 段</dd></div>
  <div><dt>SONIC 追加对照</dt><dd>108 次</dd></div>
</dl>

<h2 id="demo">Demo · 三条口令，一段连续动作</h2>

Whisper tiny.en 转写三条合成英文口令，程序把前进、转向和停止映射到地面路径。ARDY 使用上一块动作作为历史，逐块生成 27 关节人体骨架。

<figure>
  <video controls playsinline preload="metadata" width="1160" height="580" aria-label="三条语音口令驱动 ARDY 连续骨架"><source src="assets/ardy/voice-path.mp4" type="video/mp4"></video>
  <figcaption>6 秒，20 FPS。左边是骨架，右边是目标路径与生成轨迹。可打开声音听三条测试口令。初版左转口令的路径实际向右，追加实验校正了这个方向。</figcaption>
</figure>

同一个种子下，语音转写和手填指令映射到同一路径，4 步推理生成的骨架坐标完全一致。4 步与 10 步的根节点平均路径误差分别是 **3.67 cm** 和 **4.33 cm**。首窗之后，生成一个 2 秒动作块分别用 **131 ms** 和 **259 ms**。4 步动作模型峰值分配显存约 **890 MiB**。

<h2 id="interruption">进阶 · G1 在动作中途接到新口令</h2>

三种指令到达时机覆盖边界前、刚错过边界和快速连续改令。每种条件跑 3 个种子，每段 9.6 秒、25 FPS。H8 每次生成 8 帧（0.32 秒），H52 每次生成 52 帧（2.08 秒）。路径前视沿当前指令外推，语音转写到达后再更新。

| 检查点 | 路径前视 | 指令切换 | 根节点路径误差 | 平均指令排队 | 执行的中途指令 | 生成帧数／播放帧数 |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| H8 | 8 帧 | 整块播放 | 146.27 cm | 157 ms | 6/6 | 1.00× |
| H52 | 52 帧 | 整块播放 | 1.93 cm | 774 ms | 5/6 | 1.08× |
| H8 | 52 帧 | 整块播放 | 0.89 cm | 157 ms | 6/6 | 1.00× |
| H52 | 52 帧 | 4 帧边界重规划 | 1.37 cm | 104 ms | 6/6 | 1.30× |

**短窗需要足够的路径前视。** 同一 H8 权重从 8 帧前视加到 52 帧后，平均路径误差从 **146.27 cm** 降到 **0.89 cm**。

**长窗可以在 4 帧边界重规划。** 同一 H52 权重在晚到的停止样例中，排队从 **1.80 秒**降到 **44 毫秒**。从识别出停止到应用停止约束，根节点走过的距离从三种子的平均 **0.98 米**降到 **2.5 厘米**。代价是为每个实际播放帧生成约 1.30 帧。

排队从转写产出到新约束进入回放帧计算。口令的识别耗时和模型的生成耗时分别记录在数据中。

### 噪声下先检验指令入口

对 6 条合成语音各测干净、10 dB 和 0 dB 白噪声。三条支持的行走口令依次通过 **3/3、2/3、1/3**。0 dB 时，`Stop.` 被转写成 `Oh.`，白名单拒绝这条输入。干净录音里的 `Bow down and stand up.` 被转写成 `I'll now extend up.`。

<h2 id="simulation">社区 · G1 参考接到 SONIC</h2>

用 ARDY 官方转换器导出 25 Hz 的 G1 qpos，逐帧核验 6 段代表轨迹。公开社区适配器把其中一段转换为 **554 帧、50 Hz** 的 SONIC 参考。36 列 qpos 由根位置、WXYZ 四元数和 29 个关节角组成。晚到停止样例有 **72/240** 帧超出至少一个关节限位，最大超限约 **0.048 rad**，出现在左踝横滚关节。

<figure>
  <video controls playsinline preload="metadata" width="640" height="360" aria-label="ARDY G1 的运动学回放"><source src="assets/ardy/g1-playback.mp4" type="video/mp4"></video>
  <figcaption>晚到停止样例。MuJoCo 按 ARDY 导出的 qpos 逐帧显示 G1 参考动作。</figcaption>
</figure>

用 HumanTracker 的 MuJoCo 后端运行 NVIDIA SONIC 的 CPU ONNX 策略。三组整块播放参考和三组重规划参考都跑了 479 个控制帧，控制 50 Hz，物理步长 1 ms。

| 场景 | 整块播放参考的根位置误差 | 重规划参考的根位置误差 | 整块播放参考的关节 MAE | 重规划参考的关节 MAE |
| --- | ---: | ---: | ---: | ---: |
| 边界前改令 | 1.35 m | 1.30 m | 6.58° | 6.89° |
| 刚错过边界 | 1.35 m | 1.33 m | 6.80° | 8.49° |
| 连续改令 | 1.82 m | 1.44 m | 7.48° | 9.39° |

晚到停止样例的重规划参考把生成端的停令排队降到 44 ms。SONIC 跟踪这段参考时，根位置的平均误差仍为 **1.33 m**。这一步把语音响应问题和机器人轨迹跟踪问题区分开。

<figure>
  <video controls playsinline preload="metadata" width="768" height="360" aria-label="SONIC 闭环仿真的参考路径、实际路径和误差"><source src="assets/ardy/sonic-tracking.mp4" type="video/mp4"></video>
  <figcaption>整块播放的晚到停止样例。蓝线为参考，橙线为 SONIC 在 MuJoCo 的实际轨迹。右图同步显示两者的平面距离。</figcaption>
</figure>

<h2 id="sonic-latency">追加实验 · SONIC Default 与 Low latency</h2>

**H8 配 Low latency 的主要收益是少补参考帧、关节跟得更准。** H8 保留 52 帧路径前视并按块送入时，9 对样例的缺帧率从 **89.0% 降到 36.7%**，关节 MAE 从 **6.68° 降到 5.14°**。目标路径 MAE 从 **0.551 m 降到 0.525 m**，6/9 段有所改善。

两套 SONIC 使用各自公开的 ONNX 编解码器和 G1 观测配置。两套都取 10 个参考样本。Default 每隔五个 50 Hz 控制帧取一次，最远读到当前后 **900 ms**。Low latency 每个控制帧取一次，最远读到 **180 ms**。H8 一块生成 320 ms，这给了两套控制器不同的可用参考范围。 [Default 配置](https://huggingface.co/nvidia/GEAR-SONIC/blob/6733128a3d8a523b1418b06bca3cdf61c8b0987f/observation_config.yaml) · [Low latency 配置](https://huggingface.co/nvidia/GEAR-SONIC/blob/6733128a3d8a523b1418b06bca3cdf61c8b0987f/low_latency/observation_config.yaml) · [取帧实现](https://github.com/NVlabs/GR00T-WholeBodyControl/blob/1e1ec4f5f27e6c3e03048f693bd7c60cce04afda/gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/src/g1_deploy_onnx_ref.cpp#L759)

沿用三种口令时序和三个种子，按正确的 G1 左转方向重生成 36 条参考。两套控制器使用同一初始姿态、同一成功送达的参考和同一 1 ms MuJoCo 物理步长。控制频率为 50 Hz，记录控制前状态与同一时刻的参考。 [仿真后端](https://github.com/GalaxyGeneralRobotics/HumanTracker/blob/492f128dc903d1c859d2ff535c549c149f9adda8/src/humantracker/eval/backends/sonic.py)

- **按块送入**在播放边界交付一块 ARDY 动作。缺少未来帧时保持最后收到的姿态，填充帧的参考关节速度置零。
- **完整参考**提前提供整条同一轨迹，用于检查两套策略在参考充足时的跟踪。
- **按 T4 计时送入**用逐块实测耗时和口令可用时刻计算送达时间，在虚拟 50 Hz 控制时钟上回放。CPU 编解码耗时单独测量。

表里的路径误差以口令规划的地面路径为目标，关节误差以 ARDY 输出的参考关节角为基准。缺帧率只统计仍位于原始轨迹范围内的未来采样请求。

36 条参考按块送入，另有 12 条完整参考和 6 条按 T4 计时送入的对照。每条都跑 Default 和 Low latency，共 **108 次闭环仿真**。表内箭头从 Default 指向 Low latency。

| ARDY 参考 | 未来缺帧率 | 目标路径 MAE | 关节 MAE |
| --- | ---: | ---: | ---: |
| H8，8 帧路径前视 | 89.0% → 36.7% | 1.474 m → 1.492 m | 3.69° → 3.22° |
| H8，52 帧路径前视 | 89.0% → 36.7% | 0.551 m → 0.525 m | 6.68° → 5.14° |
| H52，整块 | 22.9% → 5.1% | 1.413 m → 1.532 m | 8.11° → 5.67° |
| H52，4 帧边界重规划 | 25.1% → 6.3% | 1.232 m → 1.351 m | 7.87° → 5.31° |

H8 的**路径前视**决定了给下游的动作质量。在 8 帧路径前视组，两套 SONIC 的目标路径误差都在 1.5 米左右。路径前视增加到 52 帧后，ARDY 自身每次仍只生成 8 帧，实际闭环目标路径误差降到约 0.5 米。

<figure>
  <img src="assets/ardy/sonic-latency-comparison.png" width="1464" height="1000" loading="lazy" alt="H8晚到停止样例的默认与低延迟轨迹和误差，以及四组配对的未来缺帧率和目标路径误差变化">
  <figcaption>上图是 H8 的晚到停止样例，这一段 Default 走得更贴近路径。下图给出四组汇总，右下柱低于零表示 Low latency 降低了目标路径误差。</figcaption>
</figure>

| H8，52 帧路径前视 | 配对数 | 目标路径 MAE | 未来缺帧率 |
| --- | ---: | ---: | ---: |
| 完整参考 | 3 | 0.528 m → 0.412 m | 0.0% → 0.0% |
| 按块送入 | 9 | 0.551 m → 0.525 m | 89.0% → 36.7% |
| 按 T4 计时送入 | 3 | 0.551 m → 0.470 m | 13.8% → 1.9% |

按 T4 实测时序预生成部分未来动作时，H8 的 Default 也能拿到更多参考。该组 Low latency 的缺帧率从 13.8% 降到 1.9%，目标路径误差从 0.551 m 降到 0.470 m。

同一台 Colab CPU 上，H8 按块送入组的 ONNX 单步中位数为 **17.7 ms → 31.5 ms**，P95 为 **30.1 ms → 52.7 ms**。G1 的 50 Hz 控制周期为 20 ms，Low latency 在这台 CPU 上的单步中位数超过了该周期。上述 900 ms、180 ms 是控制器读取参考的时间跨度。

H52 的两组参考在前 2 秒较低一侧的脚底标记高度中位数约为 17.8 厘米，H8 的 52 帧路径前视组约为 0.2 厘米。两套 G1 策略以关节位置、关节速度和相对根朝向为输入，仿真实际走过的根轨迹另行评分。

[全部逐次指标](assets/ardy/sonic-latency-study.json) · [H8 晚到停止轨迹 CSV](assets/ardy/sonic-latency-h8-trace.csv) · [闭环对照代码](assets/ardy/sonic-latency-replay.py)

<h2 id="round2-llm2vec">第二轮 · LLM2Vec 原句驱动的 G1 动作</h2>

六条英文指令分别跑三种输入和三个种子，完成 **54 次主闭环**。另加 **3 次语音闭环**。C 组用上真实文本后，ARDY 的平均目标路径误差仍为 **1.09 cm**。上肢语义的表现随指令而变，其中停走加挥手和双臂抬举给出了不同的结果。

本轮固定官方 ARDY G1 H8、25 Hz、8 帧生成窗、4 帧 Patch 和 52 帧路径前视。沿用上一轮的四步扩散和文本、路径 CFG 权重各 2。SONIC 采用原版 G1 Low-Latency ONNX，控制时钟 50 Hz，MuJoCo 物理步长 1 ms。六条指令各使用三个既有种子，每种输入运行 18 条参考。

A 组只给路径。B 组把原句送入官方 LLM2Vec，空间约束为空。C 组同时接入原句的官方向量和对应路径。P05 的目标先前进，3.52 秒开始减速，4 秒到静止区间。A 与 C 对同一指令使用相同路径。

官方编码器在高内存 CPU 上使用 BF16，并将 FP32 向量及有效掩码传给 T4 的 ARDY。G1 原始参考为 25 Hz。25→50 Hz 使用平移和关节线性插值、WXYZ 四元数 SLERP 和 MuJoCo 的位置差分计算速度。每个控制时刻只能读取当时已到达的参考，未来不足时保持最后可用的姿态。闭环站立与滑动统计使用 MuJoCo 模型中地面与脚部碰撞体的接触。

本次视频展示实际生成关节或 MuJoCo 闭环测得的骨架。手腕高度、脚部接触等数值作为人工评审的定位线索，三项 1–5 分仍留空。

### 同种子文本验证与 CFG

同种子、同样使用 Text Only 的两条烟测指令产生了不同向量，余弦相似度为 **0.769**，对应关节点位置的平均距离为 **0.509 m**。P04 保持相同文本、路径和种子，文本 CFG 从 2 改到 0 时，平均姿态变化 0.126 m。空间 CFG 改到 0 时，变化 0.183 m，目标路径误差从 1.74 cm 增至 12.62 cm。

| 条件 | 条数 | ARDY 目标路径 MAE | SONIC 根轨迹 MAE | 关节 MAE | 航向 MAE |
| --- | ---: | ---: | ---: | ---: | ---: |
| A · Path Only | 18 | 1.04 cm | 0.487 m | 4.78° | 1.83° |
| B · Text Only | 18 | 无预设路径 | 0.288 m | 4.08° | 1.53° |
| C · Text + Path | 18 | 1.09 cm | 0.391 m | 5.67° | 1.97° |

SONIC 根轨迹 MAE 以上游 ARDY 参考为基准。关节角和根航向在同一 50 Hz 控制时刻比对。

### 停止与上肢动作

P05 是这轮最有区分度的例子。文本组和文本加路径组的右腕波动都在 12 cm 左右，路径组约为 2.7 cm。Text Only 在 5–8 秒仍以约 0.433 m/s 移动。加上允许停车的路径后，末段根速度约为 0.005 m/s，同时保留了右腕运动。

| P05 条件 | 1–3 秒根速度 | 5–8 秒根速度 | 右腕相对肩的运动波动 |
| --- | ---: | ---: | ---: |
| A · Path Only | 0.499 m/s | 0.005 m/s | 2.7 cm |
| B · Text Only | 0.451 m/s | 0.433 m/s | 12.2 cm |
| C · Text + Path | 0.502 m/s | 0.005 m/s | 12.2 cm |

双臂抬举用「双腕均高于肩部 3 cm」作为定位指标。P04 各组在这个指标上的帧占比都是 0%。3 秒的代表帧中，Text Only 的双臂仍在肩线下方。逐段的语义一致性、自然性和物理执行质量评分留待人工审核。

<figure>
  <img src="assets/ardy/r2/r2-comparison.png" loading="lazy" alt="三组根轨迹误差、路径误差、双腕高度代理以及停走速度对照">
  <figcaption>主实验每组 18 条。P04 的双腕高度是人工复查线索，P05 的速度来自 ARDY 参考。</figcaption>
</figure>

<figure>
  <video controls playsinline preload="metadata" aria-label="P05 语音输入。视频先播放合成录音，再播放 ARDY 参考和 SONIC 闭环回放。" width="868" height="474"><source src="assets/ardy/r2/r2-p05-spoken-sonic.mp4" type="video/mp4"></video>
  <figcaption>P05 语音输入。视频先播放合成录音，再播放 ARDY 参考和 SONIC 闭环回放。</figcaption>
</figure>

三段合成录音先由 Whisper 实际转写，再把得到的原句送进同一 LLM2Vec。ASR 实耗为 1.03–1.87 秒，T4 首块生成和转换为 0.067–0.339 秒。当前跨会话批流程从音频就绪到首块参考为 161.9–163.4 秒，包含跨机会话调度。P05 的转写与书面指令逐字相同，同种子的生成 qpos 逐项最大差为 0。

以骨盆低于 0.35 m 且持续 5 个控制帧为跌倒判据，54 条主实验记录跌倒 0 次。路径执行仍有大偏差的样例。C_text_path_P03_20261122 的 ARDY 目标路径 MAE 为 2.11 cm，SONIC 实际目标路径 MAE 为 0.928 m。

<figure>
  <video controls playsinline preload="none" aria-label="P03 的路径偏差案例。左边是参考与实际骨架，右边是两条地面轨迹。" width="868" height="474"><source src="assets/ardy/r2/r2-large-tracking-error.mp4" type="video/mp4"></video>
  <figcaption>P03 的路径偏差案例。左边是参考与实际骨架，右边是两条地面轨迹。</figcaption>
</figure>

### 六条指令的代表回放

<details>
<summary>P01 · 慢走</summary>
<figure>
  <video controls playsinline preload="none" aria-label="Text + Path，种子 20261121。" width="868" height="474"><source src="assets/ardy/r2/r2-p01-text-path-sonic.mp4" type="video/mp4"></video>
  <figcaption>Text + Path，种子 20261121。</figcaption>
</figure>


</details>

<details>
<summary>P02 · 边走边挥右手</summary>
<figure>
  <video controls playsinline preload="none" aria-label="Text + Path，种子 20261121。" width="868" height="474"><source src="assets/ardy/r2/r2-p02-text-path-sonic.mp4" type="video/mp4"></video>
  <figcaption>Text + Path，种子 20261121。</figcaption>
</figure>
<figure>
  <video controls playsinline preload="none" aria-label="Text Only 的运动学对照，同一随机种子。" width="868" height="474"><source src="assets/ardy/r2/r2-p02-text-only.mp4" type="video/mp4"></video>
  <figcaption>Text Only 的运动学对照，同一随机种子。</figcaption>
</figure>

</details>

<details>
<summary>P03 · 小心走小步</summary>
<figure>
  <video controls playsinline preload="none" aria-label="Text + Path，种子 20261121。" width="868" height="474"><source src="assets/ardy/r2/r2-p03-text-path-sonic.mp4" type="video/mp4"></video>
  <figcaption>Text + Path，种子 20261121。</figcaption>
</figure>


</details>

<details>
<summary>P04 · 走路时双臂抬起</summary>
<figure>
  <video controls playsinline preload="none" aria-label="Text + Path，种子 20261121。" width="868" height="474"><source src="assets/ardy/r2/r2-p04-text-path-sonic.mp4" type="video/mp4"></video>
  <figcaption>Text + Path，种子 20261121。</figcaption>
</figure>
<figure>
  <video controls playsinline preload="none" aria-label="Text Only 的运动学对照，同一随机种子。" width="868" height="474"><source src="assets/ardy/r2/r2-p04-text-only.mp4" type="video/mp4"></video>
  <figcaption>Text Only 的运动学对照，同一随机种子。</figcaption>
</figure>
<figure>
  <video controls playsinline preload="none" aria-label="Path Only 的运动学基线，同一随机种子。" width="868" height="474"><source src="assets/ardy/r2/r2-p04-path-only.mp4" type="video/mp4"></video>
  <figcaption>Path Only 的运动学基线，同一随机种子。</figcaption>
</figure>
</details>

<details>
<summary>P05 · 走后停下再挥手</summary>
<figure>
  <video controls playsinline preload="none" aria-label="Text + Path，种子 20261121。" width="868" height="474"><source src="assets/ardy/r2/r2-p05-text-path-sonic.mp4" type="video/mp4"></video>
  <figcaption>Text + Path，种子 20261121。</figcaption>
</figure>
<figure>
  <video controls playsinline preload="none" aria-label="Text Only 的运动学对照，同一随机种子。" width="868" height="474"><source src="assets/ardy/r2/r2-p05-text-only.mp4" type="video/mp4"></video>
  <figcaption>Text Only 的运动学对照，同一随机种子。</figcaption>
</figure>

</details>

<details>
<summary>P06 · 左腿受伤式跛行</summary>
<figure>
  <video controls playsinline preload="none" aria-label="Text + Path，种子 20261121。" width="868" height="474"><source src="assets/ardy/r2/r2-p06-text-path-sonic.mp4" type="video/mp4"></video>
  <figcaption>Text + Path，种子 20261121。</figcaption>
</figure>


</details>

### 脚底、窗口和运行耗时

C 组在第一个 0.32 秒窗口内，参考下侧足点高度的试次中位数为 1.09 cm，随后至第 2 秒为 0.65 cm。Root 的 Y-up 到 Z-up 坐标转换逐帧最大差为 0 m。对 C_text_path_P03_20261122 单独降低初始骨盆 6.35 cm，参考保持相同，首两秒承重接触占比从 99% 变到 96%，根参考跟踪 MAE 从 0.929 m 变到 0.895 m。

C 组的窗边界关节转角步长 P95 为 4.15°，窗内为 3.92°。三组已到播放时刻的当前参考帧耗尽率均为 0，C 组未来槽缺失约为 0.008%。播放时钟为 50 Hz，实测 CPU ONNX 中位耗时已经超过 20 ms 的控制周期。整句在试次开始时输入，在线改口触发重规划和硬实时部署留待验证。

| 条件 | ARDY 生成 P50／P95 | 逆变换与导出 P50／P95 | SONIC ONNX P50／P95 |
| --- | ---: | ---: | ---: |
| A · Path Only | 71.5／85.1 ms | 5.5／7.7 ms | 27.6／47.8 ms |
| B · Text Only | 69.7／79.0 ms | 5.6／7.3 ms | 30.4／53.5 ms |
| C · Text + Path | 77.9／85.7 ms | 5.8／7.1 ms | 30.3／53.5 ms |

[逐次指标 CSV](assets/ardy/r2/r2-trial-metrics.csv) · [实验配置](assets/ardy/r2/r2-config.json) · [汇总 JSON](assets/ardy/r2/r2-summary.json) · [视频索引](assets/ardy/r2/r2-video-index.json)

官方版本为 ARDY G1 H8、Meta Llama 3 8B Instruct 和其两级 McGill LLM2Vec 适配器，以及 GEAR-SONIC G1 Low-Latency ONNX。Built with Meta Llama 3. [ARDY 固定版本](https://github.com/nv-tlabs/ardy/tree/e706e27acc88070918308a10922b8f7174d0825e) · [LLM2Vec](https://github.com/McGill-NLP/llm2vec) · [SONIC 低延迟权重](https://huggingface.co/nvidia/GEAR-SONIC/tree/6733128a3d8a523b1418b06bca3cdf61c8b0987f/low_latency)

<h2 id="record">复跑与实验数据</h2>

[打开 Colab 复跑笔记本](https://colab.research.google.com/github/approchin/approchin.github.io/blob/main/ardy-assets/ardy-reproduce.ipynb) · [逐次实验指标](assets/ardy/study-data.json) · [代表性轨迹与关节数据](assets/ardy/representative-trajectories.zip)

语音阶段使用三条固定路径口令。ARDY 的自由文本入口使用 LLM2Vec，需要获得 Meta Llama 权重访问权限。动作阶段直接载入 NVIDIA 的 Core H40、G1 H8 和 G1 H52 权重。[官方项目](https://research.nvidia.com/labs/sil/projects/ardy/) · [官方代码](https://github.com/nv-tlabs/ardy/tree/e706e27acc88070918308a10922b8f7174d0825e) · [模型权重](https://huggingface.co/collections/nvidia/ardy)

社区实验复用 G1 参考转换器、HumanTracker 仿真后端和 NVIDIA SONIC ONNX 权重。[G1 参考转换器](https://github.com/liylo/ardy/tree/b75d8c56b65e05857146f7e65dd4f87caeb78ed8) · [HumanTracker](https://github.com/GalaxyGeneralRobotics/HumanTracker/tree/492f128dc903d1c859d2ff535c549c149f9adda8) · [GEAR-SONIC 权重](https://huggingface.co/nvidia/GEAR-SONIC)
