# MACE 四题真实 Qwen 语义发现验证

- 日期：2026-11-04
- 分支：`research/mace-role-separated-search`
- 冻结基线：commit `d4f8047`（Role-separated Search + Semantic Relation Discovery；本报告不改变算法）
- 本轮新增：真实云端 Qwen 32B 的四题各一次调用、离线重放、关系级因果核验、与 Graph-only 的对比
- 结论先行：**新的语义关系协议值得保留为“排序先验 / 假设生成”模块，但不值得保留为 Full MACE 的核心发现模块。** 四题上它发现的新操作数为 0，新增正确关系数为 0（2 条 pilot 关系通过核验，但其操作集合 Graph-only 已经确认）；它真实带来的收益只是首确认顺序，而且收益是混合的。

---

## 0. 证据边界

本报告的所有数字都来自以下四题、每题恰好一次完成的模型调用（另有 1 次被中止的 32768 上下文生成和 1 次端点冒烟，均不计入）：

| 题目 | 类型 | 是否有隐藏真值 | 条件能否核验 |
|---|---|---|---|
| `ctrl_02` | pilot 合成题 | 有（24 个冻结输入） | 能（pilot `Verifier`） |
| `ctrl_03` | pilot 合成题 | 有（20 个冻结输入） | 能（pilot `Verifier`） |
| `werkzeug_get_host_default_empty` | 真实 v3 题 | 无（本轮不读 HIDDEN） | 不能（冻结 v3 路径无条件核验器） |
| `werkzeug_filestorage_stream_name` | 真实 v3 题 | 无（本轮不读 HIDDEN） | 不能（同上） |

必须同时读到的四条限制：

1. **n=4，每题一次调用**。下表是确定性执行结果，不是统计显著性的证据；不能外推为“Qwen 在 MACE 上的平均表现”。
2. **真实题只有集合级核验**。v3 执行器能确认每个输入上的 MSMS/MMBS 集合，但没有把模型条件编译成受限谓词并逐例评分的路径；真实题的条件一律记为 `NOT_EVALUATED`，不能写成“已验证”。
3. **`get_host` 的搜索不完整**。U=5，预算 16，每个输入只枚举了 32 个子集中的 16 个，`complete=false`；因此“某集合未出现”只等于“未确认”，不等于“已否证”。
4. **`ctrl_03` 的 cooperative 关系在调用时和重放时给出不同失败理由，但结论都是 FALSE**。调用时的首见证是 `case_0000`（c=1,d=1，集合根本不生效），重放遍历全部见证后找到 `case_0012`，真正的失败原因是条件不充分。下表采用重放结果；原始调用记录保留在 `live/ctrl_03.json`，未覆盖。

---

## 1. 冻结版本与改动边界

保留不动：

- Graph-only 臂 `A_graph`；
- Role-separated C0（`C_fixture`，Graph 自产关系）；
- 旧 Qwen 排序臂 `B_old_qwen`（历史消融，不与新协议混算）；
- 新语义关系臂 `C_semantic`；
- HIDDEN scorer、冻结 Benchmark、既有 `runs/v3_semantic_relations/results.json` 均未改动。

本轮只改了 `scripts/run_semantic_relation_discovery.py` 的三处运行/核验细节：

1. 新增 `--num-ctx`、`--num-predict`（默认 8192 / 4096），用于把 32B 模型压进 24GB 显存；
2. `_call_live` 固定 `retries=0`，保证“每题一次调用”不会被静默重试变成第二次生成；
3. pilot 关系核验不再只用第一个 `base_equal and local_effect` 见证，而是遍历候选见证并按状态质量取最优；这只影响 FALSE 记录的理由与条件证据，不影响任何 VERIFIED 判定。

`runs/v3_semantic_relations/results.json`（CPU 阶段，commit `d4f8047`）保持原样；本轮真实调用结果写入新的 `results_live.json`。

---

## 2. 真实 Qwen 32B 服务证据

连接信息与机器证据见 `runs/v3_semantic_relations/gpu_evidence.json`。密码只通过环境变量传入，未写入仓库。

| 项 | 值 |
|---|---|
| 主机 | `connect.cqa1.seetacloud.com:37377` |
| GPU | NVIDIA GeForce RTX 4090 D，24564 MiB |
| 运行中显存 | 21205 MiB |
| Ollama | 0.40.13，模型目录 `/root/autodl-tmp/ollama_models` |
| 模型 | `qwen2.5-coder:32b`，digest `b92d6a0b…bef41` |
| 运行时 | 21 GB，`100% GPU`，context 8192，20.0 tok/s |

**一次被中止、未使用的尝试（必须披露）**：第一批误用 `num_ctx=32768`，运行时 25 GB，超过 24 GB 显存，变成 `8%/92% CPU/GPU`、3.32 tok/s；在返回任何响应前停止，模型随后被卸载，未产生、未复用任何题目结果。`gpu_evidence.json` 中记为 `results_used: false`。

**冒烟调用**：43 prompt tokens / 6 completion tokens / 10.176 s，只验证端点和模型可用，不计入四题结果。

