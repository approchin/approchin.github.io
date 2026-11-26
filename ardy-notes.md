说完“向前走”又补一句“左转”时，机器人可能还在执行上一段动作。ARDY 要做的是接着已有的步态，生成一段能接上、也能向新目标走的参考动作。这篇笔记用 G1 H8 走一遍这条链路。动作频率是 25 Hz，每四帧打成一个 Patch，所以一窗 8 帧，正好两枚动作 Token。

## 1. 一窗动作怎样接到下一窗 {#overview}

<figure class="note-figure">
  <a href="assets/ardy/notes/01-ardy-overview.svg" aria-label="打开图 1 原图"><img src="assets/ardy/notes/01-ardy-overview.svg" width="1728" height="972" alt="ARDY 把 History、Current、Future、Text 和 Step 输入两阶段去噪，解码后的动作可以接回历史" fetchpriority="high"></a>
  <figcaption><strong>图 1</strong>　从已有动作和新指令出发，生成下一窗显式参考。保留下来的参考可接入下一次生成的历史。</figcaption>
</figure>

先记两个阶段。Stage 1 学会怎么打包和还原已有动作，根的全局运动保留显式值，身体动作压缩成 latent。Stage 2 把已有动作、当前窗草稿、窗外目标、文本和扩散步组织起来，用 Root 和 Body 两个 Transformer 反复修当前的两枚 Token。去噪结束，Stage 1 的 Decoder 把结果变回 8 帧显式参考。

