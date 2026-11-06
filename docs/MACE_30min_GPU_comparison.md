# MACE 30 分钟 GPU 对比实验（含真实 Qwen 运行）

- 日期：2026-11-04
- 分支：`research/mace-subgraph-search`
- 前序状态：本文件早先记录过"GPU 不可达、C/D NOT_RUN"（commit `eb8069c`）。
  用户随后提供了可连接的 AutoDL 实例，C/D 已真实运行；本文件已按实际结果重写。
- 30 分钟窗口内实际完成的：4 次真实 Qwen 32B 调用、2 个任务的
  Graph-only 与 Full-MACE 同预算对比、2 个任务的 C-fixed 计分。
  未完成项在 §7 明列，不冒充完成。

## 1. 结论先行

| 方法 | 状态 | 任务 | 计分（credited） |
|---|---|---|---|
| C-fixed-1.1（穷举） | 本轮运行 2 个任务 + 复用 2 个历史冻结运行 | jinja2, werkzeug_bind, get_host, filestorage | **4 / 4 / 7 / 4** |
| B：Graph-only | 本轮同预算运行 | get_host, filestorage | **7 / 4** |
| C：Direct Qwen 32B | 本轮真实调用 | jinja2（成功）、werkzeug_bind（连接中断） | **0**（jinja2）；bind 无结果 |
| D：Full MACE（Qwen 排序 + 因果验证） | 本轮真实调用 | get_host, filestorage | **7 / 4** |

关键发现：

1. **D 确实真实调用了 Qwen 32B**（请求、原始响应、token 数、耗时均已落盘）。
2. **D 找到的 MSMS/MMBS 与同一 `U` 上的 Graph-only 完全相同**；经官方 scorer
   计分，全部为 `WITNESS_VERIFIED` / `FINITE_DOMAIN_EXACT`，0 条 FALSE/INVALID。
3. **Qwen 没有带来净收益，反而拖慢了首次确认**：两个任务的 10 个可搜索输入中，
   首次 MSMS 评估数 5 个变慢、1 个略快（6→5）、4 个持平；首次 MMBS 5 个变慢、
   5 个持平。Qwen 的语义假设与真实最小集不符（见 §4）。
4. D 与 C-fixed 在 4 个任务上的 credited 数完全一致（4/4/7/4），
   但 D 在 get_host 上只用了 194 probes（C 历史运行 396），在 filestorage 上
   68（C 80）。

**没有把纯 Graph 结果冒充为 Full MACE。D 的每个关系都经过真实 P+/P− 干预和
严格子集最小性检查；Qwen 只改变子集访问顺序，从不删除候选。**

## 2. 环境与 GPU 证据

- 实例：AutoDL `connect.cqa1.seetacloud.com:37377`（用户提供），
  `NVIDIA GeForce RTX 4090 D, 24564 MiB`，192 核。
- 模型：`qwen2.5-coder:32b`（Q4_K_M，19GB 权重，`ollama ps` 显示 25GB 运行时）。
- `runs/v3_full_mace_30min/gpu_evidence.json`（推理进行中采样）：
  - `nvidia-smi`: `22891 MiB / 24564 MiB`，GPU 利用率 0–5%（采样瞬间）。
  - `ollama ps`: `25 GB  8%/92% CPU/GPU  32768 context`。
  - **模型超出 24GB 显存，约 8% 跑在 CPU 上**；这解释了 52–139 秒的调用耗时。
- SSH 本地转发：`D:\tmp\al_forward.py`（凭据只经环境变量传入，不写入仓库）。
  首次转发进程因本地连接重置退出，已修复异常处理并重启；修复前
  `werkzeug_bind_server_name_lower` 的 Direct Qwen 调用因此失败（见 §7）。

## 3. 真实 Qwen 调用清单（全部落盘）

| # | 用途 | 任务 | prompt / completion tokens | wall | 结果 |
|---|---|---|---:|---:|---|
| 1 | 冒烟 | — | 40 / 6 | 21.2s | `{"ok": true}` |
| 2 | Baseline A | jinja2 | 6244 / 198 | 139.3s | 有效 JSON；scorer 记 1 FALSE + 2 UNVERIFIED |
| 3 | D 排序假设 | get_host | 388 / 151 | 56.0s | 5 个候选全部映射成功 |
| 4 | D 排序假设 | filestorage | 328 / 101 | 52.5s | 3 个候选全部映射成功 |

保存位置：

- `runs/qwen_smoke_response.json`
- `runs/v3_baseline_pilot_30min/tasks/jinja2_bytecode_cache_read/baseline_a/{request.json,raw_response.txt,run.json}`
- `runs/v3_full_mace_30min/tasks/<task>/result.json` 的 `qwen.request_messages` /
  `qwen.raw_response` / `qwen.stats`

## 4. D 的实现（最小适配层，未改核心算法）

`scripts/run_full_mace_comparison.py`：

1. 读取**冻结**的 Baseline-C universe（`runs/v3_baseline_pilot/.../baseline_c.json`），
   不在本轮重选 `U`；