**四题调用**（`temperature=0`，`seed=42`，`retries=0`，`num_ctx=8192`，`num_predict=4096`）：

| 题目 | prompt tok | completion tok | total tok | wall (s) |
|---|---:|---:|---:|---:|
| `ctrl_02` | 1,265 | 665 | 1,930 | 43.368 |
| `ctrl_03` | 1,607 | 1,610 | 3,217 | 82.573 |
| `werkzeug_get_host_default_empty` | 1,753 | 2,744 | 4,497 | 139.059 |
| `werkzeug_filestorage_stream_name` | 1,376 | 1,203 | 2,579 | 62.425 |
| **合计** | **6,001** | **6,222** | **12,223** | **327.425** |

每题 `done_reason=stop`，无重试、无截断。精确请求体（system+user messages、options、`prompt_sha256`）在 `live_requests/<task>.json`；原始响应在 `live_raw/<task>.json`。

**隐藏答案泄漏检查**：四个 prompt 对 `MSMS`、`MMBS`、`witness`、`truth`、`attribution`、`absorber`、`coexisting_unmasking`、`case_00`、`hidden` 的出现次数均为 0。模型只看到公开程序、目标行、合法输入域、冻结输入列表、Graph 已提出的操作，以及“可以提出列表外操作”的说明。

---

## 3. 映射结果：全部落入 Graph，U_qwen 为空

| 题目 | U_graph | U_qwen | 提出关系数 | 映射条目数 | 唯一操作数 | 拒绝/不可执行 |
|---|---:|---:|---:|---:|---:|---:|
| `ctrl_02` | 2 | 0 | 4 | 6 | 2 | 0 |
| `ctrl_03` | 4 | 0 | 10 | 18 | 4 | 0 |
| `get_host` | 5 | 0 | 12 | 23 | 5 | 0 |
| `filestorage` | 3 | 0 | 7 | 9 | 3 | 0 |
| **合计** | — | **0** | **33** | **56** | **14** | **0** |

映射条目数大于关系数，是因为同一操作在多条关系中重复出现（例如 `ctrl_02` 的 C、D 各出现 3 次）。P/R 统计对操作名去重，不按条目重复计数。

三点必须分清：

- **0 拒绝** 不等于 **0 新操作**。模型提出的每一个 `{file,line,text}` 都映射到了真实 AST 语句，但映射目标全部已在 `U_graph` 中；`U_qwen` 因此是空集。
- 这说明映射器没有把模型输出“吞掉”，也说明模型在这四题上没有提出 Graph 之外的可执行操作。**语义发现机制在这四题上的“发现新操作”能力没有被证明，也没有被否证**——因为这些题的 U_graph 已经覆盖了可执行语句，模型没有理由越出它。
- 真实题没有隐藏真值参与映射；`candidate_metrics` 在 `results_live.json` 中为 `null`，不是 0。不能把“未计算”写成“精确率 0”。

---

## 4. 关系级因果核验

### 4.1 pilot 题：使用冻结 `Verifier`，`VERIFIED` 才算正确

判定口径：集合级检查（`only_set_masks`、`disabling_set_exposes`、真子集最小性）全部通过，且条件在冻结输入域上 `exact`（或至少 `sound` 且 `complete`），才记 `VERIFIED`。模型提出的关系初始状态一律是 `HYPOTHESIS`。

#### `ctrl_02`（真值：C、D 协同；真条件 `c==0 and d==0 and x<6`）

| # | kind | ops | 集合级 | 条件 | 结论 |
|---|---|---|---|---|---|
| 0 | independent | C | `only_set_masks=false` | 未评分 | FALSE |
| 1 | independent | D | `only_set_masks=false` | 未评分 | FALSE |
| 2 | cooperative | C,D | 最小性通过 | `c==0 and d==0`；`false_accept=case_0020`（x=6） | FALSE（条件 unsound） |
| 3 | fallback | C,D | 最小性通过 | `c==0 or d==0`；13 个 false accept | FALSE（条件 unsound） |

**0/4 VERIFIED。** 模型正确找到了协同集合 {C,D}，也正确判断了“单独 C 或单独 D 不够”，但没有给出 `x<6` 这个量级条件；它把 `x=6` 也纳入关系，因此关系作为整体是假的。

#### `ctrl_03`（真值：B、E 独立；C、D 协同，真条件在声明域上为 `c==0 and x<5`，`d==0` 由合法域蕴含）

| # | kind | ops | 集合级 | 条件 | 结论 |
|---|---|---|---|---|---|
| 0 | independent | B | 通过 | `p==0`，exact / sound / complete | **VERIFIED**（case_0000） |
| 1 | independent | E | 通过 | `q==0`，exact / sound / complete | **VERIFIED**（case_0004） |
| 2 | cooperative | B,E | 真子集 B 已经单独掩蔽 | 未评分 | FALSE |
| 3 | fallback | B,E | 同上 | 未评分 | FALSE |
| 4 | independent | D | `only_set_masks=false` | 未评分 | FALSE |
| 5 | independent | C | `only_set_masks=false` | 未评分 | FALSE |
| 6 | cooperative | C,D | 最小性通过（case_0012） | `d==0 and c==0`；`false_accept=case_0014, case_0015`（x=5,6） | FALSE（条件 unsound） |
| 7 | fallback | C,D | 同上 | 同上 | FALSE（条件 unsound） |
| 8 | coexisting | C,B,D | 真子集 C,D 已经暴露 A | 未评分 | FALSE |
| 9 | coexisting | C,E,D | 真子集 C,D 已经暴露 A | 未评分 | FALSE |

