# MACE 算法逻辑与 Qwen 运行来源审计

日期：2026-11-03  
审计对象：`mace_qwen_pilot_kit` 当前工作树、M5 冻结产物、M1/M2/M4 报告及两个历史归档。  
审计约束：全程只读；未调用任何模型；未启动或连接 GPU 推理服务；未修改评分器、fixture、历史 run 文件或报告。除本文件外，没有新增或改写任何项目文件。

本文把“算法逻辑问题”和“运行来源问题”分开处理。结论中不使用“报告一定是虚构”这种未经证据支持的判断；没有原始证据的，只标记为“无法核实”，不标记为“已证实伪造”。

---

## 0. 结论摘要

1. **M5 有较完整的存储转录证据，M1–M4 没有。**  
   M5 的 86 份运行文件都带有 `request`、`raw_response`、Ollama 风格 `stats`、provider/model 和时间；270 个 `m5/` 文件与冻结清单逐字节 SHA-256 一致。但没有任何独立的 Ollama 服务日志、`nvidia-smi`、hostname 或 endpoint 记录。因此 M5 最多是 **`VERIFIED_REPLAY_OF_MODEL_OUTPUT`（存储转录可复算）**，不是 **`VERIFIED_LIVE_MODEL_RUN`**。

2. **M1–M4 的模型成绩和 GPU 报告没有可核实的原始运行。**  
   `runs/` 为空；M2/M4 报告引用的 `/root/m2_*`、`/root/m4_*` 不存在；两个归档里没有 M1–M4 的 run 文件，也没有 `nvidia_smi.txt` 或 Ollama 日志。M1 报告声称“所有数字来自 `runs/`，可逐条复算”，但交付物中没有这些文件。这些结果只能标记为 **`UNVERIFIED_MODEL_ORIGIN`**。

3. **当前 Full MACE 的默认最终 Guard 由 Qwen 写，不是 Composer。**  
   `mace/cli.py:255-256` 的默认值是 `--guard-source qwen`；`mace/loop.py:167-169` 的默认参数也是 `qwen`。M5 的 26 份 MACE 运行全部记录 `guard_source: "qwen"`。Composer 只在 `--guard-source derived`、oracle-derived 诊断或 M6 离线重放中使用。

4. **算法存在真实的逻辑/实现问题，不能全部归因于 Qwen。**  
   至少包括：正确 Guard 被后续轮次覆盖；局部关系只提供充分条件、不能生成必要条件；Composer 结构在一般情形下表达力不完整；observer 的 condition 编译作用域与求值作用域不一致；同一 channel 多个 observer 会让 soundness 直接变成 `UNKNOWN`；fixed-point 聚合在成员已被 `REFUTED` 时仍报 `BOUNDED`；无 witness 条件被当成 `BOUNDED` 并进入 Composer。

5. **Exact 下降有多个来源。**  
   在论文的 11 个评分用例中，`held1/parity_snap` 的 1 例可由“正确 Guard 被覆盖”直接解释（M6 的 online 保留策略把它从 2/3 恢复到 3/3）。其余损失还来自模型语义错误、错误/缺失的 fixed-point 关系、Composer 的不完整组合、无效的 `<name>_post` 作用域使用，以及重复 observer 导致的 soundness 失败。

6. **哪些数字不能直接进正式论文：**  
   M1–M4 的所有模型成绩、token/墙钟、GPU/显存/驱动信息都不能作为已核实结果；M5 的数字只能以“存储转录复算”出现，不能写成“已核实的实时 Qwen 推理”或“已核实的 AutoDL RTX 4090 运行”。M6 的 symbolic/induction 是确定性结果；11/11 还依赖人工写的 helper summaries，不能写成自主结果。Direct-First 6/11 是固定提案的离线模拟，不是在线算法结果。

---

## 1. 证据分类口径

本文使用以下五类标签，并对每份运行族单独标注：

| 标签 | 含义 | 本文中的判定标准 |
|---|---|---|
| `VERIFIED_LIVE_MODEL_RUN` | 有独立证据证明请求确实到达了当时运行的真实模型服务 | 需要原始请求/响应之外，还能看到服务端日志、进程/端口、hostname、GPU 记录或可交叉验证的运行机器信息 |
| `VERIFIED_REPLAY_OF_MODEL_OUTPUT` | 有完整的原始模型请求和响应，且可由这些 response 离线复算结果 | 需要 `request`、`raw_response`、模型身份、时间、token/耗时；不要求独立服务日志 |
| `UNVERIFIED_MODEL_ORIGIN` | 报告声称是模型运行，但交付物中没有原始请求/响应或可复算记录 | 只有报告表格、摘要或二手描述 |
| `DETERMINISTIC_ONLY` | 结果由本地确定性代码产生，未调用模型 | 例如 symbolic engine、Composer、hash/统计脚本 |
| `MANUAL_OR_SYNTHETIC` | 输入或标签由人工编写/合成，不是模型自主产生 | 例如人工参考合同、人工 helper summary、人工构造的 fixture |

“无法核实”不等于“伪造”。本文只在证据不足时使用 `UNVERIFIED_MODEL_ORIGIN`，不据此推断动机。

---

## 2. Task A：模型运行来源审计

### 2.1 M5 运行资产清单

当前 `m5/` 下有 86 份 `*_seed42.json`，按目录和模式分布如下：

| 目录 | 模式 | 文件数 | 用途 |
|---|---|---:|---|
| `m5/A` | `mace` | 9 | 早期 Full MACE（Qwen Guard） |
| `m5/A3` | `mace` | 9 | dev6 + held1 补充的 Full MACE（Qwen Guard） |
| `m5/H` | `mace` | 3 | held1 早期 MACE |
| `m5/H2` | `mace` | 3 | held1 MACE 重跑 |
| `m5/H3` | `mace` | 2 | held2 MACE |
| `m5/base` | `direct` / `fixed` / `generic` | 9 + 9 + 9 | dev6 + held1 基线 |
| `m5/H` | `direct` / `fixed` / `generic` | 3 + 3 + 3 | held1 基线 |
| `m5/H3` | `direct` / `fixed` / `generic` | 2 + 2 + 2 | held2 基线 |
| `m5/T` | `direct` | 9 | token/轮次匹配的 Direct 对照 |
| `m5/C` | `oracle` | 9 | 人工 reviewed contract + Qwen 写 Guard（Cell C） |

合计 86 份运行文件、237 个 exchange 记录、`usage.calls` 合计 251 次调用。  
其中 72 份非 generic 运行的 `usage.calls` 与 exchange 数一致；14 份 generic 运行多出 1 次 summary 调用，该调用计入 `usage.calls`，但没有作为 exchange 的 `raw_response` 单独保存。这个缺口只影响 generic 基线，不影响 Direct 和 Full MACE。

M5 的目录级元数据：

- 53 份 `config.json`，53 份 `summary.json`，44 份 `events.jsonl`。`events.jsonl` 是 MACE 验证事件，不是 Ollama 服务日志。
- 每一份 MACE/Direct 运行的 exchange 都有 `request`、`raw_response`、`stats`；本次检查未发现缺失字段。
- 每份 MACE 运行都记录 `provider: "ollama"`、`model: "qwen2.5-coder:32b"`、`guard_source: "qwen"`。
- `stats` 包含 `prompt_tokens`、`completion_tokens`、`total_duration_ns`、`load_duration_ns`、`prompt_eval_duration_ns`、`eval_duration_ns`、`wall_seconds`、`model`、`done_reason`、`attempt`。
- `config.json` 的 `model_info` 来自 `/api/show`：family `qwen2`、32.8B、Q4_K_M。
- `config.json` 的 `runtime.ps` 来自 `/api/ps`：模型大小 21,775,106,702 bytes，`size_vram == size`，digest `b92d6a0b...`，context 8192，runner `llamacpp`，`expires_at` 带 `+08:00` 时区。

**这些元数据能说明什么：** 有一个 Ollama 兼容服务在某个带 GPU 的机器上加载了 32B Q4_K_M 并返回了这些响应；从响应内容、token 统计和耗时看，不像纯手工拼接的短文本。  
**这些元数据不能说明什么：** 不能证明该机器是 AutoDL、不能证明 GPU 是 RTX 4090 D、不能证明服务日志没有被重写、也不能证明调用发生在报告声称的那台实例上。M5 JSON 中没有 `endpoint` 或 `hostname` 字段；endpoint 只能从 `mace/qwen.py:17,61` 的默认值推断为 `http://127.0.0.1:11434`。

### 2.2 冻结与哈希

`m6/freeze_manifest.json` 记录了 364 个文件：