窗外目标也会影响这一窗。比如用户要求第 20 帧到达某个路点，ARDY 当前仍只生成第 1–8 帧。它能提前看见路点，决定这 8 帧里怎么起步、要不要开始转身。下一窗接着已保留的动作再做一次。语音复现测试了两种入口。一种把语音转写的文本交给编码器，另一种把前进、转向和停止这几类固定口令映成地面路径。[ARDY 论文 §3.3–3.4](https://arxiv.org/html/2607.08741#S3.SS3) · [语音复现与 G1 跟踪实验](../)

## 2. Stage 1 怎样把四帧装进一枚 Token {#tokenizer}

<figure class="note-figure">
  <a href="assets/ardy/notes/02-root-body-motion-tokenizer.svg" aria-label="打开图 2 原图"><img src="assets/ardy/notes/02-root-body-motion-tokenizer.svg" width="1728" height="972" loading="lazy" decoding="async" alt="四帧显式动作分成 Global Root 20 维和 Body latent 128 维，拼成 148 维 Token，解码时 Global Root 直通并派生 Local Root"></a>
  <figcaption><strong>图 2</strong>　四帧 Global Root 直通，Body 经过编码和量化。解码时同一枚 Hybrid Token 还原成四帧动作。</figcaption>
</figure>

### 409 维里装了什么

G1 的这套动作骨架有 34 个节点，其中包括骨盆根、29 个驱动关节和 4 个末端节点。409 是每帧 Body 的特征数。最终转成 MuJoCo 的 `qpos` 时，根位置占 3 维，根姿态四元数占 4 维，加上 29 个关节角共 36 维。[动作特征定义](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/motion_rep/reps/ardy_motionrep.py#L49-L69) · [G1 骨架](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/skeleton/definitions.py#L286-L345) · [MuJoCo 导出](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/exports/mujoco.py#L186-L204)

| Body 特征 | 每帧组成 | 维数 |
| --- | --- | ---: |
| 非根节点位置 | 33 个节点的三维位置，减去根的水平平移 | 99 |
| 全局旋转 | 34 个节点 × 6D 旋转表示 | 204 |
| 全局线速度 | 34 个节点 × 三维速度 | 102 |
| 足部接触 | 左右脚各两处 | 4 |
| **合计** | | **409** |

Global Root 每帧保留 $[x,y,z,\cos\psi,\sin\psi]$，加上 Body 一帧共 414 维。四帧打包时，Global Root 的 20 维直接保留，Body 的 $4\times409=1636$ 维经 Encoder 变成 128 维。两路沿特征轴拼接，得到 $20+128=148$ 维 Hybrid Token。[混合动作表示](https://arxiv.org/html/2607.08741#S3.SS1) · [G1 H8 配置](https://huggingface.co/nvidia/ARDY-G1-RP-25FPS-Horizon8/blob/fb815e8021d700af523ac32d9851b7e489fbb60b/config.yaml)

### 512、因果注意力和 FSQ

Encoder 的数据流是 **1636 → 512 → 128**。512 是 Transformer 内部的隐藏宽度，Decoder 也有自己的 512 维骨干。128 是交给 Stage 2 的 Body latent 宽度。所谓因果，描述的是 Patch 之间的注意力。把 1–4、5–8、9–12 帧各打成一格时，中间一格可以读自己和第一格，第三格在这条注意力路径上被遮住。同一格的四帧在进入 Transformer 前已经拼到一起。[Tokenizer 结构](https://arxiv.org/html/2607.08741#S3.SS2) · [Encoder 实现](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/autoencoder/transformer.py#L106-L141)

FSQ（有限标量量化）给每个潜变量设定可取的刻度。G1 H8 的 128 个坐标各用 64 级，训练时用直通估计传过取整操作。它省去了学习向量码本和查找最近码字的步骤。论文观察到普通 AE 在较长生成窗上的训练容易不稳，采用了 FSQ。扩散在连续的归一化数值向量上加噪和去噪。最终解码前，预测的 Body latent 会反归一化，再裁剪并按刻度取整。[FSQ 原论文](https://arxiv.org/abs/2309.15505) · [ARDY 的 Tokenizer 消融](https://arxiv.org/html/2607.08741#S5.SS3) · [量化与解码实现](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/autoencoder/fsq.py#L191-L254)

**Encoder 先学会说一种 Decoder 听得懂的话。** Stage 1 把真实动作编码后还原，重建误差更新 Decoder 和 Encoder。脚滑损失用预测的足部接触为脚点速度加权，总损失中这一项乘以 0.01。Stage 2 固定预训练 Tokenizer，用真实的干净 Token 监督预测，再把解码出的身体与真实动作比较。我的理解是，先把 1636 维身体特征整理成 128 维固定刻度的表示，去噪器就能把学习容量更多用在步伐接续和身体如何配合路径上。推理时，最后一次去噪得到的 Body latent 也由这个 Decoder 还原成显式 Body。[ARDY 训练细节](https://arxiv.org/html/2607.08741#S3.SS5) · [Hybrid Token 解码](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/latent_utils.py#L67-L101)

### 腿怎么迈，取决于根这一拍怎么走

同一套步法搬到地图另一边，迈腿的方式可以照旧。走得更快、开始转身或骨盆压低时，手脚就得换一种配合。ARDY 在这条条件边上把 Global Root 转成每帧 4 维的 $[\dot\psi,v_x,v_z,y]$，即航向角速度、场景坐标下的水平速度和根高度。25 Hz 下，相邻两帧的 $x$ 从 0.40 m 变到 0.44 m，对应 $v_x=1$ m/s。Decoder 和 Body Transformer 都能直接读这组运动量。Global Root 仍负责放回绝对位置和航向。[Global→Local 实现](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/motion_rep/reps/base.py#L140-L183) · [论文表 2](https://arxiv.org/html/2607.08741#S5.T2)

SONIC 的训练里也有用重建约束动作表示的解码头。SONIC 部署时的控制 Decoder 读取 Token 与本体状态，给出这一拍的关节目标。ARDY 的动作 Decoder 交付的是一段参考，这段参考还可以送给下游跟踪器执行。[SONIC §3.2](https://arxiv.org/html/2511.07820#S3.SS2)

### 为什么这个模型用四帧一格

论文表 3 的 Rigplay 消融固定 40 帧生成窗、10 步去噪和 128 维 Body latent，对比了 1、4 和 8 帧 Patch。8 帧的纯文本 FID 更低，4 帧在脚滑和空间控制指标上更好。比如 4 帧和 8 帧的末端位置误差分别为 2.5 cm 和 7.0 cm。对 ARDY 的实时空间控制目标，四帧是一个折中。[论文表 3](https://arxiv.org/html/2607.08741#S5.T3)

这里的 FID 沿用 Fréchet Inception Distance 的算法。这个指标起初用于图像生成，得分由真实样本和生成样本两批特征的均值与协方差决定。ARDY 的 Rigplay 实验用基于 TMR 的动作评估器提取动作特征，FID 越低表示两批动作在该特征空间里的分布越接近。“纯文本”指生成时只给文字条件。表 3 中 4 帧与 8 帧 Patch 的纯文本 FID 分别是 0.027 和 0.022。[FID 原论文](https://arxiv.org/abs/1706.08500) · [ARDY 评估指标](https://arxiv.org/html/2607.08741#S5.SS1)

## 3. 同一个路点怎样跨过生成窗 {#conditioning}

<figure class="note-figure">
  <a href="assets/ardy/notes/03-history-current-future.svg" aria-label="打开图 3 原图"><img src="assets/ardy/notes/03-history-current-future.svg" width="1728" height="972" loading="lazy" decoding="async" alt="History、Current、Future 原始宽度分别为 148、3440、3312，各自投影到 1024，和 Text、Step 沿 Token 轴排成序列"></a>
  <figcaption><strong>图 3</strong>　G1 H8 的 Root Transformer 输入。三路的原始含义各自保留，Linear 统一宽度后再沿 Token 轴排列。</figcaption>
</figure>

| 输入类型 | 单枚 Token 的组成 | 宽度 |
| --- | --- | ---: |
| History | 干净 Global Root 20＋干净 Body latent 128 | **148** |
| Current | 带噪 Body latent 128＋覆写后的 Global Root 20＋显式 Body Goal 1636＋全特征 Mask 1656 | **3440** |
| Future | 显式 Global Root Goal 20＋显式 Body Goal 1636＋全特征 Mask 1656 | **3312** |

假设第 1–8 帧是当前窗。若目标落点在第 20 帧，它会进入第三个 Future Patch（第 17–20 帧）。这枚 Token 里，只填对应帧的根 $x,z$ 目标，并把相应 Mask 置为有效。其余位置保持未指定。目标、Mask 和时间位置一起进入 Transformer，给眼前两枚动作 Token 提供前视信息。[约束拼接](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/auto_latent_twostage_denoiser.py#L201-L279) · [Future 槽位](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/latent_utils.py#L192-L220)

若把同一个点提前到第 5 帧，它就进入 Current 的第二枚 Token。每轮去噪前，在同一归一化尺度上，用目标值覆盖 Mask 指定的带噪 Root 分量。其余分量沿用这轮带噪值。若 $r_k$ 是带噪 Root、$g_r$ 是目标、$m_r$ 是 Mask，送给网络的是

$$
\tilde r_k=(1-m_r)\odot r_k+m_r\odot g_r.
$$

Body Goal 保留完整的显式槽位，能明确指定“第 5 帧右手的位置”。公开位置约束接口在同一帧取得 Root 的 $x,z$，把右手水平坐标写成相对根的偏移，保留手的高度，并标记这组三维位置。128 维 Body latent 共同表示四帧身体动作，很难挑出一个坐标专门给那只手。于是模型读取带噪 Body latent、显式 Body Goal 和 Mask，再估计这一窗的干净 Body。[约束坐标构造](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/motion_rep/reps/ardy_motionrep.py#L345-L379) · [Overwrite 与拼接](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/auto_latent_twostage_denoiser.py#L201-L255)

三路 Linear 各自从原始宽度投影到 1024，Token 的枚数仍由对应窗长决定。图中取 100 帧历史，所以 $H=25$。8 帧当前窗给出 $C=2$。这个调用保留 52 帧路径前视，扣掉当前的 8 帧，窗外 44 帧给出 $F=11$。如果互动界面按最远目标缩到第 20 帧，窗外就只需要 3 枚槽位，该目标仍在第三枚。图示的 Text 和 Step 给出 $25+2+11+2=40$ 枚。G1 H8 配置还加入 Initial Heading，补齐前的逻辑形状是 $B\times41\times1024$，这里的 $B$ 表示 batch size。TensorRT 会按引擎容量补齐动作轴，空槽由注意力 Mask 处理。[三路投影](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/auto_latent_twostage_denoiser.py#L76-L106) · [前缀](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/backbone.py#L279-L379) · [窗口预算](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/scripts/interactive_demo/window_budget.py#L35-L50) · [TensorRT 补齐](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/trt.py#L203-L239)

**Step $k$ 占一枚 1024 维前缀 Token。** 它表示当前计算进行到哪个噪声级。采样器设置跑 4 步或 10 步，决定会选哪些噪声级。两枚动作 Token 则对应机器人要播放的那 8 帧。[Step 嵌入](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/backbone.py#L279-L334)

G1 H8 采样时还会把文本条件、空间条件和无条件三个版本组成同一个 batch，再组合三份预测。[Classifier-free guidance 实现](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/cfg.py#L74-L149)

## 4. 一次去噪中，Root 和 Body 怎样配合 {#denoising}

<figure class="note-figure">
  <a href="assets/ardy/notes/04-two-stage-denoising-ddim.svg" aria-label="打开图 4 原图"><img src="assets/ardy/notes/04-two-stage-denoising-ddim.svg" width="1728" height="972" loading="lazy" decoding="async" alt="Root Transformer 先估计全局根动作，转换 Local Root 供 Body Transformer 使用，合成干净动作估计后用 DDIM 更新，迭代完成再解码"></a>
  <figcaption><strong>图 4</strong>　同一步里 Root 先给出干净估计，Body 在 Local Root 条件下估计姿态。DDIM 更新两枚 Token，跑完采样步后还原 8 帧。</figcaption>
</figure>

一次去噪里，两路 Transformer 都按 History、Current、Future 和前缀组织输入。Root Transformer 先读这一轮的带噪 Body 与处理过的 Root，输出干净的 Global Root 估计。预测根与已知的历史根接起来做差分，转换成 Local Root 后交给 Body Transformer。每个 Patch 的 Root 条件由 20 维换成 16 维，Body 分支的 History 和 Current 输入宽度因此变成 144 和 3436，Future 沿用 3312 维输入。Body 估计当前窗的干净姿态 latent，两路再合成 $2\times148$ 的干净动作估计 $\hat x_0$。DDIM 更新后，下一轮 Root 又会读到更新过的 Body。[论文图 3](https://arxiv.org/html/2607.08741#S3.F3) · [两路预测实现](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/auto_latent_twostage_denoiser.py#L201-L399)

我喜欢这处设计，因为全局根轨迹和身体姿态可以用不同的表示来预测，又能在去噪迭代里继续配合。训练时，Global→Local→Body 这条条件边会截断梯度。比如某一拍膝盖弯得不够，Body Transformer 需要靠自己的预测来修这个弯曲。这条条件边的梯度在 Local Root 停止，Root 仍有自己的监督信号。[条件边的实现](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/auto_latent_twostage_denoiser.py#L290-L335) · [训练目标](https://arxiv.org/html/2607.08741#S3.E11)

**迈得像，也可能走到别处。** 把整段根轨迹沿 $x$ 平移一米，每一步的速度、转速和关节角都可以保持，绝对位置会整体偏一米。所以在实验里，我会同时看路点误差和身体姿态。[论文表 2](https://arxiv.org/html/2607.08741#S5.T2)

### DDIM 每轮改的是同一窗动作

动作时间和扩散时间分开看。$x_k$ 里的两枚 Token 始终对应同一组 8 帧。$k$ 表示这组动作当前所处的噪声级。DDPM 和 DDIM 都可以用预测噪声或预测干净样本的参数化。ARDY 直接估计 $\hat x_0$。记累积保留系数为 $\bar\alpha_k=\prod_{\ell=1}^{k}\alpha_\ell$，前向加噪式给出干净估计与噪声方向之间的换算。

$$
\begin{aligned}
x_k &= \sqrt{\bar\alpha_k}\,x_0+\sqrt{1-\bar\alpha_k}\,\epsilon,\\
\hat\epsilon &= \frac{x_k-\sqrt{\bar\alpha_k}\,\hat x_0}{\sqrt{1-\bar\alpha_k}}.
\end{aligned}
$$

DDIM 可以选择较低的噪声级 $j<k$，用干净估计和噪声方向重新配比。

$$
x_j=\sqrt{\bar\alpha_j}\,\hat x_0
+\sqrt{1-\bar\alpha_j-\sigma_{k\to j}^{2}}\,\hat\epsilon
+\sigma_{k\to j}z.
$$

$$
\sigma_{k\to j}=\eta\sqrt{\frac{1-\bar\alpha_j}{1-\bar\alpha_k}}\sqrt{1-\frac{\bar\alpha_k}{\bar\alpha_j}}.
$$

ARDY 的采样取 $\eta=0$，所以 $\sigma_{k\to j}=0$，每一步的更新由当前状态和预测决定。典型 DDPM 沿相邻噪声级走。DDIM 允许跨噪声级，所以选稀一些的采样时间点，就可以少跑几轮两路 Transformer。图中的 $k-1$ 表示采样表里的下一步。扩散骨干用 Transformer 这一点可以从 DiT 理解，即把常见 U-Net 担任的预测模块换成 Transformer。ARDY 的设计重点落在动作如何表示、目标怎样进入模型，以及根和身体如何在每一步里配合。[DDPM](https://arxiv.org/abs/2006.11239) · [DDIM 式 12](https://arxiv.org/html/2010.02502#S4.E12) · [ARDY 采样实现](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/ardy/model/diffusion.py#L96-L133) · [DiT](https://arxiv.org/abs/2212.09748)

## 5. 新指令到了，旧动作还在播 {#replanning}

<figure class="note-figure">
  <a href="assets/ardy/notes/05-online-replanning.svg" aria-label="打开图 5 原图"><img src="assets/ardy/notes/05-online-replanning.svg" width="1728" height="972" loading="lazy" decoding="async" alt="上轴标出参考动作的承诺前缀、可替换后缀和新首帧，下轴标出后台开始生成、结果就绪和缓冲时间预算"></a>
  <figcaption><strong>图 5</strong>　上面是参考播放，下面是后台生成。新参考从缓冲尾的下一帧接上。示例生成窗为 8 帧，路径前视为 52 帧。</figcaption>
</figure>

我更关心接缝上的这一拍。假设机器人播放到第 $i=100$ 帧时收到新指令。生成线程空闲，旧参考足以承诺接下来 $B=4$ 帧。前台继续播放 101–104，后台用截至 104 的参考历史计算新窗。结果赶上接缝时，105–112 就播新生成的 8 帧。路径前视从 105 算到 156，当前窗之后还有 44 帧目标。[论文图 5](https://arxiv.org/html/2607.08741#S4.F5) · [接缝实现](https://github.com/nv-tlabs/ardy/blob/e706e27acc88070918308a10922b8f7174d0825e/scripts/interactive_demo/generation.py#L353-L401)

25 Hz 下每帧 40 ms，4 帧给后台约 160 ms。结果晚于新首帧的播放时刻，就错过了预定接缝。旧参考还有可用后缀时可以继续播，缓冲真正耗尽时才发生欠载。可以分别记按时接缝的比例、实际欠载次数和机器人走到接缝时偏离参考的程度。这样回头看 G1 跟踪视频时，就能追到走偏究竟发生在参考生成、交付还是执行。[G1 复现与跟踪记录](../)