2. 用 A 中心依赖子图给每个候选打分（只作为排序先验）；
3. 把 `U` 的 id、行号、代码交给 Qwen，要求返回
   `{"msms_rank": [...], "mmbs_rank": [...]}`；不在 `U` 中的 id 直接忽略；
4. 命中 id 加上 `2.0/(1+rank)` 的排序加成，**候选全集不变**；
5. 用 `baseline_c.run(search="graph", probe_budget=B)` 执行真实干预与冻结的
   三态最小性判据；Graph-only 臂用同样的预算、同样的代码，只去掉加成。

因此 "Full MACE" 与 "Graph-only" 的唯一差别就是 Qwen 给出的排序先验；
最终关系一律来自执行证据。

### Qwen 假设 vs 实际验证结果

- get_host（|U|=5）：Qwen 把 `85/87/90` 列为 MSMS、`93/95` 列为 MMBS；
  实际每个输入上的最小集是单元素 `{85}` 或 `{87}`（两臂一致）。
  `93/95` 的加成把错误候选排到了前面。
- filestorage（|U|=3）：Qwen 把 `2926` 列为 MSMS、`2921` 列为 MMBS；
  实际 MSMS 与 MMBS 都是 `{2924}`。**两个假设都与验证结果不符。**

## 5. 同预算对比结果

预算：每个 masked 输入最多 16 次子集评估（两臂相同；filestorage 的 2^3=8
小于预算，因此自然完整）。干预语义、验证器、`U`、最小性定义完全相同。

| 任务 | 臂 | 子集评估 | 完整? | probes | MSMS 数 | MMBS 数 | 首 MSMS（eval，逐输入） | 首 MMBS（eval） | credited |
|---|---|---:|---|---:|---:|---:|---|---|---:|
| get_host | Graph-only | 96 / 192 | 否 | 194 | 6 | 6 | 4,5,4,4,4,5 | 3,4,3,3,3,4 | **7** |
| get_host | Full MACE | 96 / 192 | 否 | 194 | 6 | 6 | 4,**10**,4,4,4,**10** | 3,**7**,3,3,3,**7** | **7** |
| filestorage | Graph-only | 32 / 32 | 是 | 68 | 8 | 4 | 4,6,4,4 | 3,—,3,3 | **4** |
| filestorage | Full MACE | 32 / 32 | 是 | 68 | 8 | 4 | **8**,5,**8**,**8** | **7**,—,**7**,**7** | **4** |

- 两臂确认的关系集合逐输入完全相同；D 没有多找到任何关系，也没有多报错误关系。
- 首次确认成本：Qwen 加成在 get_host 的 2/6 输入上把首 MSMS 从 5 拖到 10、
  首 MMBS 从 4 拖到 7；filestorage 的 4 个输入中首 MSMS 3 个从 4 拖到 8、
  1 个从 6 降到 5，首 MMBS 3 个从 3 拖到 7。
  合计首 MSMS 5 慢 1 快 4 平，首 MMBS 5 慢 5 平。
- get_host 预算 16 只是 2^5=32 的一半，两臂都**不完整**；表中关系均经过
  严格子集检查（`first_msms`/`first_mmbs` 只在全部必要比较完成后才非空），
  但不能声称穷尽该 `U`。

### 与 C-fixed 对比

| 任务 | C-fixed credited | D credited | C probes | D probes | 错误关系（FALSE/INVALID/UNVERIFIED） |
|---|---:|---:|---:|---:|---:|
| jinja2 | 4（本轮） | 未运行 D | 24 | — | 0 |
| werkzeug_bind | 4（本轮） | 未运行 D | 76 | — | 0 |
| get_host | 7（历史冻结运行，同 `U`/同 scorer） | 7 | 396 | **194** | 0 / 0 |
| filestorage | 4（历史冻结运行） | 4 | 80 | **68** | 0 / 0 |

C 的 get_host/filestorage 数字来自 `runs/v3_baseline_pilot/`（同一冻结版本、
同一 universe、同一 scorer），不是本轮新跑；已在此注明来源。C-fixed 用穷举，
D 用受限预算的图搜索，所以 D 用更少 probes 得到同等 credited 是**搜索顺序**
的结果，不是 Qwen 的贡献——同一预算下 Graph-only 也是 194/68。

### 与 Direct Qwen（方法 C）对比

- jinja2：Direct Qwen 输出 1 条 FALSE + 2 条 UNVERIFIED（候选都不在声明 `U` 内），
  credited **0**；同任务 C-fixed credited **4**。
- 这是本轮唯一一次完整的 Direct Qwen 计分；bind 的调用因 SSH 转发崩溃失败。
- 因此"模型直接给答案"在本轮是 0 分，"图搜索 + 执行验证"是 4–7 分。

## 6. 直接回答六个问题

1. **Full MACE 是否已经真实调用 Qwen？**
   **是。** 4 次真实调用（含冒烟），模型 `qwen2.5-coder:32b`，请求/原始响应/
   token/耗时/服务端 GPU 状态均已保存。§3 列出每次调用的 token 与耗时。