- `m5/` 270 个文件全部存在，SHA-256 全部匹配，0 缺失、0 不匹配。
- 非 `m5/` 的 4 个文件与当前工作树不一致：`mace/cli.py`、`mace/loop.py`、`mace/symbolic.py`、`tests/test_symbolic.py`。其中 `cli.py`/`loop.py` 是冻结后加入 Evidence Gate 的改动；`symbolic.py`/`test_symbolic.py` 也是冻结后的改动。当前树不等于冻结 commit，但 M5 的 270 个产物没有被改动。
- 冻结清单自身记录 `frozen_through_commit: 94912c12466054dcfc809e3bf45224137501ad9b`、`model_runs.model: qwen2.5-coder:32b (Ollama, stored M5 runs only)`、`note: M6 and this audit made no model calls`。

因此，“M5 文件被冻结并可校验”这一点成立；它校验的是**存储字节**，不是**实时服务来源**。

### 2.3 M5 运行时间

`generated_utc` 显示 M5 集中在 2026-10-30：

- `A`：约 02:46–02:54Z
- `A3`：约 10:31–10:39Z
- `H2`：约 10:39–10:41Z
- `H3`：约 10:44–10:48Z
- `base`：约 10:48–10:54Z

`config.json` 的 `started_utc` 与文件 mtime（本地 +08）能对上。时间上内部自洽；但没有服务端时间戳或调度日志可以交叉验证。

### 2.4 M1–M4 的证据缺口

`docs/M1_report.md` 的关键声明：

- 第 3 行：所有数字来自 `runs/` 下的 `events.jsonl`、`<mode>_seed42.json`、`config.json`，可逐条复算。
- 第 17–21 行：GPU 为 NVIDIA GeForce RTX 4090 D，24564 MiB；驱动 580.76.05 / CUDA 13.0；AutoDL 容器 16 核、80 GB；Ollama 绑定 `127.0.0.1:11434`。
- 第 23 行：换机前的 AutoDL 实例处于无卡模式（`/dev/nvidia*` 不存在、`cpu.max=0.5` 核、`memory.max=2GiB`），其日志不进入任何结论。
- 第 36 行：原始产物路径为 `runs/<...>/events.jsonl` 和 `runs/<...>/<mode>_seed42.json`。

实际情况：

- 当前 `runs/` 目录为空，只有 `.` 和 `..`。
- 工作树中没有 `nvidia_smi.txt`，没有任何以 `nvidia`、`ollama`、`gpu` 命名的日志文件。
- 两个归档中也没有 M1–M4 的 run 文件：旧归档 603 个条目，只有一个空的 `runs/` 目录；新归档 502 个条目，只有后续 benchmark 的 `executability/runs` 和 `interface/runs`，没有 M1/M2/M4。
- `docs/M2_M4_report.md` 第 3–6、146、195 行引用 `/root/m2_20261030_090315`、`/root/m2_20261030_090957`、`/root/m4_20261030_091725`、`/root/m4_20261030_092722`、`/root/m4_20261030_093648`、`/root/m4_20261030_094431`；这些目录在当前工作树和归档中均不存在。

结论：M1–M4 的 7B/14B/32B 成绩、token/墙钟、GPU/显存/驱动/主机信息，全部是 **`UNVERIFIED_MODEL_ORIGIN`**。这不是“已证实伪造”，但报告中的“可逐条复算”在交付物层面不成立。

### 2.5 AutoDL 报告与实际环境

审计机当前环境：

- `nvidia-smi`：NVIDIA GeForce RTX 5060，8151 MiB，驱动 577.05，CUDA 12.9。
- 本机没有 `ollama` 可执行文件，也没有 `~/.ollama` 目录。

这与 M1 报告的 RTX 4090 D 24564 MiB / AutoDL 16 核 80 GB 不是同一台机器。这个不一致本身不能证明报告虚构；更合理的解释是报告声称的是远程 AutoDL 实例，而审计机是另一台本地机器。问题在于：交付物中没有远程实例的 hostname、`nvidia-smi`、Ollama 服务日志或调度记录，无法独立确认“那台实例”存在过。

M5 的 `runtime.ps` 显示 21.78 GB 模型全部驻留显存，这与 24 GB 级 GPU 一致，也与“不是本机 8 GB 显卡”一致；但它是客户端自己记录的 `/api/ps` 响应，不是独立 GPU 监控日志。因此：

- **M1–M4 的 AutoDL/4090D 声明：无法核实。**
- **M5 的 GPU 驻留元数据：与 24 GB 级 Ollama 主机一致，但不能独立证明主机身份。**
- **没有发现可直接判定“环境声明为假”的证据；也没有发现可确认其为真的独立证据。**

### 2.6 来源分类矩阵

| 运行族 | 内容 | 原始请求/响应 | 独立服务/GPU 日志 | 标签 |
|---|---|---|---|---|
| M5 Full MACE（A3/H2/H3，论文 11 例中的 11 份） | Qwen 32B 合同 + Qwen Guard | 有 | 无 | `VERIFIED_REPLAY_OF_MODEL_OUTPUT`（非 live） |
| M5 Full MACE 补充（A/H） | 早期/held1 重复 | 有 | 无 | 同上 |
| M5 Direct（base/H3，论文 11 例） | Qwen 32B 直接 Guard | 有 | 无 | 同上 |
| M5 Direct 12 轮（T） | 轮次/token 对照 | 有 | 无 | 同上 |
| M5 generic/fixed 基线 | 摘要/模板 Guard | 有（generic 的 summary 调用未单列） | 无 | 同上，generic 有记录缺口 |
| M5 C oracle | 人工 reviewed contract + Qwen Guard | 有（模型 Guard）；合同为人工 | 无 | 合同 `MANUAL_OR_SYNTHETIC`；Guard 输出 `VERIFIED_REPLAY_OF_MODEL_OUTPUT` |
| M6 Composer 3/11 | 对 M5 合同离线重组 | 使用 M5 转录 | 不适用 | `DETERMINISTIC_ONLY`（输入来自存储转录） |
| M6 Symbolic 7/11 | 纯符号执行 | 不调用模型 | 不适用 | `DETERMINISTIC_ONLY` |
| M6 Symbolic + human summaries 11/11 | 符号执行 + 人工 helper summary | 不调用模型 | 不适用 | `DETERMINISTIC_ONLY` + `MANUAL_OR_SYNTHETIC` |
| M6 Induction 10/11 sufficient，0/11 necessary | 有界条件归纳 | 不调用模型 | 不适用 | `DETERMINISTIC_ONLY` |
| Direct-First 6/11 | 固定 Direct/MACE 提案的离线策略 | 使用 M5 转录 | 不适用 | `DETERMINISTIC_ONLY`（离线模拟） |
| M1–M4 7B/14B/32B | 报告表格 | 无 | 无 | `UNVERIFIED_MODEL_ORIGIN` |
| M1 硬件表 / `nvidia_smi.txt` | GPU/驱动/主机 | 无 | 无 | `UNVERIFIED_MODEL_ORIGIN` |

#### 2.6.1 论文 11 例的逐例映射

下表把论文使用的 11 个 fixture 对到具体 run 文件。每一份 MACE JSON 都含 `request`、`raw_response`、`stats`，`guard_source` 为 `qwen`；Direct JSON 同样含原始转录。统一标签 **`VRO` = `VERIFIED_REPLAY_OF_MODEL_OUTPUT`（存储转录可复算，非 live）**。

| fixture | split | Direct run | Full MACE run | Direct exact | MACE exact |
|---|---|---|---|---|---|
| `alt_masking` | dev6 | `m5/base/alt_masking/direct_seed42.json` | `m5/A3/alt_masking/mace_seed42.json` | 是 | 是 |
| `dedup_channel` | dev6 | `m5/base/dedup_channel/direct_seed42.json` | `m5/A3/dedup_channel/mace_seed42.json` | 是 | 否 |
| `modulo_absorb` | dev6 | `m5/base/modulo_absorb/direct_seed42.json` | `m5/A3/modulo_absorb/mace_seed42.json` | 否 | 否 |
| `overwrite_channel` | dev6 | `m5/base/overwrite_channel/direct_seed42.json` | `m5/A3/overwrite_channel/mace_seed42.json` | 是 | 否 |
| `sort_channel` | dev6 | `m5/base/sort_channel/direct_seed42.json` | `m5/A3/sort_channel/mace_seed42.json` | 否 | 否 |
| `swap_channels` | dev6 | `m5/base/swap_channels/direct_seed42.json` | `m5/A3/swap_channels/mace_seed42.json` | 否 | 否 |
| `dead_flag` | held1 | `m5/base/dead_flag/direct_seed42.json` | `m5/H2/dead_flag/mace_seed42.json` | 是 | 是 |
| `dict_slot` | held1 | `m5/base/dict_slot/direct_seed42.json` | `m5/H2/dict_slot/mace_seed42.json` | 是 | 是 |
| `parity_snap` | held1 | `m5/base/parity_snap/direct_seed42.json` | `m5/H2/parity_snap/mace_seed42.json` | 否 | 否 |
| `clamp_absorb` | held2 | `m5/H3/clamp_absorb/direct_seed42.json` | `m5/H3/clamp_absorb/mace_seed42.json` | 否 | 否 |
| `toggle_pair` | held2 | `m5/H3/toggle_pair/direct_seed42.json` | `m5/H3/toggle_pair/mace_seed42.json` | 否 | 否 |