**2/10 VERIFIED。** 两条通过的都是简单独立关系，条件是输入域的精确重述；两条协同关系集合正确，但都漏掉 `x<5`，所以作为关系是假的；4 个 fallback/coexisting 全部在最小性上失败。

#### pilot 汇总

| 口径 | 数值 |
|---|---:|
| 提出关系总数 | 14 |
| 集合级 + 条件 exact 的 VERIFIED | **2**（B、E） |
| 协同集合提出正确 | 2/2（{C,D} × 2 题） |
| 协同关系 VERIFIED | **0/2** |
| 条件被实际评分的关系 | 6（2 exact + 4 unsound） |
| 其余关系未评分的原因 | 集合级先失败（单独不掩蔽 / 真子集已掩蔽） |

### 4.2 真实题：只做集合级核验，条件记为 `NOT_EVALUATED`

真实题没有 pilot `Verifier` 所需的冻结真值，冻结 v3 路径也没有条件核验器。因此本轮只做一件事：把模型声明的操作集合，与 Graph-only 臂在每个输入上**由因果执行器确认的 MSMS/MMBS 集合**做比对。确认集合来自执行器，不来自模型，因此这不是“把假设当正确”。

| 题目 | 关系数 | 集合在至少一个输入上被确认 | 从未被确认 | 枚举完整性 |
|---|---:|---:|---:|---|
| `get_host` | 12 | 2（line 85 在 4/6 输入；line 87 在 2/6 输入） | 10 | 6/6 输入 `complete=false`（16/32 子集） |
| `filestorage` | 7 | 5（对应 3 个唯一操作：line 2924 在 4/4 输入；line 2921、2926 仅在 `stream=none`；两条 fallback 与对应 independent 重复） | 2（两条 cooperative） | 4/4 输入 `complete=true`（8/8 子集） |

解释：

- **`get_host`**：模型提出的 10 条 cooperative/fallback/coexisting 关系，其集合没有在任何输入上被确认；但所有输入都只枚举了一半子集，所以只能写“未确认”。已确认的只有两条单操作关系（line 85 / line 87），与 Graph-only 的结果完全一致。模型条件使用 `is not None`、`endswith`、集合字面量，超出 pilot 条件语法，未评分。
- **`filestorage`**：两条 cooperative（2921+2924、2924+2926）在完整枚举下 0/4 输入被确认，属于**集合级 false**；两条 fallback 实际是单操作，与 independent 重复；line 2924 的单操作关系在四个输入上都被确认，但条件（`filename[0]=='<'` 等）未评分。已确认集合仍与 Graph-only 完全一致。
- 真实题上**没有任何一条关系达到“集合 + 条件都正确”**；因此真实项目的新增正确关系数为 0。

### 4.3 一个必须记住的口径

- `VERIFIED` = 操作集合是**最小**掩蔽集合（或最小暴露集合），并且条件在冻结域上精确/可靠。
- `FALSE` = 上述任一检查失败；失败理由可能是集合不对、最小性不对，或条件不充分。
- `HYPOTHESIS` = 模型说了，但还没有被因果执行器接受。**绝不能把 HYPOTHESIS 计入正确关系。**
- `NOT_EVALUATED` = 现有冻结路径没有能力评分；不是“通过”，也不是“失败”。

---

## 5. 与 Graph-only 的对比

### 5.1 搜索成本与首确认位置

三个臂的预算、证据存储和探针数完全相同；差别只在候选子集的**排序**。`probe_executions` 是真实程序执行次数，`evaluations` 是子集评估次数。

| 题目 | 臂 | firstMSMS 均值 | firstMMBS 均值 | probes | evaluations |
|---|---|---:|---:|---:|---:|
| `ctrl_02` | A_graph | 3.000 | 2.000 | 240 | 20 |
| | B_old_qwen | 3.000 | 2.000 | 240 | 20 |
| | **C_semantic** | **3.000** | **2.000** | 240 | 20 |
| `ctrl_03` | A_graph | 6.000 | 7.857 | 680 | 224 |
| | B_old_qwen | 7.714 | 9.000 | 680 | 224 |
| | **C_semantic** | **3.714** | **5.571** | 680 | 224 |
| `get_host` | A_graph | 4.333 | 3.333 | 194 | 96 |
| | B_old_qwen | 6.000 | 4.333 | 194 | 96 |
| | **C_semantic** | **2.667** | **3.667** | 194 | 96 |
| `filestorage` | A_graph | 4.500 | 3.000 | 68 | 32 |
| | B_old_qwen | 7.250 | 7.000 | 68 | 32 |
| | **C_semantic** | **2.000** | **3.000** | 68 | 32 |

