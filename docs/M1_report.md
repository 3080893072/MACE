# M1 报告：真实 Qwen 试点

日期：2026-10-30。所有数字来自 `runs/` 下的原始产物（`events.jsonl`、
`<mode>_seed42.json`、`config.json`），可逐条复算。

**证据等级声明**：本文所有"通过/失败"都是对声明过的有限输入域的全量执行结果，
即 `BOUNDED`。原型没有无穷域证明过程，永远不会输出 `PROVEN`。
`experiments/hidden/*_reference.json` 中的人工参考合同**从未进入任何 prompt**，
只用于 CPU 自检与事后打分。

---

## 1. 硬件

| 项 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 4090 D |
| 显存 | 24564 MiB（`nvidia_smi.txt` 记录 5315 MiB 常驻，运行期模型占满） |
| 驱动 / CUDA | 580.76.05 / 13.0 |
| 主机 | AutoDL 容器，16 核，80 GB 内存 |
| 模型服务 | `ollama serve`，只绑定 `127.0.0.1:11434`，`OLLAMA_NUM_PARALLEL=1`、`OLLAMA_MAX_LOADED_MODELS=1`、`KEEP_ALIVE=-1` |

换机前那台 AutoDL 实例处于**无卡模式**（`/dev/nvidia*` 不存在、`cpu.max=0.5` 核、
`memory.max=2GiB`），llama-server 反复 "loading model"，已弃用，其日志不进入任何结论。

## 2. 实际使用的 Qwen 模型

| 用途 | 模型 | 量化 | 体积 | 上下文 | 位置 |
|---|---|---|---|---|---|
| 主实验 | `qwen2.5-coder:7b` | Q4_K_M（7.6B） | 4.7 GB | 8192 | 100% GPU（`size_vram == size`） |
| 对照 | `qwen2.5-coder:14b` | Q4_K_M | 9.0 GB | 8192 | 100% GPU |
| 链路冒烟 | `qwen2.5-coder:0.5b` | Q4_K_M | 397 MB | 8192 | 只验证 JSON 通道 |

采样参数：`temperature=0`、`seed=42`、`format=json`、`num_ctx=8192`。
每次调用的完整响应、耗时、prompt/completion token 都写进
`runs/<...>/events.jsonl` 和 `runs/<...>/<mode>_seed42.json`；
`config.json` 里另存 `/api/show` 的模型元数据和 `/api/ps` 的显存驻留情况。

## 3. 冒烟是否通过

**是**，但要分清两件事。

* 引擎侧（CPU）：`python -m mace.cli smoke` 对三个 fixture 各跑一次，
  沙箱子进程执行 P+/P−，隐藏参考合同全部 `BOUNDED`、`guard_ok=true`；
  `pytest` 64 项全绿（含 trace 差分、归因对比、guard 归因定位、跨 run 汇总）。
* 模型侧：`qwen2.5-coder:0.5b` 能稳定返回可解析的 JSON（通道通），
  语义毫无意义；`qwen2.5-coder:7b` 在 `sort_channel` 上首次产出**合法**合同
  （schema 合格、变量名合法）。冒烟只证明"引擎能跑通、模型能收到并回传结构"，
  **不证明**模型能答对。

## 4. 模型真实产出的语义关系/公式

下面是 7B 在 full MACE 模式下最终轮的原样内容（`engine_*/mace_seed42.json`）：

| fixture | 关系 | 状态 | 表达式 | 条件 |
|---|---|---|---|---|
| dedup | T1 target_effect | BOUNDED | `xs_post == xs + [xs[0] + 1]` | True |
| dedup | U1 upstream/supporting | BOUNDED | `len(xs) > 0` | True |
| dedup | O0 observer | INVALID | `len(fn_0(xs_post))` | True |
| dedup | guard | REFUTED | `len(xs) > 0` | 误接受 140 行 |
| sort | T1 target_effect | BOUNDED | `xs_post == sorted(xs)` | True |
| sort | U1 upstream/fixed_point | REFUTED | `pre == False` | True |
| sort | O0 observer | REFUTED | `xs[0]` | `use_left` |
| sort | O1 observer | REFUTED | `xs[-1]` | `use_right` |
| sort | guard | REFUTED | `pre == False` | 误接受 2866、误拒绝 5456 |
| swap | T1 target_effect | INVALID | `xs_post == xs` | True |
| swap | U1 upstream/fixed_point | REFUTED | `n == k` | True |
| swap | O0 observer | BOUNDED | `a + b` | True |
| swap | O1 observer | BOUNDED | `a * b` | True |
| swap | O2 observer | REFUTED | `0` | True |
| swap | guard | REFUTED | `n == k` | 误拒绝 12（无误差接受） |

14B 在 `sort_channel` 的 full MACE 里最终给出
`pre and xs == fn_0(xs) or use_left and xs == sorted(xs) or use_right and xs == sorted(xs)`：
**sound（0 误接受）但 incomplete（7171 行该接受而未接受）**——结构方向对了，
组合不完整。同一次实验里 14B 在 `direct` 模式下第 4 轮给出
`n == k or show_gap == False`，与人工参考 guard 逐字相同，`BOUNDED`。

## 5. 找到多少不可靠/不完整的条件