- Direct 5/11 与 MACE 3/11 均由此表逐例复算；`m5/A3` 的另外 3 份（`dead_flag`、`dict_slot`、`parity_snap`）是 held1 的额外 MACE 重跑证据，不进入 dev6 的 6 例分母。
- 上表所有 22 份 run 文件的标签都是 `VRO`，不是 `VERIFIED_LIVE_MODEL_RUN`；`m5/C` 的 oracle 合同另有 `MANUAL_OR_SYNTHETIC` 输入，`m5/T` 的 12 轮 Direct 是 token/轮次对照，不在上表 11 例内。
- `m5/A` 的 9 份是更早的 MACE 运行，与 `A3` 有重叠用例；论文采用 `A3`，不采用 `A`。`m5/H` 的 3 份同理，论文 held1 采用 `H2`。

### 2.7 明确不作出的结论

本审计**不**作出以下结论：

- 不判定 M1–M4 一定没有运行过模型；只判定交付物中没有可核实证据。
- 不判定 M5 的 raw response 是伪造；只判定没有独立 live 服务证据。
- 不把“本机是 RTX 5060”当作“报告中的 AutoDL 4090D 不存在”的证明。
- 不把“没有日志”当作“一定有造假”。

---

## 3. Task B：Full MACE 设计逻辑审计

以下按用户列出的 8 个问题逐项给出源码位置、触发条件、最小复现和影响。源码行号以当前工作树为准；M5 冻结版 `94912c1` 在这些控制点上与当前版一致（当前只在 `loop.py`/`cli.py` 增加了 Evidence Gate 分支，未改变默认 Guard 来源、覆盖行为和停止条件）。

### B.1 实际默认 Guard 由 Qwen 还是 Composer 产生？

**源码位置**

- `mace/cli.py:255-256`：`--guard-source` 的 `choices=["qwen", "derived"]`，`default="qwen"`。
- `mace/loop.py:167-169`：`run_mode(..., guard_source: str = "qwen", ...)`。
- `mace/loop.py:319-336`：只有 `guard_source == "derived"` 时，才用 `_derived_expr(qwen_report)` 生成 Composer Guard，替换 `bundle_dict` 并重新 verify。
- `mace/loop.py:369-370`：最终 `final_guard` 取 `bundle_dict["mask_guard"]["expr"]`；在默认路径下，这个 bundle 的 guard 就是模型写的那个。
- `mace/verify.py:466-471`：`verify_bundle` 总会计算 `composition.derived_guard`，但它只是报告字段，不会自动替换模型 Guard。

**触发条件**

- 默认 `python -m mace.cli run ...`，未显式传 `--guard-source derived`。
- M5 的历史运行全部属于这一路径。

**最小复现**

- 查看任一 `m5/A3/*/mace_seed42.json`：顶层 `guard_source` 为 `"qwen"`，`final_guard` 与 `final_bundle.mask_guard.expr` 相同。
- 查看 `m5/A3/parity_snap/mace_seed42.json`：最终 Guard 是 Qwen 的 `even and (sum(xs) % 2 == 0 or sum(xs) % 2 == 1) or not even`，不是 Composer 的 `even and sum(xs) % 2 == 0`。

**影响/分类**

- 这是设计事实，不是 bug。  
- 分类：**不属于 A/B/C/D/E 的缺陷**；它是理解后续结果的前提。
- 重要含义：论文中的 “MACE 3/11” 是 **Qwen 写 Guard 的 Full MACE**；Composer 3/11 是另一条离线重放结果。两者不能混写。

### B.2 Guard 已正确、但局部关系失败时，是否仍继续修复？

**源码位置**

- `mace/loop.py:369-378`：

  ```python
  final_bundle = bundle_dict
  final_guard = (bundle_dict.get("mask_guard") or {}).get("expr")
  final_report = report
  rounds_used = round_id
  if report.get("status") != "OK":
      status = report.get("status", "UNKNOWN")
      break
  if report.get("all_relations_pass"):
      status = "ALL_VERIFIED"
      break
  ```

- `mace/verify.py:536-539`：

  ```python
  guard_ok = guard_report.get("status") in ("BOUNDED", "TESTED") and len(usable) > 0
  all_pass = all(r["status"] in ("BOUNDED", "TESTED") for r in results) \
      and guard_ok and soundness.get("status") in ("BOUNDED", "TESTED")
  ```

**触发条件**

- `all_relations_pass` 要求**所有** target/upstream/observer 关系都通过，并且 `guard_ok` 与 `observer_soundness` 都通过。
- 只要有一个局部关系失败（`REFUTED`/`INVALID`/`UNKNOWN`），即使 Guard 本身已经 `BOUNDED`，循环也不会停止。

**最小复现**

- `m5/A/alt_masking/mace_seed42.json`：第 1 轮 Guard `mode == 0 or mode == 1` 为 `BOUNDED`（在域上 exact），但 `U1`、`U2`、`U3` 为 `REFUTED`，`all_relations_pass=false`；循环继续到第 3 轮，最终状态 `ROUNDS_EXHAUSTED`。最终 Guard 仍是 exact，但系统没有把它识别为“Guard 已完成”。
- `m5/A3/alt_masking/mace_seed42.json`：3 轮 Guard 都是 `BOUNDED`，但关系失败，`all_relations_pass=false`；最终仍为 `ROUNDS_EXHAUSTED`。
- `m5/A3/dict_slot/mace_seed42.json`：第 2、3 轮 Guard `mode` 为 `BOUNDED`，但 `U1` 为 `REFUTED`，最终 `ROUNDS_EXHAUSTED`。

**影响/分类**

- 直接影响：多消耗轮次；给后续错误修复提供机会；把“Guard 已正确”误报成“未完成”。
- 在这些具体用例中，最终 Guard 仍被保留，所以没有直接损失 exact；但它为 B.7 的覆盖提供了条件。
- 分类：**B（停止条件/控制策略设计不完整）**，同时暴露 **C（`all_relations_pass` 把与 Guard 无关的 supporting 关系也当作停止必要条件）**。

### B.3 局部关系是否仅提供充分条件，而无法提供必要条件？

**源码位置**

- `mace/verify.py:162-184`：每个关系只在 `condition` 为真时检查 `expr`；失败计数为 0 就返回 `BOUNDED/TESTED`。这只证明 `condition => expr`，不证明 `expr => condition`。
- `mace/verify.py:187-211`：`_fixed_point_of` 只检查 `condition => snap_plus == snap_minus`；这是“条件是 no-op 的充分条件”，不是必要条件。
- `mace/verify.py:315-323`：observer 只在 `condition` 为真时检查 `observed_plus == observed_minus`；同样是单向充分条件。
- `mace/compose.py:50-73`：Composer 把这些条件当作可用的充分条件，用 OR/AND 拼成 Guard；没有否定、没有补集、没有覆盖推理。

**触发条件**

- 任何“条件成立时一定安全，但条件不成立时也可能安全”的情形。
- 真实 Guard 需要 `A 或 B`，但模型只给出 `A` 的一部分，或只给出每通道的充分条件，Composer 不会自动补出缺失的 `B`。

**最小复现**

- `m5/A3/sort_channel/mace_seed42.json`：
  - 参考 Guard：`pre or ((use_left or xs[0] == min(xs)) and (use_right or xs[-1] == max(xs)))`。
  - 模型合同：`U1` 是 `fixed_point`，但 `condition=True`、`expr=True`，被 `REFUTED`；`O0/O1` 的条件都是 `xs == sorted(xs)`。
  - Composer 只能得到 `xs == sorted(xs)`，在 10,912 个输入上 `incomplete=7046`。
  - 必要条件 `pre` 从未被模型提出；Composer 没有机制从“incomplete 的反例”中合成 `pre`。
- `m5/A3/dedup_channel/mace_seed42.json`：
  - Composer 得到 `len(xs) == 0`，`incomplete=100`；参考 Guard 是 `count(xs, xs[0] + 1) > 0`。
  - `O0` 的条件是 `len(xs) == 0`，但在该域上 `invariance_checked=0`、`counterexamples=[]`；条件从未为真，所以它没有 invariance witness。它之所以被接受，是因为“没有反例”被当成了通过（见 B.8/A.1），不是因为提供了有效覆盖。