相对 Graph-only 的变化：

| 题目 | Δ 首 MSMS | Δ 首 MMBS |
|---|---:|---:|
| `ctrl_02` | 0.0% | 0.0% |
| `ctrl_03` | **−38.1%** | **−29.1%** |
| `get_host` | **−38.5%** | **+10.0%**（变差） |
| `filestorage` | **−55.6%** | 0.0% |

**四个题的确认集合在所有臂之间逐输入完全相同**（`msms_ids` / `mmbs_ids` 无一差异，包含 `C_fixture`）。一个值得注意的控制结果：`C_fixture`（Graph 自己产的关系）在 `ctrl_02` 反而比 A 慢（4.0/3.0 vs 3.0/2.0），在 `ctrl_03` 与 C 的 MSMS 完全相同、MMBS 略好（5.286 vs 5.571）。这说明**即使是正确来源的关系，在小 U 上也可能误导排序**；排序前验的收益依赖 U 的大小和关系与搜索空间的匹配，不是单调的。因此：

- 语义臂没有增加或减少任何一个被确认的 MSMS/MMBS；
- 收益全部来自排序，不是来自额外执行；
- probes 完全相同（240/680/194/68），没有节省预算；
- 旧 Qwen 排序臂 B 在 `ctrl_02` 与 A 持平，其余三题全部比 A 慢；新协议 C 在三个题上明显优于 B，在 `get_host` 的 MMBS 上也优于 B（3.667 < 4.333）。所以“新协议比旧 Qwen 排序好”成立，“新协议比 Graph 更会发现”不成立。

### 5.2 均值掩盖的逐输入回退

不能只看均值。逐输入首确认索引（只列被搜索的输入）：

- `ctrl_03` MSMS：A `[4,4,4,4,6,6,6,6,4,4,4,4,14,14]` → C `[2,2,2,2,4,4,4,4,2,2,2,2,10,10]`，14/14 输入全部持平或更好。
- `ctrl_03` MMBS：A `[5,5,5,5,7,7,7,7,14,14,14,14,3,3]` → C `[3,3,3,3,5,5,5,5,7,7,7,7,9,9]`。前 12 个输入改善，但 `case_0012`、`case_0013` 从 **3 退化到 9**（2/14 输入显著变差）。这两个输入正是 C、D 协同生效的输入；模型给出的协同条件不充分，反而把错误候选排到了前面。
- `get_host` MSMS：A `[4,5,4,4,4,5]` → C `[2,4,2,2,2,4]`，6/6 改善。
- `get_host` MMBS：A `[3,4,3,3,3,4]` → C `[3,5,3,3,3,5]`，2/6 输入从 4 退化到 5。
- `filestorage` MSMS：A `[4,6,4,4]` → C `[2,2,2,2]`，4/4 改善；MMBS 完全持平。
- `ctrl_02`：所有输入持平。

结论：**排序收益是真的，但不是稳定的**；在协同关系上，错误条件会把排序带偏。均值改善不能掩盖 2/14 与 2/6 的回退。

---

## 6. 为什么 P/R 可以是 1.0/1.0，而关系核验是 FALSE

这是上一轮和本轮都容易被误读的地方。P/R 的定义是**候选操作级匹配**：

- `truth_ops`：该题真值中的操作名集合；
- `mapped_ops`：模型提出的、成功映射到 AST 的条目（同一操作出现多次就记多次）；
- `precision = |unique(mapped) ∩ truth| / |unique(mapped)|`；
- `recall = |unique(mapped) ∩ truth| / |truth|`；
- 它**不看** kind、不看集合是否最小、不看真子集、不看条件，也不看关系是否成立。

因此：

| 题目 | 映射条目 | 唯一操作 | P | R | 关系 VERIFIED |
|---|---:|---|---:|---:|---:|
| `ctrl_02` | 6 | C,D | 1.0 | 1.0 | **0/4** |
| `ctrl_03` | 18 | B,C,D,E | 1.0 | 1.0 | **2/10** |
| 旧协议 `ctrl_03` | 2 | C,D | 1.0 | **0.5** | **0/2** |

- `ctrl_02` 的 P/R=1.0/1.0 只说明“模型点名的操作都是真值里的操作”。它把 C、D 各点了 3 次，唯一操作集合刚好是 {C,D}，所以操作级满分；但它把 C、D 说成各自独立（错），协同条件又漏了 `x<6`（错），于是 0/4 关系为真。
- `ctrl_03` 的 P/R=1.0/1.0 同理：B、C、D、E 都被点到，操作级满分；但 8/10 关系在集合或最小性上失败，只有 B、E 两条独立关系通过。
- 旧协议反过来：只点了 C、D，召回 0.5，但精确率仍 1.0，且 0/2 关系为真。**低召回不等于关系错，高 P/R 也不等于关系对。**

一句话：**P/R 回答“模型有没有指对操作”，关系核验回答“模型有没有说出一条真的、最小的、条件正确的掩蔽关系”。两者正交，不能互相替代，更不能把 P/R 当关系正确率汇报。**

