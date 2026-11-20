## 适配：把 G1 的策略接到 PM01 上 {#adaptation}

首屏的 A、B 两段回放跟的是同一段参考动作，区别在训练时哪些参数允许更新。两组均从 NVIDIA 的 Default SONIC G1 策略初始化。两组共用一条前向路径：参考编码器压缩运动信息，FSQ 把它量化成离散表示，控制解码器再结合 PM01 的本体观测给出动作。

两台机器人的关节顺序、角度和坐标约定不同。先把参考动作重定向到 PM01，再把固定映射折叠进网络的边界层。比如，一个输入向量 $x$ 先经 $Mx+c$ 换到源坐标，再通过原来的线性层 $W,b$。这两步可以合并：

$$
W(Mx+c)+b=(WM)x+(Wc+b).
$$

所以新的线性层用 $WM$ 和 $Wc+b$ 初始化，就能在同一个算子里完成映射和原网络计算。映射固定后，再用 PM01 的仿真反馈微调。

<figure class="research-figure">
  <figcaption><span>两组共用的参考到动作流程</span><a href="../assets/sonic/diagrams/overview.svg" target="_blank" rel="noopener">查看总图原尺寸</a></figcaption>
  <a href="../assets/sonic/diagrams/overview.svg" target="_blank" rel="noopener" aria-label="打开共用推理结构图"><img src="../assets/sonic/diagrams/overview.svg" alt="参考编码通过固定的 FSQ；本体观测与量化后的参考特征一同进入动作解码器，产生 23 个身体动作。" loading="lazy"></a>
</figure>

## 训练：冻结编码器，还是跟着一起学？ {#training}

**方案 A** 固定参考编码器，只更新 Actor 的动作解码器；**方案 B** 同时更新参考编码器和动作解码器。两组都学习身体动作的探索标准差，也都更新各自的 Critic。参考的量化规则和坐标映射保持固定。

| 组件 | 方案 A | 方案 B |
| --- | --- | --- |
| 参考编码器 | 固定 | 微调 |
| 动作解码器 | 微调 | 微调 |
| 探索标准差与 Critic | 更新 | 更新 |

两组都在 PhysX 里采集转移，使用 PPO 更新。训练时，根据解码器的均值和学习到的标准差采样身体动作；仿真产生真实的下一状态和奖励，Critic 再帮助估计优势。若 $\rho_t$ 是新旧策略对同一条采样动作的概率比，$\hat A_t$ 是优势，定义 $\bar\rho_t$ 为限制在 $[1-\epsilon,1+\epsilon]$ 内的概率比，Actor 优化的截断项为：

$$
L_t^{\mathrm{clip}}=\min\!\left(\rho_t\hat A_t,\ \bar\rho_t\hat A_t\right).
$$

从第一段 93 条 CMU 参考训练到累计 1,018 次 PPO 更新后，两组接续到包含 3,950 条 PM01 参考的库。本文的 4k、28k 是累计 PPO 更新次数。A/B 的差别在于梯度是否更新参考编码器；优势和更新目标来自采集轨迹，梯度不穿过 PhysX。

<details class="research-figure diagram-detail">
  <summary>A、B 的训练更新图</summary>
  <figure>
    <figcaption><span>A · 固定参考编码器</span><a href="../assets/sonic/diagrams/train-a.svg" target="_blank" rel="noopener">查看 A 图原尺寸</a></figcaption>
    <a href="../assets/sonic/diagrams/train-a.svg" target="_blank" rel="noopener" aria-label="打开 A 方案训练图"><img src="../assets/sonic/diagrams/train-a.svg" alt="方案 A 固定参考编码器；梯度更新动作解码器与独立价值网络。" loading="lazy"></a>
  </figure>
  <figure>
    <figcaption><span>B · 微调参考编码器和动作解码器</span><a href="../assets/sonic/diagrams/train-b.svg" target="_blank" rel="noopener">查看 B 图原尺寸</a></figcaption>
    <a href="../assets/sonic/diagrams/train-b.svg" target="_blank" rel="noopener" aria-label="打开 B 方案训练图"><img src="../assets/sonic/diagrams/train-b.svg" alt="方案 B 的梯度穿过 FSQ 的直通估计更新参考编码器，并更新动作解码器与独立价值网络。" loading="lazy"></a>
  </figure>