**影响/分类**

- 这是结构性的：局部关系只能证明“这些条件足够”，不能证明“这些条件是全部”。
- 分类：**B（算法设计不完整，缺少必要条件生成/覆盖推理）**。  
- 对 exact 的影响：Composer 只能生成 sound-but-incomplete 的 Guard；它不会静默产生 false accept（组装结果还会被 `verify` 重新检查），但会大量产生 false reject/`INCOMPLETE`。

### B.4 Composer 的固定逻辑结构是否遗漏合法的析取项？

**源码位置**

- `mace/compose.py:46-99`，核心是：

  ```text
  guard = OR(所有 verified fixed_point 关系的 condition)
          OR
          AND(每个 channel 的 OR(该 channel 的 verified observer 关系的 condition))
  ```

  具体行：
  - `:50-51` 取 verified fixed_point；
  - `:52-55` 按 channel 收集 verified observer；
  - `:57` 计算缺失 channel；
  - `:58-59` 生成 `upstream_text` 与 `downstream_text`；
  - `:70-73` 拼接成 `upstream or downstream`；
  - `:78-87` 给出 `UNKNOWN` / `INCOMPLETE` / `COMPOSED`。

**对 11 个参考 Guard 的检查**

本次逐一对照了 `experiments/hidden/*_reference.json` 中的 11 个 Guard。它们全部落在上述结构内：

- `alt_masking`：单 channel 条件；
- `dead_flag`：每 channel `True`，AND 后仍为 `True`；
- `dedup_channel`：单 channel 条件；
- `dict_slot`：channel 0 `mode`，channel 1 `True`，AND 后为 `mode`；
- `modulo_absorb`：单 channel 条件；
- `overwrite_channel`：fixed_point `fn_0(xs)==0` OR 观察者条件；
- `parity_snap`：单 channel 条件；
- `sort_channel`：fixed_point `pre` OR 两个 channel 条件的 AND；
- `swap_channels`：前两个 channel `True`，第三个 channel 条件，AND 后为该条件；
- `toggle_pair`：两个 channel 同一条件，AND 后为该条件；
- `clamp_absorb`：单 channel 条件。

**结论：对当前 11 个参考 Guard，Composer 的结构没有“遗漏合法析取项”。**  
因此，Composer 3/11 不能主要归因于“结构表达式不够宽”；更直接的原因是关系本身错误、缺失、或无 witness 条件被误接受。

**但作为通用算法，结构确实不完整。** 它不能表达：

1. 两个分别验证的 fixed_point 条件的**合取**：  
   `(U1.condition and U2.condition) or ...`。Composer 只会把它们分别 OR。
2. **相关的跨 channel 分支**：  
   `(O0a and O1a) or (O0b and O1b)`。Composer 会分配成 `(O0a or O0b) and (O1a or O1b)`，这是一个更弱的交叉积，可能接受混合分支。
3. **否定条件**：  
   除非模型把 `not c` 直接写成某个 condition，Composer 不会对一个已验证条件取反。
4. **联合约束**：  
   一个 channel 的条件依赖另一个 channel 的条件时，只能把整个联合条件塞进单个 relation；Composer 不会跨 relation 求解。

**触发条件与最小复现（通用）**

- 设两个 fixed_point 关系分别有充分条件 `p`、`q`，但真实 Guard 是 `(p and q) or r`。
- Composer 得到 `p or q or r`（更弱）。它在重新验证时可能因 false accept 被判 `REFUTED`，或因 false reject 被判 `INCOMPLETE`；不会静默通过。
- 因此这类结构缺陷的后果是 **exact 下降**，不是“错误的 Guard 被当成正确”。

**分类：B（表达力/设计不完整）**，不是 A（逻辑本身不可靠）。  
Composer 的 OR/AND 组合在“每个输入条件都是充分条件”的前提下是 sound 的；它的问题是 completeness，不是 soundness。

### B.5 upstream、observer 与 target_effect 的作用域和时间状态是否一致？

**设计上的作用域（`mace/contracts.py:27-37`、`mace/verify.py:37-45`、`mace/prompts.py:73-93`）**

| 字段 | 设计作用域 | 代码中的编译/求值环境 |
|---|---|---|
| `target_effects` | 入口参数 + A 前局部变量（plain）+ A 后局部变量（`<name>_post`） | `verify.py:249-252`，`effect_values` 见 `:238-245` |
| `upstream` | 仅入口参数 | `verify.py:254-256`，`input_values` 见 `:230-231` |
| `observers.expr` | 入口参数 + A 后局部变量（plain） | `verify.py:281` 用 `post_env_sorts`；`:299-300` 用 `post_values` |
| `observers.condition` | **设计上仅入口参数**（schema 明说 “over the entry arguments”） | **编译**用 `post_env_sorts`（`:281`），但**求值**用 `input_values`（`:315`） |
| `mask_guard` | 仅入口参数 | `verify.py:342` 用 `input_sorts` |

**问题 1：observer condition 的编译作用域和求值作用域不一致（C）**

- `mace/verify.py:281` 把 `rel` 的 `expr` 和 `condition` 都按 `post_env_sorts` 编译；`post_env_sorts` 包含 A 后局部变量（`:226-228`）。
- `mace/verify.py:315` 却用 `input_values(row)` 求值 `condition`；`input_values` 只含入口参数（`:230-231`）。
- 触发条件：observer 的 `condition` 使用一个 A 后局部变量（plain 名），例如 `total > 0`，而 `total` 只在 `snap_plus` 里。
- 结果：编译通过，求值抛 `TermError: unknown variable total`；`:324-327` 把它计入 `eval_errors`，最终 observer 状态是 `REFUTED`，而不是 `INVALID`。
- 最小复现：fixture `clamp_absorb`（A 后局部变量有 `total`），构造 observer：
  ```json
  {"id":"O0","channel":0,
   "expr":"min(total, 10) if cap else total",
   "condition":"total > 0"}
  ```
  `post_env_sorts` 含 `total`，所以 `_compile` 成功；`input_values` 不含 `total`，所以每个输入都计入 `evaluation_errors`，observer 被 `REFUTED`。
- 影响：一个本来可能正确的 observer 条件被错误地判为反例；修复反馈只会说“表达式无法求值”，不会指出“condition 只能引用入口参数”。这会消耗轮次，并可能导致后续覆盖。
- 分类：**C（实现 bug/作用域不一致）**。

**问题 2：同一 channel 多个 observer 会让 soundness 失败（C）**

- `mace/contracts.py:159-162` 明确允许“多个 observer 描述同一 channel，每个 case 一个”，Composer 也会 OR 它们的条件。
- 但 `mace/verify.py:406-407` 要求：
  ```python
  sorted(r["channel"] for r in observer_results) == list(range(channels))
  ```
  如果 channel 0 有 `O0,O1,O2`，排序结果是 `[0,0,0]`，不等于 `[0]`，于是 `soundness` 保持 `UNKNOWN`（`reason: "no complete observer set"`）。
- 最小复现：`m5/A3/parity_snap` 的最终合同有 `O0/O1/O2` 三个 channel 0 observer；`observer_soundness` 为 `UNKNOWN`。`m5/A3/dedup_channel`、`m5/H3/clamp_absorb` 同样。
- 影响：即使所有 observer 都正确、Guard 也 exact，`all_relations_pass` 仍可能因为 `soundness=UNKNOWN` 为 false；循环继续，给覆盖创造机会。
- 分类：**C（实现 bug：允许的合同形状与 soundness 检查不一致）**。

**问题 3：`<name>_post` 在 guard/observer 中的使用**

- `mask_guard` 只按入口参数编译（`verify.py:342`），observer `expr` 只按 A 后 plain 名编译（`:281,299-300`）。
- 模型经常把 `_post` 写进 guard 或 observer（例如 `total_post <= 10 or not cap`、`total_post % 2 == 0`），这会被判 `INVALID`。
- 这是模型对 schema 的语义错误（D），但 schema 的提示/修复补丁没有提供“把 `_post` 改回 plain 名”的结构化修复（见 B.7/C.6），因此错误会重复。
- 分类：**D（模型语义错误）**，并叠加 **B（修复接口不完整）**。

### B.6 局部关系通过验证是否足以支持最终 Guard？

**源码位置**