---

## 7. 五个问题的直接回答

**Q1：Qwen 是否发现了 Graph 遗漏的操作？**

没有。四题 `U_qwen=0`，0 条拒绝、0 条不可执行；56 个映射条目、14 个唯一操作全部在 `U_graph` 内。不是映射失败，而是模型没有提出列表外的可执行语句。由于这四题的 `U_graph` 已覆盖可执行语句，这个结果不能证明“模型永远不会发现新操作”，只能证明**在这四题上它没有发现**。

**Q2：Qwen 是否正确找到 `ctrl_02` / `ctrl_03` 的协同关系？**

集合级正确，关系级不正确。两题的 {C,D} 都被提出，且都通过“单独 C / 单独 D 不够”的最小性检查；但两题的条件都不充分：`ctrl_02` 漏 `x<6`（false accept `case_0020`），`ctrl_03` 漏 `x<5`（false accept `case_0014`、`case_0015`）。因此**协同关系 VERIFIED = 0/2**。模型还额外提出了错误的 B+E 协同、以及 4 条错误的 fallback/coexisting，说明它会把“顺序执行”“条件分支”误判为协同。

**Q3：是否在真实项目里发现新的正确关系？**

没有。`get_host` 的 12 条关系里只有 2 条单操作集合在部分输入上被确认，10 条 cooperative/fallback/coexisting 未被确认（且搜索不完整，不能据此判假）；`filestorage` 的 7 条里 5 条（对应 3 个唯一操作，含两条与 independent 重复的 fallback）被确认，2 条 cooperative 在完整枚举下集合级为假。两题的条件都因冻结 v3 路径没有条件核验器而记为 `NOT_EVALUATED`。**集合 + 条件都正确的新关系 = 0。**

**Q4：Qwen 的条件假设是否被验证？**

- pilot：6 条关系进入条件评分，2 条 exact（`p==0`、`q==0`），4 条 unsound（两条 `ctrl_02`、两条 `ctrl_03` 的 C,D 协同/fallback）；其余 8 条在集合级先失败，没有进入条件评分。
- 真实题：0 条被验证。不是“条件错”，而是现有冻结路径没有能力对 `is not None`、`.endswith`、集合字面量这些形式做有界条件核验；一律 `NOT_EVALUATED`。
- 还有一个 gate 语义要记住：搜索门控检查的是**当前输入上的见证**，不是全局条件。因此一个过宽的条件仍然可能帮排序（`ctrl_03` 的 MSMS 就是这样），但这**不是**条件被验证，绝不能写成“条件正确”。

**Q5：每条新关系的探测与 token 成本？**

- 新操作：0；新正确关系：0。因此“每条新关系的边际成本”在这个样本上**没有定义**（分母为 0）。
- 总成本：4 次完成调用，12,223 tokens（6,001 prompt + 6,222 completion），327.425 s。
- 额外探针：**0**。三个臂的 probes 完全相同（240/680/194/68），语义臂只改排序，不增加执行。
- 若按“通过核验的关系”摊销：12,223 tokens / 2 = 6,111.5 tokens/条，327.425 s / 2 = 163.7 s/条；但这 2 条都是简单独立关系，且操作集合 Graph-only 已经确认，**不能把这个摊销值当成“发现新关系的成本”**。

---

## 8. 判断：是否保留为 Full MACE 的核心模块

**判断：保留，但只作为可选的排序先验 / 假设生成模块；不作为 Full MACE 的核心发现模块。**

支持保留的证据：

1. 新协议在 3/4 题上明显改善首确认位置：`ctrl_03` MSMS −38.1%、MMBS −29.1%；`get_host` MSMS −38.5%；`filestorage` MSMS −55.6%。
2. 它稳定优于旧 Qwen 排序臂 B（B 在三题上比 Graph 更慢），说明结构化协议本身是有效的改进。
3. 成本可控：每题一次调用，总 12,223 tokens，且不增加任何探针；在“已经要调用一次模型”的前提下，这是便宜的排序信号。
4. 映射与安全边界干净：0 拒绝、0 新操作、0 隐藏答案泄漏；模型输出没有污染 `U_graph`。

反对把它升为核心的证据：

1. **发现能力为 0**：四题 0 个新操作、0 条新增正确关系；它没有证明自己能补 Graph 的漏。
2. **关系质量不足**：pilot 14 条只有 2 条 VERIFIED；协同集合正确但条件 0/2 通过；真实题 0 条达到“集合 + 条件都正确”。
3. **收益是混合的**：`ctrl_02` 完全持平；`get_host` 的 MMBS 变差 10%；`ctrl_03` 有 2/14 输入 MMBS 从 3 退化到 9，`get_host` 有 2/6 输入 MMBS 从 4 退化到 5。把错误条件排在前面会伤害搜索。
4. **没有预算节省**：probes 与 Graph-only 完全相同；收益只是“更早看到”，不是“更少执行”。在预算受限的真实任务上，这个收益不一定兑现。
5. **条件归纳仍是瓶颈**：这与 M5/M6 的结论一致——组合不是瓶颈，条件才是。新的语义协议改善了“提出什么集合”，但没有解决“条件是否充分”。