7B、full MACE、三个 fixture 合计 **11 条关系：5 条 BOUNDED、4 条 REFUTED、2 条 INVALID**，
即 **6/11（55%）不可靠**；12 次 guard 检查（3 fixture × 4 模式）**0 次正确**。

可复现的错误类型：

1. **条件取反**：把"A 是 no-op"写成 `pre == False`（真实语义是 `pre` 为真时上游已经排好序）。
   用 `pre → flag_0` 的改名对照 fixture 复测，14B 仍写 `flag_0 == False`，
   排除"变量名暗示"这一解释，属于语义推理错误。
2. **观察者写成本地变量名而非真实计算**：`xs[0]`、`xs[-1]`，而真实通道是
   `min(xs) if use_left else xs[0]`。
3. **把检查器诊断字段当程序变量**：14B 在 swap 的 MACE 里产出
   `show_gap == False or a_has_local_effect`，`a_has_local_effect` 是我们回传的
   反例 JSON 字段名。已修：诊断信息移入 `"diagnostic"` 子对象，顶层只留真实的程序值。
4. **在 `mask_guard` 里用 `xs_post`**：`xs_post` 只在 `target_effects` 的语义里有定义。
   已修：编译失败信息现在直接说明这一点。

## 6. 反例反馈是否改善了关系

是，但只在"把过宽的 guard 收窄"这个方向稳定，且会中间回退。逐轮守卫误差
（误接受 / 误拒绝）原样摘自 `exchanges[*].report.guard`：

| 模型/fixture/模式 | 第 1 轮 | 第 2 轮 | 第 3 轮 | 第 4 轮 | 最终 guard |
|---|---|---|---|---|---|
| 14B swap direct | 12 / 0 | 0 / 4 | INVALID | **0 / 0 BOUNDED** | `n == k or show_gap == False` |
| 14B swap generic | 12 / 0 | 0 / 4 | INVALID | **0 / 0 BOUNDED** | 同上 |
| 14B dedup fixed | INVALID | INVALID | INVALID | **0 / 0 BOUNDED** | `len(fn_0(xs)) == len(fn_0(xs + [xs[0] + 1]))` |
| 7B sort direct | 2866 / 5456 | **0** / 6682 | 1134 / 7816 | — | 收窄成功但不再完整 |
| 7B swap mace | 0 / 12 | 0 / 12 | 0 / 12 | — | `n == k`，四轮不动 |
| 14B sort mace | INVALID | 0 / 7171 | 0 / 7171 | 0 / 7171 | 结构对、组合不全 |

结论：

* 反馈确实改变了输出，并两次让 14B 收敛到与参考逐字相同的 guard。
* 改善主要发生在 **soundness**（不再误接受）；**completeness** 几乎不动，
  模型倾向于删掉自己没把握的析取项而不去补缺失的那一项。
* 会**回退**：模型有把合法 guard 改写成 INVALID 的轮次（`n == ... _post`）。

针对这一点，M3 阶段加入了两条反馈增强（本轮之后才实现的，见第 7 节与后续 M3 报告）：
*给失败的 guard 定位"是哪个顶层子项导致的误判"*，以及
*给出一对只差一个参数、结论相反的**真实执行对比**（contrast witness）*。

## 7. 离真正的 MACE 引擎还差什么

已具备：受限类型语言（不执行模型代码）、进程隔离沙箱、观察者可靠性/目标不变性分离、
逐通道检查、反例定位与补丁式修复、上游定点、证明 DAG、三级归因、跨 run 汇总。

仍缺：

1. **证明**。只有有限域 `BOUNDED`。没有 SMT/区间抽象，`PROVEN` 状态虽然定义了但从不产生。
   对无限域只能报 `TESTED`。
2. **真正的上游推理**。`fixed_point` 角色目前是对"条件 ⇒ 快照不变"的直接检查；
   还没有让模型为未知函数提出并验证后置条件/循环不变式的那条链。
3. **组合求解**。proof DAG 是单层 `(OR 定点) OR (AND 观察者)`，
   跨变量补偿、替代掩盖（两条不同路径各自掩盖）还没有共享结构上的求解，
   只是把模型给的 guard 拿去检查。
4. **多输出联合掩盖**：逐通道检查有，但联合 guard 的组合仍靠模型一次写对。
5. **归因第三级**只做了单参数对比，没有多参数联合对比；第 2 级（trace 差分）已实现，
   但还没有进入自动评分。
6. **真实仓库隔离**：只有子进程 + AST 白名单 + 超时，不是容器级沙箱。
7. **模型能力**。7B/14B 在"合同级"推理上明显不足：能写出正确的 target_effect
   （3/3 fixture 中有 2 个 BOUNDED），但观察者与 guard 的失败率高。
   这不是引擎的问题，但决定了端到端成功率的上限。

## 复现

```bash
# 引擎自检（CPU）
python -m mace.cli smoke --fixture sort_channel.json
python -m pytest -q

# 真实模型实验
python -m mace.cli run --fixture sort_channel.json --provider ollama \
    --model qwen2.5-coder:7b --mode all --rounds 4 --seed 42 --num-ctx 8192

# 跨 run 汇总（守卫误差、逐轮变化、token 成本）
python -m mace.cli summarize --runs runs/m1_20261030_081238
```