- `mace/verify.py:536-539`：`all_relations_pass` 同时要求所有 relation 通过、`guard_ok`、`observer_soundness` 通过。
- `mace/loop.py:373-378`：只有 `all_relations_pass` 才设置 `ALL_VERIFIED`。
- `mace/verify.py:360-400`：Guard 是在实际 paired executions 上独立检查的，不依赖 relation 的通过状态。

**结论**

- **不是“局部关系通过 ⇒ 最终 Guard 正确”。**  
  `all_relations_pass` 额外要求 `guard_ok`，所以系统不会仅凭关系通过就宣称 Guard 已验证。
- **也不是“最终 Guard 正确 ⇒ 局部关系通过”。**  
  `m5/A/alt_masking`、`m5/A3/alt_masking`、`m5/A3/dict_slot` 都有 exact Guard，但局部关系失败，`all_relations_pass=false`。
- **`ALL_VERIFIED` 只表示“在声明有限域上，所有关系和 Guard 都通过”**，不是证明；`BOUNDED/TESTED` 都不是 `PROVEN`。
- 真正支撑最终 Guard 的是 `guard_ok` 的独立 bounded check；局部关系不是它的充分条件，也不是必要条件。

**影响/分类**

- 把 `all_relations_pass` 当作停止条件，会把“Guard 已正确但某个 supporting 关系错误”误判为未完成。  
- 分类：**B（控制策略）**；`all_relations_pass` 包含所有 relation 这一点也有 **C** 的成分（把未被 Composer 使用的 supporting 关系也当作必须通过）。

### B.7 为什么会发生正确候选被后续修复覆盖？

**源码位置**

- `mace/loop.py:369-371`：每个有效轮次无条件执行：
  ```python
  final_bundle = bundle_dict
  final_guard = (bundle_dict.get("mask_guard") or {}).get("expr")
  final_report = report
  ```
  没有“保留历史最优 Guard”的逻辑。
- `mace/loop.py:376-378`：只有 `all_relations_pass` 才停止；Guard 已 exact 但某个关系失败时继续。
- `mace/loop.py:382-392`：失败反馈包含 Guard 失败和关系失败；在 Qwen Guard 模式下，模型会同时看到“关系失败”，被鼓励继续修改合同/Guard。
- `mace/loop.py:389-392`：如果 `_same_relations` 认为表达式/条件没变，会附加“必须修改”的提示；这会增加模型改动 Guard 的压力。

**最小复现（真实存储用例）**

1. `m5/A3/parity_snap/mace_seed42.json`
   - 第 1 轮 Guard：`even and sum(xs) % 2 == 0`，`guard.status = BOUNDED`（在 170 个输入上 exact）。
   - 第 2 轮：`even and total_post % 2 == 0 or not even`，`INVALID`。
   - 第 3 轮：`even and (sum(xs) % 2 == 0 or sum(xs) % 2 == 1) or not even`，逻辑上等于 `True`，`REFUTED`（`unsound=127`）。
   - 最终 `final_guard` 是第 3 轮的错误 Guard；第 1 轮的 exact Guard 被覆盖。
2. `m5/H2/parity_snap/mace_seed42.json`
   - 第 1 轮同样是 `even and sum(xs) % 2 == 0`，`BOUNDED`。
   - 第 2 轮 `even`，`REFUTED`；第 3 轮 `even and sum(xs) % 2 == 0 or not even`，`REFUTED`（`unsound=85`）。
   - 最终 Guard 错误。

`m6/repair.md` 也明确记录：

- `A3/qwen parity_snap`：`valid rounds (fit)=1`，`final eval=wrong (u=62,i=0)`，`online eval=exact`。
- `H2/qwen parity_snap`：`valid rounds (fit)=1`，`final eval=wrong (u=41,i=0)`，`online eval=exact`。
- held1 的 MACE A：`final=2`，`online=3`。

**对论文 11 例的影响**

- 论文的 held1 使用 `H2`；`H2/parity_snap` 的覆盖直接造成 **1 例 exact 损失**（final 2/3 → online 3/3）。
- `A3/parity_snap` 不在 dev6 的 6 个评分用例中（parity 属于 held1），所以它是同一 bug 的额外诊断证据，不直接改变 dev6 的 1/6。
- 因此：**至少 1/11 的 MACE 失败不是模型能力问题，而是 Guard 保留策略问题。**

**分类**

- **B（控制策略缺少保留/最优选择）**；
- **C（实现上无条件覆盖 `final_guard`）**；
- 不是 D（模型语义）单独造成；模型在第 2/3 轮确实也犯了错，但第 1 轮已经给出正确 Guard。

### B.8 是否存在将 INVALID、UNKNOWN、BOUNDED 混用的情况？

**状态定义**

- `BOUNDED`：在声明域上全量检查，无失败（`verify.py:181`）。
- `TESTED`：在抽样域上检查，无失败（同一 `level` 机制）。
- `REFUTED`：至少一个反例（`verify.py:181`、`:393`、`:328-331`）。
- `INVALID`：表达式/条件无法在作用域内编译或类型错误（`verify.py:159`、`:286`）。
- `UNKNOWN`：没有可用输入、没有完整 observer 集、没有 fixed_point 等（`verify.py:403-405`、`:448-450`、`:648`）。
- `INCOMPLETE`：Composer 缺少 channel（`compose.py:81-84`）。
- `UNVERIFIED`：Evidence Gate 没有 witness（`evidence_gate.py:100-109`）。
- `ABSENT`/`ERROR`：无 Guard / 沙箱错误（`m6_symbolic.py:61-73` 等）。

**发现 1：fixed-point 聚合会在成员已 REFUTED 时仍报 BOUNDED（C）**

- `mace/verify.py:443-460`：
  ```python
  fixed_all = [r for r in results
               if r["kind"] == "upstream" and r.get("role") == "fixed_point"]
  fixed_ok = [r for r in fixed_all if r["status"] in ("BOUNDED", "TESTED")]
  ...
  failures = sum(r.get("fixed_point_failures") or 0 for r in fixed_all)
  checked_fp = sum(r.get("fixed_point_checked") or 0 for r in fixed_all)
  ...
  fixed_point = {"status": level if failures == 0 else "REFUTED", ...}
  ```
- `fixed_point_failures` 只在 relation 自身 status 为 GOOD 时才会被设置（`:257-270`）。如果 fixed_point 的 `expr` 已经被 `REFUTED`，它没有 `fixed_point_failures`，于是聚合 `failures=0`、`checked=0`，状态变成 `BOUNDED`。
- 真实复现：`m5/A3/parity_snap/mace_seed42.json` 的 `final_report.composition.upstream_fixed_point`：
  ```json
  {"status": "BOUNDED", "checked": 0, "failures": 0,
   "reason": "every fixed-point condition implies A is a no-op on the local state"}
  ```
  但同一报告里 `U1`、`U2` 都是 `REFUTED`。
- 影响：诊断层会把“所有 fixed_point 都被反驳”误报为“fixed_point 已验证”；`all_relations_pass` 仍会因 `results` 中的 REFUTED 而为 false，所以不直接改变 Guard，但会误导修复/报告。
- 分类：**C（聚合实现 bug）**。

**发现 2：重复 observer 使 soundness 变成 UNKNOWN（C）**

- 见 B.5 问题 2。`contracts.py:159-162` 允许重复 channel，`verify.py:407` 却要求 channel 列表等于 `range(channels)`；`verify.py:412` 又只取每 channel 的第一个 observer。
- 影响：`all_pass` 被错误阻断；这是“INVALID/UNKNOWN 混用”的一个具体来源：合同形状是合法的，却被报成“no complete observer set”。

**发现 3：Composer 的 INCOMPLETE 在外层被折叠成 UNKNOWN（C/报告）**

- `mace/verify.py:466-471`：
  ```python
  derived = {
      **{k: v for k, v in composed.items() if k != "status"},
      "compose_status": composed["status"],
      "status": "UNKNOWN",
  }
  ```
  如果 `composed["expr"]` 为空，`derived.status` 固定为 `UNKNOWN`；`compose_status` 仍保留 `INCOMPLETE`/`UNKNOWN`，但只看外层 `status` 的分析会把两者混在一起。
- 影响：报告统计中“INCOMPLETE”和“UNKNOWN”可能被合并；不直接改变 Guard，但会让失败归因失真。

**发现 4：Evidence Gate 的 filtered_report 把 INVALID/REFUTED 统一写成 UNVERIFIED（C/报告）**

- `mace/evidence_gate.py:159-174`：只保留 `WITNESS_VERIFIED` 的 status，其余一律写成 `UNVERIFIED`。
- 这是 Gate 的设计（只允许 witness-verified 关系进入 Composer），但做失败分析时必须同时看 `verifier_status`，否则无法区分“类型错误”和“无 witness”。
- 影响：Gated 3/11 的数字可复算，但不能用 filtered status 解释失败原因。