因此建议的定位是：

- 默认 Full MACE 核心 = Graph 枚举 + 因果执行器 + 严格最小性 + 反例驱动；语义关系**默认不参与正确性判定**。
- 语义关系只作为 `--hypotheses` 的可选排序臂；所有模型关系保持 `HYPOTHESIS`，只有执行器确认后才能升级。
- 若未来要把它升为核心，先满足至少一个预注册条件：
  (a) 在一个 `U_graph` 可证明不完整的任务上，模型提出 `U_qwen` 非空且被执行器确认的新操作；
  (b) 协同关系的条件达到 exact/sound，而不是只对当前见证成立；
  (c) 在更大的 U 上，排序收益转化为真实的探针/时间节省，而不只是首确认索引变小。
  这三条在本轮四题上都没有满足。

对上一轮 M10 结论的修正：上一轮说“证据不足以把语义发现升为核心机制”，这一判断仍然成立；但本轮补充了一个正面事实——**新协议确实能改善排序，且明显优于旧 Qwen 排序**。所以正确的结论不是“完全不用”，而是“保留为排序器，别当发现器”。

---

## 9. 限制与复现

限制：

- 四题、每题一次调用；没有重复采样，没有置信区间；排序差异是确定性的，但不能外推到其他题。
- `get_host` 搜索不完整（每个输入 16/32 子集），其“未确认”不能读成“已否证”。
- 真实题没有条件核验器；`NOT_EVALUATED` 不是通过。
- 一次 32768 上下文生成被中止且未使用；一次冒烟调用不计入结果。
- pilot 的调用时核验与离线重放可能给出不同的 FALSE 理由；本报告以重放为准，原始记录保留。
- 模型输出只在本轮的四题上检查了泄漏；不能据此声称对所有 prompt 都无泄漏。

复现路径：

1. 在 AutoDL 上启动 Ollama，设置 `OLLAMA_MODELS=/root/autodl-tmp/ollama_models`，确认 `qwen2.5-coder:32b` 以 8192 上下文、100% GPU 加载。
2. 本地 SSH 转发 `127.0.0.1:11434` 到云端（密码只从环境变量读取）。
3. 对每题单独运行一次：

```bash
python scripts/run_semantic_relation_discovery.py \
  --tasks ctrl_02 \
  --live --endpoint http://127.0.0.1:11434 \
  --model qwen2.5-coder:32b --num-ctx 8192 --num-predict 4096
```

`ctrl_03`、`werkzeug_get_host_default_empty`、`werkzeug_filestorage_stream_name` 各换 `--tasks` 单独运行；不要在一次进程里并发多题，以免显存和超时互相干扰。

4. 离线重放与汇总（不调用模型）：

```bash
python scripts/run_semantic_relation_discovery.py \
  --tasks ctrl_02 ctrl_03 \
  --hypotheses runs/v3_semantic_relations/live_raw/<task>.json
```

5. 全量测试：`pytest -q`（本轮 exit 0，373 项；日志 `runs/v3_semantic_relations/live_tests.log`）。

---

## 10. 产物清单

| 路径 | 内容 |
|---|---|
| `docs/MACE_four_task_semantic_validation.md` | 本报告 |
| `runs/v3_semantic_relations/results_live.json` | 四题合并结果（模型输出、映射、角色假设、三臂搜索、pilot 核验、统计） |
| `runs/v3_semantic_relations/live/<task>.json` | 每题的调用时结果（原始核验记录） |
| `runs/v3_semantic_relations/live_raw/<task>.json` | 抽取出的原始响应，供离线重放 |
| `runs/v3_semantic_relations/live_requests/<task>.json` | 精确 system/user messages、options、`prompt_sha256` |
| `runs/v3_semantic_relations/gpu_evidence.json` | SSH/GPU/Ollama 证据、被中止的 32768 尝试、冒烟、四题 tokens/wall |
| `runs/v3_semantic_relations/live_code_hashes.json` | 本轮代码与产物的 sha256 |
| `runs/v3_semantic_relations/live_replay.log` | 离线重放日志（三臂首确认数组） |
| `runs/v3_semantic_relations/live_run.log` | 被中止批次日志（无结果） |
| `runs/v3_semantic_relations/live_tests.log` | 全量测试日志 |
| `scripts/run_semantic_relation_discovery.py` | 本轮修改的 runner（num_ctx/num_predict、retries=0、见证遍历） |
| `docs/MACE_semantic_relation_discovery_results.md` | 上一轮（commit `d4f8047`）的 CPU 阶段报告，未被覆盖 |

---

## 11. 一句话总结

**新语义关系协议是一个有用的“排序先验”，不是“发现引擎”：它在四题上没有带来任何新操作或新增正确关系，只把部分题目的首确认位置提前了 29%–56%，同时伴随少量回退；协同关系的条件仍不充分，真实题的条件无法核验。因此保留为可选排序模块，Full MACE 的核心继续是 Graph + 因果执行器 + 严格最小性。**

---

## 12. 追加：Direct Qwen 端到端基线（四题各再 1 次调用）