</details>

## 推理：怎样从参考生成关节目标 {#inference}

把仿真中的一拍拆开看：参考编码器读取 540 维动作参考，FSQ 输出两个各 32 维的 token。解码器将这 64 维与 789 维本体及反馈特征拼接，输出 23 个身体动作的均值。789 维由十帧状态和动作历史、以及当前的 9 维跟踪反馈组成。

策略每 20 ms 更新一次。令 $\mu_{23}$ 为 Actor 的输出、$a_h$ 为按当前参考头角换算的单独指令，先拼接并裁剪，再按该控制器的默认姿态 $\mathbf q^0$ 和动作尺度 $\mathbf s$ 换回角度：

$$
\begin{aligned}
\bar{\mathbf a}&=\operatorname{clip}([\mu_{23},a_h]),\\
\mathbf q^{\star}&=\mathbf q^0+\mathbf s\odot\bar{\mathbf a}.
\end{aligned}
$$

导出的确定性 Actor 只计算身体动作均值；当前参考帧提供头部目标。训练用的动作采样和 Critic 都不在推理图里。这让读者能用合成输入先核对网络接口，再接自己的状态估计与执行链路。

## 评测：完成数相同，误差各有取舍 {#results}

在 **106 段 LAFAN1、394 段 OMOMO** 组成的固定开发评测上，A、B 都从参考首帧开始运行一遍。仿真是 PhysX，物理 200 Hz、控制 50 Hz。表格统计完整走完参考且未触发主要失败判据的段数；误差只覆盖各段实际执行的区间，按片段等权。24 关节 RMSE 包括由参考驱动的头。

| 28k · 固定混合 500 | A | B |
| --- | ---: | ---: |
| 完成片段 | 485 / 500 | 485 / 500 |
| 关节 RMSE | 8.657° | 8.292° |
| 局部连杆位置误差 | 27.36 mm | 26.43 mm |
| 世界坐标根位置误差 | 18.17 cm | 20.26 cm |

**看姿势和看路径，会得到不同排序。** B 的关节与局部连杆误差更小，A 的整体根位置偏差更小。两组完成数相同，意味着单看能不能走完全段，会错过对姿势和位置的取舍。

同一套动作上，4k 的 A、B 完成数分别为 **485、483**，关节 RMSE 分别为 **9.725°、9.589°**。到 28k，关节误差都下降了，A 的完成数没变，B 增加两段。首屏七组 BONES-SEED 视频用于观察具体动作；这里的计数来自上面的固定 500 段。

## 代码与权重 {#release}

[GitHub 推理源码](https://github.com/approchin/sonic-pm01) · [下载 A/B 权重（v0.1.0）](https://github.com/approchin/sonic-pm01/releases/tag/v0.1.0) · [权重清单与使用说明](https://github.com/approchin/sonic-pm01/blob/main/docs/weights.md)

源码仓库包含独立的 CPU 推理代码和输入输出契约。Release 提供 A、B 各自的 4k 与 28k 检查点，每组都有 ONNX 和 safetensors。任选一个检查点压缩包，解压到源码仓库根目录，保留 `weights/` 路径即可运行推理示例。

适配基于 [NVIDIA GEAR-SONIC](https://nvlabs.github.io/GEAR-SONIC/)，参考 [Any2Any](https://any2any.top/) 的跨机器人适配思路。展示是 PhysX 的仿真轨迹，不是持续真机控制的验收结果。原始动作与机器人模型不随网页分发。