**发现 5：无 witness 条件被当作 BOUNDED 并进入 Composer（A/C）**

- `mace/verify.py:162-184`：`checked=0, failures=0` 时仍返回 `level`（`BOUNDED/TESTED`）。
- `mace/compose.py:48`：只按 `status in ("BOUNDED","TESTED")` 取关系，不检查 `checked > 0`，也不检查 observer 的 `invariance_checked > 0`。
- 真实复现：`m5/A3/dedup_channel` 的 `O0` 条件 `len(xs) == 0`，在该域上 `checked=240`（240 个 usable 输入都被走过）、`invariance_checked=0`（条件从未为真）、`counterexamples=[]`，verifier 仍给 `BOUNDED`；Composer 使用它，得到 `len(xs) == 0`，`incomplete=100`。Evidence Gate 将其判为 `UNVERIFIED`，所以 gated 版本没有 Guard（`None`）。
- 影响：无 witness 的条件可以污染 Composer，造成 incomplete；Gate 能过滤，但默认路径没有。
- 分类：**A（`BOUNDED` 的定义缺少非空 witness 要求，形式化规则过弱）** + **C（Composer 不检查 `checked`）**。

---

## 4. Task C：问题分类

### A. 形式化定义或推理规则本身错误

| ID | 问题 | 证据 | 影响 |
|---|---|---|---|
| A1 | `BOUNDED` 只要求“没有反例”，不要求至少一个满足条件且被检查的 witness；条件在声明域上从未为真（vacuously true）时仍被当成有效证据 | `verify.py:162-184`；`m5/A3/dedup_channel` 的 `O0`：`checked=240`、`invariance_checked=0`、`counterexamples=[]`、`status=BOUNDED`；`evidence_gate.py:106-109` 将其改为 `UNVERIFIED` | 默认 Composer 可被无 witness 条件污染，产生 incomplete；是 dedup 组合失败的直接原因之一 |
| A2 | “fixed_point 聚合状态”的规则没有把成员 relation 的 `REFUTED` 计入聚合 | `verify.py:452-455`；`m5/A3/parity_snap` 聚合报 `BOUNDED/checked=0`，但 U1/U2 是 `REFUTED` | 诊断误报；不直接改 Guard，但会误导修复/报告 |

严格说，A2 也可归入 C（实现时漏了成员状态）；本文把它放在 A，因为“聚合状态如何定义”本身没有写清楚。

### B. 算法设计不完整，缺少必要条件生成能力

| ID | 问题 | 证据 | 影响 |
|---|---|---|---|
| B1 | 局部关系只验证 `condition => expr` / `condition => invariance`，没有反向检查、否定或覆盖推理；无法生成必要条件 | `verify.py:167-181`、`:200-211`、`:315-323`；`compose.py:50-73` | Composer 只能得到充分条件拼出的 Guard，容易 incomplete |
| B2 | Composer 固定结构缺少一般布尔表达力：不能合取两个分别验证的 fixed_point 条件、不能表达相关跨 channel 分支、不能取反 | `compose.py:50-73` | 对 11 个参考 Guard 不构成问题；对更大程序会漏解/产生 incomplete |
| B3 | 修复补丁只能 `revise` 已有 id、`add_observers`，不能新增 upstream fixed_point，也不能改 `role`/`channel` | `loop.py:85-115`；`prompts.py:318-325` | 初始合同漏掉 fixed_point 或把 role 写错后，后续无法修复；sort_channel 的 `pre` 就是这种情形 |
| B4 | 停止条件要求所有局部关系通过；没有“Guard 已 exact 就保留”的策略 | `loop.py:369-378`；`verify.py:536-539` | 正确 Guard 被后续轮次覆盖（parity_snap） |
| B5 | 没有 coverage-directed synthesis：不会从 incomplete 反例中合成缺失条件，也不会自动补 `True` observer | `compose.py:57-84`；`loop.py:382-392` | 缺失 channel/条件时只能靠模型再次猜 |
| B6 | 把未被 Composer 使用的 `supporting` 关系也纳入 `all_relations_pass` | `verify.py:537`；`loop.py:376` | exact Guard + 一个无关 supporting 失败 → 不停止，增加覆盖风险 |

### C. 实现 Bug

| ID | 问题 | 证据 | 影响 |
|---|---|---|---|
| C1 | observer `condition` 编译用 `post_env_sorts`，求值用 `input_values` | `verify.py:281` vs `:315` | 使用 A 后 plain 局部变量的 condition 编译通过、求值报错，被误判 `REFUTED` 而非 `INVALID` |
| C2 | 同一 channel 多个 observer 时，`observer_soundness` 要求 channel 列表等于 `range(channels)` | `verify.py:406-407` vs `contracts.py:159-162` | 合法合同被判 `UNKNOWN`，阻断 `ALL_VERIFIED`，触发继续修复 |
| C3 | fixed_point 聚合只累加 `fixed_point_failures`，忽略 relation 自身 `REFUTED` | `verify.py:452-455`；`m5/A3/parity_snap` | 聚合报 `BOUNDED/checked=0`，与成员状态矛盾 |
| C4 | Composer 只按 status 取关系，不检查 `checked>0`，也不检查 observer 的 `invariance_checked>0` | `compose.py:48`；`verify.py:162-184` | 无 witness 条件进入组合；dedup_channel 的 `O0` 是实例 |
| C5 | `_same_relations` 比较 group/id/expr/condition/guard，不比较 `role`/`channel` | `loop.py:118-128` | role/channel 改了但被当成“未修改”，反馈错误 |
| C6 | `revise` 不允许改 `role`/`channel`；没有 `add_upstream` | `loop.py:94`；`prompts.py:319-323` | 初始 role 写错/缺 fixed_point 无法修复；观察者 channel 写错也无法改，只能追加 |
| C7 | generic 基线多出的 summary 调用计入 `usage.calls`，但没有独立 exchange/raw_response | `m5/*/generic_seed42.json` 中 `usage.calls` 比 exchange 多 1；14 份 | generic 基线的来源记录不完整；不影响 Direct/Full MACE |
| C8 | `derived` 外层 status 在 `composed.expr` 为空时固定 `UNKNOWN` | `verify.py:466-471` | `INCOMPLETE` 与 `UNKNOWN` 在统计层被折叠 |
| C9 | `filtered_report` 把非 witness 关系统一写成 `UNVERIFIED` | `evidence_gate.py:159-174` | gated 统计无法区分 `INVALID` 和“无 witness”；分析时必须回看 `verifier_status` |

### D. 模型语义推理错误

这些是真实存在的模型错误，不能忽略；但它们不是全部原因。

| ID | 例子 | 证据 |
|---|---|---|
| D1 | parity_snap 最终 Guard 变成 `even and (sum%2==0 or sum%2==1) or not even`，逻辑上等于 `True` | `m5/A3/parity_snap/mace_seed42.json`，`unsound=127` |
| D2 | overwrite_channel 最终 Guard `keep or not keep`，等于 `True` | `m5/A3/overwrite_channel/mace_seed42.json`，`unsound=28` |
| D3 | sort_channel 最终 Guard `xs == sorted(xs)`，忽略 `pre` 和下游 `use_left/use_right` | `m5/A3/sort_channel`，`incomplete=7046` |
| D4 | clamp_absorb Guard 使用 `total_post`，在 guard scope 中非法 | `m5/H3/clamp_absorb`，`INVALID` |
| D5 | dedup_channel 最终 Guard 为 `len(xs) == 0 or (pre and distinct(xs) and ...)`，被 `INVALID`；Composer 退化为 `len(xs) == 0`，`incomplete=100` | `m5/A3/dedup_channel/mace_seed42.json` |
| D6 | toggle_pair 最终 Guard `flag`，`unsound=0`、`incomplete=3`（18 个输入中 3 个 false reject） | `m5/H3/toggle_pair/mace_seed42.json` |

D1/D2 是“正确 Guard 在后续轮次被改坏”的模型侧表现；其根因还包括 B4（没有保留策略）。

### E. 实验来源不明或证据缺失

| ID | 问题 | 证据 | 结论 |
|---|---|---|---|
| E1 | M1–M4 的 7B/14B/32B 运行没有原始 request/response | `runs/` 为空；报告引用 `/root/...` 不存在；归档无 M1–M4 run | `UNVERIFIED_MODEL_ORIGIN` |
| E2 | M1 的 GPU/驱动/主机声明没有 `nvidia_smi.txt` | `docs/M1_report.md:17-21`；工作树/归档无该文件 | 无法核实 |
| E3 | M5 没有独立 Ollama 服务日志/GPU 日志/hostname/endpoint | M5 JSON 无 `endpoint`/`hostname`；`events.jsonl` 是验证事件；`runtime.ps` 是客户端记录 | 存储转录可复算，非 live |
| E4 | generic 基线 summary 调用未单独保存 raw_response | `usage.calls` 比 exchange 多 1（14 份） | generic 基线来源记录有缺口 |
| E5 | 当前审计机不是报告声称的 AutoDL 4090D | 本机 RTX 5060 8GB，无 Ollama | 不能据此证明报告为假；只说明无法本机复核 |