### 12.1 目的与预算

本节回答“让 Qwen 直接端到端答题会怎样”。它是上一节四题之外的**新基线**，不是对原
C 臂的替换：仍然只用 `ctrl_02`、`ctrl_03`、`get_host`、`filestorage` 四题，不新增题目，
不读 HIDDEN，不改 scorer，不跑 515 个旧目标/SQLAlchemy coverage。原指令限定“每题只调用
一次模型”；用户随后明确要求看纯 Qwen 端到端结果，因此本节**每题恰好多调用 1 次**，共
4 次，`retries=0`，没有重试、没有并发、没有中止批次。原有四题结果和产物均未覆盖。

提示词是中性直答版：同一份公开信息（程序、目标 A、合法输入、observable），但

- 不给 Graph 候选操作列表；
- 不给 `independent/cooperative/fallback/coexisting` 关系分类；
- 不给执行反馈、不给搜索机会；
- 只要求输出最小操作集合、条件和一句理由。

模型输出先按真实 AST 语句映射；pilot 用冻结的 `Verifier.verify_relation` 在全部合法输入
上评分（单操作试 `independent`，多操作试 `cooperative`/`coexisting`）；真实 v3 题没有条件
核验器，只把操作集合与 A_graph 已经因果确认的 MSMS/MMBS 集合比对，条件记
`NOT_EVALUATED`。

### 12.2 调用证据

| 题 | prompt tok | completion tok | wall (s) | attempt |
|---|---:|---:|---:|---:|
| `ctrl_02` | 1,068 | 286 | 24.243 | 0 |
| `ctrl_03` | 1,356 | 665 | 36.276 | 0 |
| `get_host` | 1,421 | 1,320 | 69.485 | 0 |
| `filestorage` | 1,109 | 877 | 46.335 | 0 |
| **合计** | **4,954** | **3,148** | **176.339** |  |

同一 AutoDL RTX 4090 D、`qwen2.5-coder:32b`（digest `b92d6a0b…bef41`）、8192 上下文、
100% GPU、21 GB、llama.cpp。请求 prompt 的泄漏扫描（`MSMS/MMBS/witness/truth/
attribution/absorber/case_00/hidden`）为 0 命中。证据见
`runs/v3_semantic_relations/direct_end_to_end/gpu_evidence.json`。

### 12.3 评分修正（没有重新调用模型）

第一遍严格评分把 `ctrl_03` 的 5 条关系全部判成 “duplicate operation”：模型同时列了
`if p == 0:` 和它的函数体 `v = x`，而映射器把函数体折回同一个 `if` 操作。这不是模型的
第二次生成，而是评分器把“同一条操作被写了两遍”误当成拒绝理由。离线重评时改为**同一关系
内按操作 id 去重**，保留原始响应和第一遍结果，不覆盖：

- 第一遍：`direct_end_to_end/results.json`
- 去重重评：`direct_end_to_end/rescored/results.json`
- 内层归一化敏感性分析：`direct_end_to_end/normalized_inner/results.json`

### 12.4 结果

严格评分（literal AST mapping）：

| 题 | 原始/映射/拒绝 | 关系级结果 | 说明 |
|---|---|---|---|
| `ctrl_02` | 3 / 3 / 0 | 0 VERIFIED（3 FALSE） | 提出真实集合 `{C,D}`，但条件是 `c==0 and d==0`，漏 `x<6`；`case_0020` false_accept |
| `ctrl_03` | 5 / 5 / 0 | 2 VERIFIED（B、E），3 FALSE | B `p==0`、E `q==0` 条件 exact；`{C,D}` 集合正确但条件过强（false_reject `case_0012/0013`）；未提出 `{B,E}` |
| `get_host` | 8 / 8 / 0 | 0 集合确认；8 条 NEW_OP | 8 条关系都同时列了外层 `if` 和函数体，严格集合包含不在 U_graph 的控制语句 |
| `filestorage` | 6 / 4 / 2 | 2 集合确认（2921、2926）；2 条 NEW_OP | 两条 2923 的文本多了一个引号，`text_mismatch` 拒绝；另有 2 条把 `if filename is not None` 与 2921 一起列出 |

pilot 的真实集合覆盖：

| 题 | 真实集合 | 直接提出 | 关系级 VERIFIED |
|---|---|---|---|
| `ctrl_02` | masking `{C,D}`（1 个） | 1/1 | 0/1 |
| `ctrl_03` | masking `{B}`、`{E}`、`{C,D}`，exposing `{B,E}`（4 个） | 3/4（缺 `{B,E}`） | 2/4 |

两题都**没有 exact**：`ctrl_02` 的协同条件 unsound，`ctrl_03` 的 `{C,D}` 条件 incomplete，
且都缺少至少一个真实关系（`ctrl_02` 的真实集合虽被提出但条件未过，故不算 exact）。

内层归一化（次级敏感性，不是主结果）：当同一关系同时列了外层语句和它的函数体时，保留
最内层语句，丢掉外层容器。它只用于回答“模型是否说中了同一个赋值”，不能替代严格可执行
接口。

