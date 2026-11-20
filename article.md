## 训练：从仿真记录到想象轨迹 {#training}

把视频定在一拍：参考给出下一拍的姿势，Actor 根据此刻的观测发出关节指令。机器人究竟迈了多远、身体有没有偏向一侧，要等物理仿真走完这一拍才知道。**参考动作给目标，经验池记录执行结果。**

策略每 20 ms 更新一次（50 Hz），仿真在这段时间内推进四个 5 ms 的物理子步。每一拍把状态、实际使用的指令、下一状态和终止信息存入 Replay；也记录环境参数和指令延迟状态。训练从这里分成三步：拟合世界模型、通过想象更新 Actor、用同一批想象轨迹拟合 Critic。

<figure class="research-figure">
  <figcaption><span>训练循环</span><a href="assets/figures/training-loop.png" target="_blank" rel="noopener">查看训练图原尺寸</a></figcaption>
  <a href="assets/figures/training-loop.png" target="_blank" rel="noopener" aria-label="打开训练循环原图"><img src="assets/figures/training-loop.png" width="1600" height="900" alt="仿真转移进入 Replay；Replay 提供连续窗口来拟合世界模型，再提供起点在世界模型中展开想象、更新 Actor 和 Critic。" loading="lazy"></a>
</figure>

### 第一步：让世界模型预测下一拍

每次从 Replay 取连续八步的窗口。用真实起点预测一步，再接着自己的预测往前走；每一步仍使用记录下来的动作、环境参数和延迟状态。这样，$F_\omega$ 不仅要预测准第一步，也要学会控制接下来几步的误差积累。

记 $e_{bj}$ 是第 $b$ 个窗口、第 $j$ 步的 60 维局部状态误差，已逐维除以带下限的误差尺度。$m_{bj}$ 标记仍在同一回合的有效转移。每步求 60 维的均方误差，累加窗口内的有效步，再对 $B$ 个窗口取平均：

$$
\mathcal L_F=\frac{1}{60B}\sum_{b,j}m_{bj}\,\lVert e_{bj}\rVert_2^2 .
$$

### 第二步：让 Actor 看见动作的后果

从 Replay 抽一个起点，把 Actor 这次选择的动作送进 $F_\omega$，再用预测状态构造下一拍观测。这样向前推至多 $H=32$ 步。每一步都用同一套跟踪规则计算奖励和软终止风险，而窗口末端的 Critic 估计接下来还可能获得的价值。

记 $\hat r_{t+1}$ 为这一拍奖励，$m_t$ 为有效标记，$d_t$ 为终止风险。后续奖励按存活权重 $c_{t+1}=c_t(1-d_t)$ 折算，初始 $c_0=1$。把窗口内折扣奖励记作 $R_H$，Actor 最大化它和折扣后的末端价值：

$$
\begin{aligned}
R_H &= \sum_{t=0}^{H-1}\gamma^t c_t m_t\hat r_{t+1},\\
J &= \mathbb E\!\left[R_H+\gamma^H c_H V_\psi(x_H)\right].
\end{aligned}
$$

动作到片尾时，最后一个有效步仍拿到奖励，此后的价值权重归零。本轮更新 Actor，固定世界模型和 Critic 的参数，梯度通过它们回到 Actor。

### 第三步：把想象轨迹变成 Critic 的固定目标

Critic 复用这一批想象轨迹的逐步数据：状态特征、参考和执行上下文，以及奖励、终止权重和有效标记。先保留数值、切断到 Actor 和世界模型的梯度。同一个 Critic 在本轮拟合前算出旧估值 $v_t$，再从 $Y_H=v_H$ 向前倒推目标。令 $\beta_t=\gamma(1-d_t)$，$r_{t+1}$ 为有效步的奖励：

$$
Y_t=r_{t+1}+\beta_t\big[(1-\lambda)v_{t+1}+\lambda Y_{t+1}\big].
$$

这也可以用 GAE 来读：先求一步残差 $\delta_t$，再把它和后面各步的残差按权重累加，得到旧估值的修正量 $A_t$。

$$
\begin{aligned}
\delta_t &= r_{t+1}+\beta_t v_{t+1}-v_t,\\
A_t &= \delta_t+\lambda\beta_t A_{t+1},\\
Y_t &= v_t+A_t .
\end{aligned}
$$

用一个两步例子看数字。旧估值是 $(4,3,2)$，两步奖励是 $1$ 和 $5$，第二步结束。为方便手算，例子取 $\gamma=0.9,\lambda=0.5$：先得 $Y_1=5$，再算 $Y_0=1+0.9(0.5\times3+0.5\times5)=4.6$。目标减去旧估值，得到 $A_0=0.6$、$A_1=2$。训练中的 Critic 用固定的 $Y_t$ 作均方误差拟合；本项目取 $\gamma=0.99,\lambda=0.95$。

## 推理：23 个身体动作，怎么变成 24 个目标 {#inference}

65k Actor 读最近 10 帧本体观测和从参考中取出的 10 个未来时刻，输出 23 个身体动作。**头部从当前参考帧另取一列。** BONES 与 LAFAN1 的 BVH、以及项目使用的 CMU 转换版，都能在头颈骨架上记录旋转。重定向把这些旋转换到 PM01 自己的关节轴上，输出随帧变化的一维 `J23_HEAD_YAW`。