---

## 5. 六个直接回答

### 5.1 历史 Qwen 模型调用究竟是否有可核实的原始证据？

**分两层回答：**

- **M5：有“存储转录”级证据，没有“实时服务”级证据。**  
  86 份运行文件包含 `request`、`raw_response`、Ollama 风格 token/耗时、provider/model、时间；270 个 M5 文件与冻结清单哈希一致。可以离线复算 Guard 和 exact 分数。  
  但没有独立服务日志、GPU 日志、hostname、endpoint 记录，因此只能标 **`VERIFIED_REPLAY_OF_MODEL_OUTPUT`**，不能标 **`VERIFIED_LIVE_MODEL_RUN`**。
- **M1–M4：没有可核实的原始证据。**  
  `runs/` 为空，`/root/m2_*`/`/root/m4_*` 不存在，归档没有这些 run 文件，也没有 `nvidia_smi.txt` 或 Ollama 日志。报告中的模型成绩只能标 **`UNVERIFIED_MODEL_ORIGIN`**。

“没有证据”不等于“已证明没有发生”；但在论文中，不能把 M1–M4 的数字写成已核实的真实 Qwen 推理结果。

### 5.2 声称使用 AutoDL GPU 的报告与实际环境是否一致？

- **M1–M4：无法确认。**  
  报告声称 RTX 4090 D 24564 MiB、驱动 580.76.05/CUDA 13.0、AutoDL 16 核 80 GB、Ollama `127.0.0.1:11434`；但交付物没有 `nvidia_smi.txt`、没有服务日志、没有 hostname。M1 报告还明确提到更早的 AutoDL 实例处于无卡模式，但那段日志也没有交付。
- **M5：元数据与“24 GB 级 GPU 上的 Ollama”一致，但不能独立确认主机身份。**  
  `runtime.ps` 显示 21.78 GB 模型全部驻留显存、Q4_K_M、digest、`+08:00` 时区；这与 24 GB 级 GPU 自洽，也与本机 8 GB RTX 5060 不一致。它是客户端通过 `/api/ps` 记录的响应，不是独立 GPU 监控。
- **审计机：** RTX 5060 8GB、无 Ollama；它不是报告声称的运行机器。这个差异不能证明报告虚构，只能说明本机无法复核。
- **结论：** 没有发现可直接判定“环境声明为假”的证据；也没有发现可确认“AutoDL 4090D 实际运行”的独立证据。若期刊要求 live 运行证明，M1–M4 不合格，M5 也只达到“存储转录”级。

### 5.3 旧版和当前版 Full MACE 最终 Guard 到底由谁产生？

- **旧版 M1–M4（报告所述）：** 按报告和代码默认路径，Guard 由 Qwen 写；但没有原始响应，无法核实。代码默认 `guard_source="qwen"`（`loop.py:167-169`）。
- **当前 M5 Full MACE：** 26 份 MACE 运行全部 `guard_source: "qwen"`；`final_guard` 来自 `final_bundle.mask_guard.expr`，即 Qwen 在最后一轮写的 Guard。
- **Composer：** 只有 `--guard-source derived`（`loop.py:319-336`）、oracle-derived（`loop.py:201-222`）或 M6 离线重放时才产生最终 Guard。`verify_bundle` 总会计算 `composition.derived_guard`，但它只是诊断字段，不替换模型 Guard。
- **Cell C（M5/C）：** 人工 reviewed contract 是 `MANUAL_OR_SYNTHETIC` 输入；最终 Guard 仍由 Qwen 写（`guard_source=qwen`）。
- **Cell D / Composer 3/11：** 确定性 Composer 产生；不是 Qwen 写的，也不是一次新的 live 模型运行。

因此，论文里的 “Full MACE 3/11” = **Qwen 写 Guard 的 Full MACE**；不要把 “Composer 3/11” 或 “Gated 3/11” 误写成同一个 Guard 来源。

### 5.4 算法存在什么逻辑问题和结构性限制？

按重要性排序：

1. **正确 Guard 会被后续轮次覆盖**：每个有效轮次无条件写 `final_guard`；停止条件要求所有关系通过；正确 Guard + 一个失败关系 → 继续修复 → 可能改坏（parity_snap 两例）。
2. **局部关系只有充分条件，没有必要条件生成**：`condition => expr` 单向检查；Composer 只能拼充分条件；无法从 incomplete 反例合成缺失条件（sort_channel 缺 `pre`，dedup_channel 缺正确条件）。
3. **Composer 结构在一般情形下表达力不完整**：不能合取两个 fixed_point、不能表达相关跨 channel 分支、不能取反；对 11 个参考 Guard 恰好够用，所以不是 3/11 的主因，但是更大程序的限制。
4. **修复接口不能新增 upstream fixed_point，也不能改 role/channel**：初始合同漏掉 fixed_point 或 role 写错后，后续无法修复。
5. **observer condition 作用域不一致**：编译允许 A 后局部变量，求值只用入口参数；会把本可正确的条件误判为 `REFUTED`。
6. **同一 channel 多个 observer 会使 soundness 变成 `UNKNOWN`**：合同明确允许多个 observer，但 soundness 要求 channel 唯一；阻断 `ALL_VERIFIED`，增加覆盖风险。
7. **fixed-point 聚合状态错误**：成员已 `REFUTED` 时聚合仍可能报 `BOUNDED/checked=0`。
8. **无 witness 条件被当成 `BOUNDED` 并进入 Composer**：没有有效 witness（`checked=0`，或 observer 的 `invariance_checked=0`）仍可按 status 进入组合；Gate 能过滤，默认路径不能。
9. **状态语义在报告层被折叠**：`INCOMPLETE`→`UNKNOWN`、`INVALID`/`REFUTED`→`UNVERIFIED`；不影响 Guard 本身，但会影响失败归因。

### 5.5 哪些问题会直接导致 Exact 下降？

**直接、有存储证据的：**

1. **Guard 覆盖（B4/C）**：`H2/parity_snap` 第 1 轮 exact，最终 wrong；论文 held1 从 online 3/3 降到 final 2/3，直接损失 **1/11**。`A3/parity_snap` 是同一 bug 的额外证据（不在 dev6 评分集）。
2. **Composer 只能拼充分条件、缺必要条件（B1/B2）**：`sort_channel` 的 Composer `xs==sorted(xs)` incomplete 7046；`dedup_channel` 的 Composer `len(xs)==0` incomplete 100。即使关系本身正确，缺少 `pre`/正确 observer 条件也会 incomplete。
3. **无 witness 条件污染 Composer（A1/C4）**：`dedup_channel` 的 `O0` 条件 `len(xs)==0` 没有 witness，仍被 verifier 接受，Composer 用它生成 incomplete Guard；Gate 过滤后直接没有 Guard。
4. **模型语义错误（D）**：parity 的 tautology、overwrite 的 `keep or not keep`、sort 忽略 `pre`、clamp 使用 `total_post`、dedup 无效表达式、toggle `flag` 等；这些是真实错误，且会直接产生 wrong/incomplete Guard。
5. **重复 observer 导致 soundness `UNKNOWN`（C2）**：`parity_snap`、`dedup_channel`、`clamp_absorb` 都有多个同 channel observer；这会让 `all_relations_pass` 为 false，触发继续修复，间接导致覆盖。
6. **停止条件把 supporting 关系也当必要条件（B6）**：`alt_masking`、`dict_slot` 的 Guard 已 exact，但局部关系失败，系统不停止；这些具体用例最终仍保留了 exact Guard，但增加了覆盖风险。

**不是直接原因、但会影响报告/归因的：**

- fixed-point 聚合 `BOUNDED/checked=0`（C3）：诊断错误，不直接改 Guard。
- `derived` 状态折叠（C8）、Gate 的 `UNVERIFIED` 折叠（C9）：报告/统计问题。
- observer condition 作用域 bug（C1）：目前没有在 11 个最终 Guard 中形成直接 exact 损失的存储证据，但它是潜在的直接损失点；一旦模型写出 plain post-local 条件，就会被误判。
- generic summary 调用缺失（C7）：基线来源问题，不是算法问题。

### 5.6 哪些数字暂时不能出现在正式论文里？

#### 不能作为“已核实结果”出现