| 题 | 严格确认 | 内层归一确认 | 严格唯一操作 | 归一唯一操作 |
|---|---:|---:|---|---|
| `get_host` | 0 | 2（85、87） | 12 = 5 U_graph + 7 控制语句 | 6 = 5 U_graph + 1 控制语句（99） |
| `filestorage` | 2（2921、2926） | 4 条记录（2921×3、2926） | 3 = 2 U_graph + 1 `if` 块（2920–2921） | 2（2921、2926） |

严格口径下，模型在真实题上提出的 **8 个唯一新操作全部是控制语句**（`if`/`elif` 块），
不是 U_graph 的可执行赋值；归一化后只剩 `get_host` 的 99 号 `if`。这说明直接 Qwen 的
主要问题不是“想不到关系”，而是**没有操作粒度约束时会把控制语句当成可删除操作**；冻结的
v3 执行器无法执行这类操作。

### 12.5 与语义关系协议的对比

| 指标 | 语义关系协议（C 臂） | Direct Qwen |
|---|---|---|
| pilot VERIFIED | 2 / 14 | 2 / 8 |
| `ctrl_02` exact | false | false |
| `ctrl_03` exact | false | false |
| `get_host` 唯一确认操作 | 2（85、87） | 严格 0；归一 2（85、87） |
| `filestorage` 唯一确认操作 | 3（2921、2924、2926） | 严格 2（2921、2926）；归一 2 |
| 新操作 | 0 | 严格 8 个控制语句；归一 1 个 |
| tokens / wall | 12,223 / 327.4 s | 8,102 / 176.3 s |

关键点：

1. **pilot 上直接 Qwen 并没有更差。** 两者都只验证 2 条，且验证的都是 B、E；两者都在
   `ctrl_02` 提出 `{C,D}` 但因漏 `x<6` 失败；`ctrl_03` 的 `{C,D}` 都失败，只是失败方向
   不同（语义协议 false_accept，直接 Qwen false_reject）。直接 Qwen 没有提出 `{B,E}`，
   但语义协议提出了两条 coexisting 关系也都没有通过。
2. **真实题上直接 Qwen 的严格输出不可执行。** 它把外层 `if` 当成操作，导致 0 个
   `get_host` 集合可被冻结执行器确认；归一化后才恢复到 85、87 两个和语义协议相同的操作。
   它漏掉了 `filestorage` 的 2924，说明直接答案的召回也不完整。
3. **成本更低但买不到正确性。** 直接 Qwen 少约 34% tokens、少约 46% wall，但 0/2 exact、
   0 条真实题条件被验证、真实题严格集合 0/8（`get_host`）被集合确认。
4. **条件仍是瓶颈。** 直接 Qwen 在 pilot 上能给出 B、E 的 exact 条件，和语义协议一样；
   但两个协同集合的条件都不过。真实题的条件完全未评分，不能把“模型写了条件”当成通过。

### 12.6 判断

**Direct Qwen 是一个可用的“关系假设生成器”，但不是端到端求解器；它也不证明语义关系
协议有独立价值。**

- 它能在不看候选列表、不看关系分类的情况下找到 B、E 和 `{C,D}` 集合，说明这些关系主要
  来自代码本身，不是协议“发现”的。语义协议多花的 tokens 买到的是格式对齐和候选操作
  约束，而不是更多的正确关系。
- 它在真实题上暴露了直接答案的核心缺陷：没有操作粒度约束时会把 `if` 当操作，冻结执行器
  无法执行；条件也没有核验器。因此直接 Qwen 不能替代 AST 映射 + 因果执行器。
- 上一节的判断不变，且被这个更强的基线进一步支持：**语义关系发现只保留为可选排序先验/
  假设生成，不作为 Full MACE 的核心发现模块。** 不因本轮结果升级为核心，也不新增题目、
  不扩大 GPU 实验。

### 12.7 产物

| 路径 | 内容 |
|---|---|
| `scripts/run_direct_qwen_baseline.py` | 中性直答 prompt、调用、AST 映射、pilot/真实题评分、离线重放 |
| `scripts/analyze_direct_qwen_baseline.py` | 汇总严格/归一化结果并写 `summary.json` |
| `runs/v3_semantic_relations/direct_end_to_end/results.json` | 第一遍结果（保留，未覆盖） |
| `runs/v3_semantic_relations/direct_end_to_end/rescored/results.json` | 去重后的严格重评（本报告主结果） |
| `runs/v3_semantic_relations/direct_end_to_end/normalized_inner/results.json` | 内层归一化敏感性分析 |
| `runs/v3_semantic_relations/direct_end_to_end/summary.json` | 汇总数字与语义协议对照 |
| `runs/v3_semantic_relations/direct_end_to_end/requests/*.json` | 四题精确 messages、options、prompt sha256 |
| `runs/v3_semantic_relations/direct_end_to_end/raw/*.json` | 四题原始响应 |
| `runs/v3_semantic_relations/direct_end_to_end/gpu_evidence.json` | GPU/Ollama 证据、四题 tokens/wall、泄漏扫描 |