2. **能否正确发现 MSMS/MMBS？**
   **能复现存证关系，但没有新增。** 两个任务上与 Graph-only 的 confirmed 集合
   逐输入相同，官方 scorer 给出 7/4 credited、0 FALSE/INVALID/UNVERIFIED。
   get_host 的预算只覆盖 96/192 个子集，因此**不能**声称穷尽。
3. **与 C-fixed 相比，正确/错误关系数量和首次确认成本？**
   4 个任务上 credited 完全相同：jinja2 4、bind 4、get_host 7、filestorage 4；
   错误关系均为 0。D 的 probes 更少（194 vs 396；68 vs 80），但同预算的
   Graph-only 也是这个数，所以成本优势来自图排序/预算，不是 Qwen。
4. **与 Graph-only 相比 Qwen 有没有额外收益？**
   **没有，且总体有害。** 关系集合与计分完全相同；首 MSMS 5 个输入变慢、
   1 个略快、4 个持平，首 MMBS 5 个变慢、5 个持平。Qwen 的假设
   （filestorage 的 2926/2921、get_host 的 93/95）与真实最小集不符，
   加成把正确候选往后推。
5. **当前算法主要失败原因？**
   - 语义排序信号太弱：`U` 只有 1–5 个局部语句，模型给出的假设与可执行证据
     不一致；加成直接放大了错误先验。
   - 模型本身不经济：25GB 运行时放不进 24GB 显存，8% CPU offload 导致每次
     52–139s、prompt eval 占大头（jinja2 77s/6244 tokens）。
   - 任务规模太小：|U|≤5 时穷举本身只要几十到几百 probes，Qwen 的固定成本
     无法摊销。
   - 这不否定 MACE 的因果验证部分：D 的所有关系都是真实干预 + 严格子集验证，
     失败在"用模型猜顺序"，不在证据链。
6. **哪些结论仅限开发题？**
   全部 5 个 v3 任务都是 **DEV-TUNED**；以上数字只能作开发集结果，不能当
   held-out 泛化。D 的两个任务（get_host、filestorage）同样是开发题。
   独立测试缺口仍在 M1：336/515 目标已探针，0 个 CONFIRMED M1；
   Qwen 排序需要新的独立任务与更大的 `U` 才能有意义地评估。

## 7. 本轮实际运行、预算与未完成项

- 成功运行：
  - Baseline C（本轮）：jinja2（24 probes，4 credited）、bind（76 probes，4 credited）
  - Baseline A Direct Qwen：jinja2（1 次调用，0 credited）
  - Graph-only / Full MACE 同预算对比：get_host、filestorage（各 194 / 68 probes）
  - Qwen 冒烟 1 次
- 未完成 / 失败：
  - Direct Qwen（bind）：`RemoteDisconnected`，SSH 转发进程崩溃所致；**无模型输出，
    不计分**，未重跑（时间预算用尽）。
  - Direct Qwen 其余 3 个任务：NOT_RUN。
  - D 的其余 3 个任务：NOT_RUN（|U| 为 1–2 的 jinja2/bind 上 Qwen 排序无意义）。
  - get_host 两臂均只覆盖 96/192 子集（预算 16/输入），不是完整枚举。
- 未修改：HIDDEN scorer、冻结候选排序、Graph 权重、执行器、最小性判据。
- 新增代码：`scripts/run_full_mace_comparison.py`（仅排序适配层）。
- 快速回归（本轮重跑，同一命令）：
  `python -m pytest tests/test_v3_baselines.py tests/test_subgraph_search.py
  tests/test_budget_experiment.py tests/test_verify.py tests/test_verifier_v2.py
  tests/test_evidence_gate.py` → 95 个用例全部通过、退出码 0
  （日志 `runs/m1_targeted_regression_gpu.txt`；该仓库 pytest 配置抑制了汇总行，
  只输出点阵）。

## 8. 后续接线审查

对 D 的离线审查（无 GPU）见 **docs/MACE_full_mace_wiring_audit.md**：
Qwen 的 7 个 id 全部映射；它没有被图分压制，而是被 `edge` 分层和
"一张分数表同时服务 MSMS/MMBS 两侧"的接线结构限制；用已验证最小集构造的
理想先验也没有带来净收益（首 MSMS 4.40→4.40，首 MMBS 3.22→3.44）。

角色分离 + 假设门控的 v2 实现、回归测试与 A/B/C/C0/D 离线对照见
**docs/MACE_role_separated_search_v2_results.md**。

## 9. 产物与复现

- `runs/v3_baseline_pilot_30min/`：C/A 运行、raw response、计分
- `runs/v3_full_mace_30min/tasks/<task>/result.json`：U、Qwen 请求/响应、
  两臂逐输入结果与 search metrics
- `runs/v3_full_mace_30min/tasks/<task>/{graph_only,full_mace}_{submission,score}.json`
- `runs/v3_full_mace_30min/gpu_evidence.json`
- `runs/full_mace_30min.log`、`runs/full_mace_30min_filestorage.log`、
  `runs/pilot_30min.log`
- 复现：`python -m scripts.run_full_mace_comparison --tasks <task> --budget 16`
  （需要 127.0.0.1:11434 上的 `qwen2.5-coder:32b`；无服务时不会伪造结果）。