| 数字/声明 | 原因 | 建议 |
|---|---|---|
| M1–M4 的 7B/14B/32B 成绩（含 “MACE 2/6 = 最好基线 2/6”等） | `UNVERIFIED_MODEL_ORIGIN`；无原始 run | 不写入正式结果；如必须提及，只能作为“历史报告中的未核实数字”放在附录/限制 |
| M1 的 RTX 4090 D、24564 MiB、驱动 580.76.05/CUDA 13.0、AutoDL 16 核 80 GB | 无 `nvidia_smi.txt`/hostname/服务日志 | 不作为硬件事实；最多写“报告声称”，并注明无法核实 |
| M1–M4 的 token/墙钟/成本 | 无原始 usage 记录 | 不作为效率结论 |
| “M1–M4 的 runs/ 可逐条复算” | 交付物中 `runs/` 为空、`/root` 路径不存在 | 删除该可复现性声明，或补齐原始文件 |

#### 可以出现，但必须带来源标签

| 数字/声明 | 允许的写法 | 不允许的写法 |
|---|---|---|
| M5 Direct 5/11、Full MACE 3/11、Composer 3/11、Gated 3/11 | “基于 M5 存储转录的离线复算；有 request/raw_response，哈希冻结；无独立服务/GPU 日志” | “已核实的实时 Qwen/AutoDL 运行结果” |
| M5 token/墙钟（如 23,626 vs 141,081；102.3 vs 704.5 s） | “存储 usage 汇总” | “已核实的 GPU 实测成本” |
| M5 的 `qwen2.5-coder:32b`、Q4_K_M、21.78 GB `size_vram` | “客户端记录的 `/api/ps`/`/api/show` 元数据” | “独立 GPU 监控证明” |
| Composer 3/11 | “对 M5 合同进行确定性离线重组的结果” | “Full MACE 在线运行结果” |
| Gated 3/11 | “对 M5 合同进行 Evidence Gate 离线重放的结果；gate 0 gain/0 loss” | “Gate 提升了准确率” |
| M6 Symbolic 7/11 | “确定性符号执行，无模型调用” | “Qwen 的结果” |
| M6 Symbolic + human summaries 11/11 | “符号执行 + 人工写的 helper summaries；非自主结果” | “自主算法 11/11” |
| M6 Induction 10/11 sufficient、0/11 necessary | “有界归纳的充分方向；必要方向 0/11” | “完整 Guard 10/11” |
| Direct-First 6/11 | “固定 Direct/MACE 提案的离线模拟；不是在线算法” | “新算法在线达到 6/11” |
| 人工 reviewed contract 9/9 | “诊断上限 / Cell C 上限” | “系统准确率” |
| “MACE 优于 Direct” | 不应出现：Direct 5/11，MACE 3/11 | 任何“新算法胜过强基线”的表述 |
| “Gate 有收益” | 不应出现：0 gain / 0 loss | “Gate 改善准确率” |

#### 特别提醒

- M5 的 3/11 是在 **Qwen 写 Guard** 的默认路径下得到的；Composer 3/11 是另一条离线路径。两者不能合并成“MACE 3/11 + Composer 3/11 = 6/11”。
- `held1` 的 1 例覆盖损失可以用 M6 `online` 保留策略恢复，但 `online` 是离线 fit-half 重放，不是新的在线算法；不能写成“新方法 4/11”。
- M6 的 11/11 依赖人工 helper summaries；不能写成“符号引擎自主 11/11”。
- M6 的 10/11 只是 sufficient 方向；necessary 方向 0/11，不能写成“归纳出完整 Guard”。

---

## 6. 可以安全写进论文的事实

在不夸大的前提下，以下事实有存储证据或确定性代码支持：

1. **M5 有 86 份存储转录，237 个 exchange；MACE/Direct 的 request/raw_response/stats 完整；270 个 M5 文件哈希匹配冻结清单。**  
   这支持“结果可由存储转录复算”，不支持“实时服务来源已核实”。
2. **在 M5 的 11 个评分用例上，Direct 5/11，Full MACE（Qwen Guard）3/11，Composer 3/11，Gated 3/11。**  
   MACE 没有超过 Direct；Composer 与 MACE 打平但 exact 集合不同（Composer 多了 parity_snap，少了 dedup/overwrite）。
3. **MACE 的 3 个 exact 是 alt_masking、dead_flag、dict_slot；Direct 的 5 个是 alt_masking、dedup_channel、overwrite_channel、dead_flag、dict_slot。**  
   这说明 MACE 不是“全面更强”，而是“在不同用例上得失不同”。
4. **M6 的 online 保留策略在 held1 上把 MACE 从 2/3 恢复到 3/3；`H2/parity_snap` 第 1 轮 exact，最终被覆盖。**  
   这支持“至少 1 例失败是控制策略，不是模型能力”。
5. **Composer 对 11 个参考 Guard 的结构是够用的；它的 3/11 主要来自关系错误/缺失/无 witness 条件，而不是“参考 Guard 超出结构”。**  
   这可以避免把 Composer 的失败错误地归因于“表达式语言不够宽”。
6. **Evidence Gate 在 11 例上是 0 gain / 0 loss。**  
   它修正了无 witness 条件的组合，但没有提高 exact；不能声称收益。
7. **M6 的 symbolic/induction 是确定性结果；11/11 依赖人工 summaries；Direct-First 6/11 是离线固定提案模拟。**  
   这些都必须与“在线 MACE”分开报告。

---

## 7. 审计方法与可复核命令（只读）

本次审计使用的只读检查包括：

```bash
# 1. M5 文件/字段/统计
python - <<'PY'
import glob, json
files = glob.glob('m5/*/*/*_seed42.json')
print(len(files))
for p in files:
    d = json.load(open(p, encoding='utf-8'))
    assert d['provider'] == 'ollama'
    assert d['model'] == 'qwen2.5-coder:32b'
    assert d['guard_source'] == 'qwen'
    for e in d['exchanges']:
        assert 'request' in e and 'raw_response' in e and 'stats' in e
PY

# 2. 冻结清单哈希（m5 部分）
python - <<'PY'
import json, hashlib, os
m = json.load(open('m6/freeze_manifest.json', encoding='utf-8'))
ok = bad = miss = 0
for f in m['files']:
    if not f['path'].startswith('m5/'):
        continue
    if not os.path.exists(f['path']):
        miss += 1
    elif hashlib.sha256(open(f['path'], 'rb').read()).hexdigest() == f['sha256']:
        ok += 1
    else:
        bad += 1
print(ok, bad, miss)   # 270 0 0
PY

# 3. 归档中是否有 M1–M4 run / GPU 日志
python - <<'PY'
import zipfile
for z in ['../mace_qwen_pilot_kit.zip', '../mace_qwen_pilot_kit_latest.zip']:
    with zipfile.ZipFile(z) as f:
        names = f.namelist()
    print(z, len(names),
          [n for n in names if 'nvidia' in n.lower() or 'ollama' in n.lower()][:5])
PY
```

本次审计**没有**执行：

- `ollama`、`ollama serve`、`ollama pull`、`ollama run`；
- 任何 `mace.cli run`（会调用模型）；
- 任何 GPU 负载或 AutoDL 连接；
- 任何对 `m6/`、`m5/`、评分器、fixture、历史报告的写入。

---

## 8. 最终裁定

| 问题 | 裁定 |
|---|---|
| M1–M4 的 Qwen 调用有原始证据吗？ | 没有；`UNVERIFIED_MODEL_ORIGIN` |
| M5 的 Qwen 调用有原始证据吗？ | 有存储转录和哈希；`VERIFIED_REPLAY_OF_MODEL_OUTPUT`，不是 `VERIFIED_LIVE_MODEL_RUN` |
| AutoDL/4090D 声明被独立证实了吗？ | 没有；M5 元数据只与 24 GB 级 GPU 自洽，不能证明主机身份 |
| 当前 Full MACE 的最终 Guard 谁写？ | 默认 Qwen；Composer 只在 derived/离线路径 |
| 算法有逻辑问题吗？ | 有；A1/A2 + B1–B6 + C1–C9，不能全部归因于 Qwen |
| 哪些问题直接导致 Exact 下降？ | Guard 覆盖、Composer 缺必要条件/无 witness 条件、模型语义错误、重复 observer soundness、停止条件 |
| 哪些数字不能进论文？ | M1–M4 全部；M5 只能以“存储转录”出现；M6 的 11/11/10/11/6/11 必须带“人工/离线/确定性”标签 |
| 是否存在“新算法胜过强基线”的证据？ | 没有；Direct 5/11 > MACE 3/11；Gate 0 gain/0 loss |

审计结束。