设 $\mathbf q^0$ 为默认角，$\mathbf b$ 为校准偏移，$\mathbf s$ 为动作尺度。当前帧的头部参考角 $q_h^{\mathrm{ref}}$ 先变换成和 Actor 身体输出一致的归一化坐标。拼接后裁剪，再换回关节角：

$$
\begin{aligned}
a_h &= (q_h^{\mathrm{ref}}-q_h^0-b_h)/s_h,\\
\bar{\mathbf a} &= \operatorname{clip}_{[-20,20]}([\mathbf a_{23},a_h]),\\
\mathbf q^{\star} &= \mathbf q^0+\mathbf b+\mathbf s\odot\bar{\mathbf a}.
\end{aligned}
$$

<figure class="research-figure">
  <figcaption><span>从参考动作到关节目标</span><a href="assets/figures/inference.png" target="_blank" rel="noopener">查看推理图原尺寸</a></figcaption>
  <a href="assets/figures/inference.png" target="_blank" rel="noopener" aria-label="打开推理流程原图"><img src="assets/figures/inference.png" width="1600" height="900" alt="推理时观测历史与未来参考进入 Actor；23 个身体动作与当前参考头角组合、裁剪并换算成 24 个关节位置目标。" loading="lazy"></a>
</figure>

因此，推理只需要导出的 Actor 和归一化参数。世界模型和 Critic 在训练时提供学习信号，关节目标由上面的组合步骤生成。

## 评测：完成多少段，跟得有多准 {#results}

65k 检查点在同一个固定 200 段开发集上做了三次原生 MuJoCo-Warp 复测，Actor 以 **CUDA BF16** 前向运行。执行到参考末尾且未触发原生终止计为完成。关节 MAE 是 23 个身体关节的平均绝对角误差，单位为度；先对每段实际执行的帧取平均，再对片段等权平均。开头的动作视频另用 **CPU MuJoCo 与 FP32 ONNX**。

| 复测条件 | 完成片段 | 关节 MAE |
| --- | ---: | ---: |
| 0 ms · A | 195 / 200 | 8.01° |
| 0 ms · B | 194 / 200 | 8.01° |
| 逐段随机固定 0–20 ms | 194 / 200 | 7.99° |

**先读复测差异。** 两次 0 ms 只差一个片段，随机延迟的完成数与复测 B 相同。第三轮给每个片段固定抽一档延迟，五档里的动作不同，因此这里比较整套协议下的总体表现。提前终止以完整根旋转超限为主；完成数和关节误差放在一起看，才能同时读出跑到了哪里、姿势跟得如何。

**再读训练后段。** 在相同随机延迟协议下，79k 完成 198 段，MAE 为 7.17°；99k 只完成 175 段，MAE 升至 10.02°，帧覆盖也降至 92.08%。继续采集和更新期间，闭环表现并未单调变好。橙色标出的 65k 是这次准备分发的快照。持续静站和完整敬礼将在真机联调后另行记录。

<figure class="research-figure">
  <figcaption><span>八个检查点的同协议对照</span><a href="assets/figures/checkpoint-comparison.png" target="_blank" rel="noopener">查看评测图原尺寸</a></figcaption>
  <a href="assets/figures/checkpoint-comparison.png" target="_blank" rel="noopener" aria-label="打开检查点对照图"><img src="assets/figures/checkpoint-comparison.png" width="2728" height="1936" alt="八个采集步快照的完成率、身体关节 MAE、帧覆盖率。65k 为候选，79k 的误差较低，99k 三项均退化。" loading="lazy"></a>
</figure>

[下载 65k 复测汇总](assets/native_bf16_retests_65k.csv) · [下载八个快照的汇总](assets/native_bf16_candidate_snapshots.csv)

## 代码与权重 {#release}

[GitHub 源码与使用说明](https://github.com/approchin/SuperMimic-PM01) · [Hugging Face 模型卡与 65k 权重](https://huggingface.co/approchin/SuperMimic-PM01) · [GitHub 65k 权重文件（v0.1.0）](https://github.com/approchin/SuperMimic-PM01/tree/v0.1.0/models)

v0.1.0 包含训练、仿真评测和离线推理代码。仓库的 `models/` 目录提供两份 65k 权重：

- **CPU 推理：** `actor_65000_fp32.onnx`，包含 Actor 与归一化，配合 `robot_spec.json` 使用。
- **检查与重导出：** 脱敏的 `actor_0000065000.pt` 附模型卡、校验清单与独立模型许可。

在源码仓库根目录运行最小示例，用 `models/` 中的 ONNX 做一次 CPU 推理：

```sh
python -m pip install -r inference/requirements.txt
python tools/smoke_inference.py
```

示例检查 23 维网络输出、24 维关节位置目标和重置行为。方法来源：[SuperMimic](https://arxiv.org/abs/2610.28480)、[HoloMotion](https://github.com/HorizonRobotics/HoloMotion)；TD 与 GAE 的关系可对照 [GAE 原文](https://arxiv.org/abs/1506.02438)。
