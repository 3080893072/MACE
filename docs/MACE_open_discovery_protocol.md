# MACE：部分真值 + 开放式掩盖发现 Benchmark 可行性实验

**状态：STOP / NO-GO（仅针对本轮“扩张到新的真实删除任务”）**

**日期：** 2026-11-01

**结论先行：** 原版 Full MACE 不能按统一提交格式给出**可评分的操作级掩盖归因**。即使把 1.5B 模型的 `<expr>` 记法做通用规范化、让 MACE 产出合法 bundle，它的关系种类仍然只有 `target_effect / upstream / observer / mask_guard`，没有“某组下游操作 + independent/cooperative + 具体输入”的字段；它的 `attribution` 是**参数级**因果对比，不是 B/C/D/E 操作归因。按照本轮预注册的门禁，**停止新增题目**，没有创建新的真实任务、隐藏种子或开放式评测集。Guard 结果没有被拿来替代完整掩盖发现结果。

---

## 1. 固定的研究任务

给定：

- 一个真实程序 `P`；
- 一个被提议删除的操作 `A`；
- 已有测试 `T`；
- 一个声明的有限合法输入域（公开）。

方法必须自动发现下游操作及其组合，使得删除 `A` 的影响在这些输入上不可观察，并提交：

1. 操作在源码中的位置（1-based 行号，不是私有操作名）；
2. 关系类型：`independent`（单个操作独立掩盖）、`cooperative`（多个操作合作掩盖，且任何真非空子集都不单独掩盖）、`coexisting`（多个操作同时关闭才暴露，且任何真子集都不暴露）；
3. 一个具体的合法输入，关系在该输入上成立；
4. 一个可执行的布尔条件，描述关系在哪些输入上成立；
5. 一句可检查的语义解释；
6. 若找到，给出一个暴露删除风险的反例输入。

**不向被测方法提供**正确的 B/C/D/E 操作位置、私有 `attribution.json`、oracle guard、隐藏标签或标准关系。操作位置由方法自行从公开源码中识别。

---

## 2. 公开 / 私有边界

| 内容 | 可见性 | 用途 |
|---|---|---|
| `program.source`、`target_A`、删除规则、`input_domain`、已有测试 | 公开 | 同时提供给 Direct Qwen 和 Full MACE |
| `attribution.json` 中的 `op_lines`、`ops`、`absorber_sets`、`coexisting_sets` | 私有 | 只给独立验证器；绝不进 prompt |
| 正确 guard、私有 witness、隐藏标签 | 私有 | 只用于评分；不用于修改模型输出 |
| `SUBMISSION_SCHEMA.json` | 公开 | 两个方法共用同一提交格式 |

本轮接口检查在旧的 `ctrl_01/02/03` 上进行。它们是**旧 Pilot 控制题**，不是新的独立评测集，也不代表真实 commit。它们的私有操作行只进入验证器，不进入 prompt。

公开 prompt 已做泄漏检查，禁止出现 `# OP_`、`op_lines`、`attribution`、`absorber`、`oracle`、API key 标记、`coexisting_unmasking_sets`、`individually_masking_ops`。三份 Direct prompt 的 SHA-256 记录在 `benchmark_open_v1/interface/direct_qwen/*_raw.json`。

---

## 3. 统一提交格式

文件：`benchmark_open_v1/SUBMISSION_SCHEMA.json`

```json
{
  "relations": [
    {
      "operations": [{"line": 4, "text": "if ...:"}],
      "kind": "independent | cooperative | coexisting",
      "input": {"arg": 0},
      "condition": "<restricted boolean expression over argument names>",
      "explanation": "<one sentence>",
      "counterexample": null
    }
  ],
  "guard": {"expr": "<restricted boolean expression>", "status": "BOUNDED | UNKNOWN"},
  "test_gap": [{"test": "<existing test name>", "verdict": "unexercised | masked | would_be_caught | assertion_gap | test_broken | not_covered"}],
  "evidence": "<optional executable observations>"
}
```

约束：

- 每个方法每题最多提交 **5 条不同的关系**；同一 `(operations, kind)` 的重复记录只保留首次，后续记为 `DUPLICATE`，不计入正确数，也不计入 false attribution 的分母。
- `input` 必须是声明域中的**精确合法用例**，不能只给部分参数或域外值。
- `condition` 只允许参数名、int/bool 常量、比较、`and/or/not`、算术；不允许函数调用、属性访问、未声明名字、字符串常量。
- `guard` 不是操作归因的替代品；Guard 正确不等于掩盖发现正确。
- `BOUNDED` 只表示在声明的有限域上执行过，不是 `PROVEN`。

### 关系语义（验证器实际执行的定义）

对操作集合 `S`：

- **independent / cooperative**：只启用 `S`（关闭其补集）时，`P+` 与 `P−` 的观察相等；并且对 `S` 的每个真非空子集，只启用该子集时观察不相等。
- **coexisting**：关闭 `S` 时 `P+` 与 `P−` 的观察不相等；并且对 `S` 的每个真非空子集，关闭该子集时观察相等。
- **condition**：在声明的全部合法输入上，条件为真的集合必须与上述关系实际成立的集合一致（`exact`）。条件可以 `sound`（只漏报）或 `unsound`（过报）；只有 `sound + exact` 才算完整有效。
- **反例**：必须是一个合法输入，且删除 `A` 后观察确实改变（`P+` 与 `P−` 不同）。

---

## 4. 独立验证器

脚本：`scripts/check_open_interface.py`

验证器不导入被测模型，只使用 `benchmark_pilot.engine` 执行：

1. 将提交的行号映射到私有操作（接受 `if` 行或其直接 body 行；其他行记为 `UNVERIFIED`，不是 false）；
2. 检查 `A` 在该输入上有局部效果（`locals()` 快照不同）；
3. 检查原程序在该输入上确实掩盖（`P+` 与 `P−` 观察相等）；
4. 检查声明的操作集合在“只启用该集合”/“关闭该集合”下是否满足对应关系；
5. 对 cooperative 检查所有真非空子集的最小性；对 coexisting 检查所有真子集；
6. 在有限域上检查 `condition` 的 `sound / complete / exact`；
7. 检查反例是否合法、是否真的暴露；
8. 单独检查 Guard 和测试缺口。

记录状态：

- `VERIFIED`：执行检查和 condition 都完整有效；
- `INCOMPLETE`：核心关系在 witness 上成立，但 condition 缺失/不完整；
- `FALSE`：关系在执行上不成立，或 condition 过报（unsound）；
- `UNVERIFIED`：行号无法映射、输入不在域内、无法执行；
- `FORMAT_ERROR`：JSON/字段/条件语言不合法；
- `DUPLICATE`：同一 `(operations, kind)` 的后续重复。

“不能验证的记录为 UNVERIFIED”是本轮硬规则；`UNSUPPORTED` 只表示接口没有该能力，不写成 0% 正确率。

---

## 5. 接口检查结果：ctrl_01 / ctrl_02 / ctrl_03

模型：**Qwen2.5-Coder-1.5B**，本地 `transformers`，bf16，SDPA，`temperature=0`，`seed=42`，`max_new_tokens=1200`；Full MACE `rounds=2`。

产物：

- `benchmark_open_v1/interface/ctrl_interface.json`（总记录）
- `benchmark_open_v1/interface/interface_summary.json`（聚合指标）
- `benchmark_open_v1/interface/direct_qwen/*_raw.json` / `*_scored.json`
- `benchmark_open_v1/interface/runs/<task>/full_mace/`
- `benchmark_open_v1/interface/runs/<task>/full_mace_norm/`
- `benchmark_open_v1/interface/runs/<task>/schema_probe/`

### 5.1 Direct Qwen

| 题目 | 解析 | 唯一关系 | witness 执行通过 | false | unverified | complete valid | Guard exact | 测试缺口 | tokens | wall |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| ctrl_01 | ANSWERED | 1（共 3，2 重复） | 1 | 1 | 0 | 0 | 否（`True` unsound） | 0/2 | 1,271 | 17.8 s |
| ctrl_02 | ANSWERED | 2 | 0 | 2 | 0 | 0 | 否（`True` unsound） | 0/2 | 1,655 | 6.6 s |
| ctrl_03 | ANSWERED | 1（共 2，1 重复） | 0 | 0 | 1 | 0 | 否（`True` unsound） | 0/4 | 2,085 | 8.6 s |
| **合计** | 3/3 可解析 | **4** | **1** | **3** | **1** | **0** | 0/3 | **0/8** | **5,011** | **33.0 s** |

关键细节：

- **ctrl_01**：提交 `B`（第 4 行）`independent`，输入 `{mode:0,x:0}`。执行检查全部通过（该输入上 `B` 单独启用确实掩盖，且原程序确实掩盖；`A` 有局部效果）。但它把 `condition` 写成 `True`，在 `mode=1` 的三个输入上过报，因此记录整体是 **SEMANTIC_ERROR**，不是 complete valid。它提交了 3 条同 `(B, independent)` 的记录，去重后 1 条。
- **ctrl_02**：真实种子是 `{C,D}` cooperative。Qwen 分别提交 `C` 和 `D` 为 independent；验证器执行 `C` 单独或 `D` 单独时 `P+/P−` 仍不同，因此两条都是 **FALSE**。
- **ctrl_03**：提交第 9 行（`D` 的 body，验证器按通用适配映射到 `D`）`independent`，但 `input={"d":0}` 缺少 `p,q,x,c`，不是合法用例，记为 **UNVERIFIED**；第二条映射到同一 `D`，记为 `DUPLICATE`。没有合法 witness，因此不判 false。

因此 Direct Qwen **能输出统一格式、能给出具体操作行和输入**，但在 4 条唯一记录中：0 条完整有效，1 条 witness 级成立但条件过报，3 条执行上不成立，1 条无法验证。它没有提交任何反例（`counterexample` 全为 `null`），测试缺口为空，Guard 全部是 `True` 且 unsound。

### 5.2 Full MACE（原版 pipeline）

| 题目 | 原始运行 | 原始接口 | 规范化后运行 | 规范化后接口 | 操作级关系 | Guard | tokens raw/norm | wall raw/norm |
|---|---|---|---:|---|---:|---|---:|---:|
| ctrl_01 | NO_RESULT | NO_RESULT | ROUNDS_EXHAUSTED | **UNSUPPORTED** | 0 | `True` REFUTED | 3,444 / 5,357 | 16.0 / 16.3 s |
| ctrl_02 | NO_RESULT | NO_RESULT | ROUNDS_EXHAUSTED | **UNSUPPORTED** | 0 | `True` REFUTED | 3,397 / 5,543 | 14.2 / 15.8 s |
| ctrl_03 | NO_RESULT | NO_RESULT | ROUNDS_EXHAUSTED | **UNSUPPORTED** | 0 | `True` REFUTED | 3,476 / 5,473 | 14.0 / 13.1 s |
| **合计** | 0 bundle | — | 3 bundle | **0 可评分** | **0** | 0/3 exact | **10,317 / 16,373** | **44.3 / 45.2 s** |

区分两件事：

1. **原始 Full MACE run 是 NO_RESULT / 格式错误。** 1.5B 把表达式写成 `<v_post == v>`、`<mode == 0>`、`<True>`，解析器报 `T1.expr is not a parsable expression: invalid syntax`。这是模型输出记法问题，不能写成“Full MACE 0% 正确”。
2. **规范化后的 Full MACE 仍然 UNSUPPORTED。** 为排除“只是尖括号”的干扰，加了一个**通用** transport adapter：只把 JSON 字符串值两端的 `<...>` 去掉，不增加、不删除、不选择任何操作；对三题统一应用。之后 bundle 合法，`run_status=ROUNDS_EXHAUSTED`，但接口仍缺操作归因。

规范化后 ctrl_01 的实际结构：

- `final_bundle` 键：`target_effects`, `upstream`, `observers`, `mask_guard`, `uncertainty`；
- `relations` 的 `kind`：`target_effect`, `upstream`, `observer`；
- **没有** `relations[].operations`，没有 per-relation `input`，没有 `independent/cooperative`；
- `attribution.contrast` 是参数级：`mode` 被标为 `causally_relevant=true`，`x` 为 false；这是“哪个参数改变掩盖”，不是“哪组下游操作掩盖”；
- `proof_dag.nodes` 是 `T1/U1/U2/O0/O9/G` 这些合同节点，`source_lines` 是公式出处（如 `[3,4]`、`[4]`），不是操作集合；
- `guard=True`，被 bounded checker 判为 `REFUTED`（ctrl_01 unsound=3；ctrl_02 unsound=19；ctrl_03 unsound=6）。

`upstream` 的 `source_lines` 有时包含操作行（例如 ctrl_01 的 U1 含第 4 行），但它是 `upstream` 公式的 provenance，不是“关闭这组操作会让 `P+/P−` 相等”的 `operations` 字段。用 `source_lines` 反推操作集合会改变合同语义，不能算作接口支持。

**Schema probe（不是模型运行）：** 用一个只含恒真式的 neutral contract 调用同一个 `run_mode`，得到合法 `final_bundle` 和 `final_report`；报告仍然只有 `target_effects/upstream/observers/mask_guard`、参数级 `attribution.contrast` 和 `proof_dag`，没有操作集字段。该 probe 0 token，证明阻断是**结构性的**，不是 1.5B 的记法或能力问题。

### 5.3 状态归类

| 对象 | 状态 | 含义 |
|---|---|---|
| Direct ctrl_01 | `SEMANTIC_ERROR` | JSON 合法、行号有效、witness 成立，但 condition `True` 过报 |
| Direct ctrl_02 | `SEMANTIC_ERROR` | 把 cooperative `{C,D}` 拆成两个 independent，执行上不成立 |
| Direct ctrl_03 | `UNVERIFIED` | 行号可映射，但输入不是合法用例；另一条重复 |
| Full MACE 原始 | `NO_RESULT` / 格式错误 | `<expr>` 不是可解析表达式；不是接口 unsupported，也不是 0% |
| Full MACE 规范化 | `UNSUPPORTED` | 合法 bundle 但无操作集/输入关系 |
| Full MACE schema probe | `UNSUPPORTED` | 与模型无关的合同 schema 缺字段 |
| 任一方法的 complete valid | **0** | 本轮没有完整有效提交 |
| UNKNOWN | 未出现 | Direct 三题都提交了非空 relations；MACE 不是“空回答” |

---

## 6. 指标（仅接口检查，不是新 benchmark 成绩）

这些数字只描述 ctrl_01/02/03 的接口可行性，**不能**当作真实任务上的 Seed Recovery 或方法排名。

| 指标 | Direct Qwen | Full MACE |
|---|---:|---:|
| Seed Recovery（完整有效，6 个控制种子） | 0/6 | N/A（UNSUPPORTED，不评分） |
| Seed Recovery（witness 级、operation+kind 匹配） | 1/6 | N/A（UNSUPPORTED） |
| New Verified Discoveries | 0 | 0 |
| False Attribution Rate（全部唯一记录） | 3/4 = 75% | N/A（无操作关系） |
| False Attribution Rate（只算可执行判定的记录） | 3/3 = 100% | N/A |
| Unverified Rate（全部唯一记录） | 1/4 = 25% | N/A |
| Complete Valid Rate | 0/4 = 0% | N/A（UNSUPPORTED，不评分） |
| Guard exact | 0/3 | 0/3 |
| 测试缺口 | 0/8 正确（全部缺失） | 接口无字段 |
| 有效反例 | 0 | 0（witness 不是提交的操作反例） |
| tokens | 5,011 | 10,317（raw）/ 16,373（norm） |
| 时间 | 33.0 s | 44.3 s（raw）/ 45.2 s（norm） |
| 程序执行次数 | 验证器 220 次 | `run_mode` 未报告，记为 `not_reported` |

说明：

- **Seed Recovery 不是完整 recall。** 6 个控制种子只是旧 Pilot 的检查点；本轮没有新的真实任务，也没有“全部正确关系”的穷举声明。
- Full MACE 的 Seed Recovery 记作 N/A，不是“模型答错 6 条”，而是**接口无法表达操作集关系**，所以不进入正确率分母。
- Direct Qwen 的 1/6 witness 级匹配（ctrl_01 的 `{B}, independent`）也不能算完整正确：它的 condition 过报，记录状态是 `SEMANTIC_ERROR`。
- Full MACE 的 `guard=True` 与 witness 没有被拿来替代缺失的操作归因。

---

## 7. 为什么停止新增题目

本轮预注册的门禁是：

> 如果 Full MACE 不能提供可评分的操作归因，停止新增题目，并报告这一阻断问题。不能用它的 Guard 结果替代完整掩盖发现结果。

实际结果满足 STOP 条件：

1. 原版 Full MACE 的合同 schema 没有 `operations`、per-relation `input`、`independent/cooperative` 字段；
2. 即使把模型输出做通用记法规范化，得到合法 bundle，仍然没有这些字段；
3. neutral-contract schema probe 在没有模型参与时也复现同样的缺字段；
4. 它的 `attribution` 是参数级 contrast，`proof_dag` 是合同关系图，不是源码操作集合；
5. 因此无法在同一提交格式下给 Full MACE 打分，也无法诚实地比较“谁找到更多有效关系”。

**没有创建新的真实任务。** 没有从公开 Python 源码选题，没有候选清单，也没有“被拒案例”清单——因为门禁在选题之前就失败了，继续选题会违反本轮预注册规则。没有隐藏种子、没有开放式评测、没有按最终成绩调指标或题目。

> 新任务选题状态：**未启动**。因此本轮不存在“已接受/已拒绝”的真实项目清单；这不是遗漏，而是 STOP 门禁的规定动作。也没有用任何旧 M1–M6 fixture 冒充新的真实任务。

---

## 8. GO / NO-GO

**NO-GO：本轮不把“部分真值 + 开放式掩盖发现”扩张为新的真实任务 benchmark。**

**STOP 的具体含义：**

- 不新增 3 个真实删除任务；
- 不生成新的隐藏 seed；
- 不运行 Direct Qwen vs Full MACE 的新任务开放式评测；
- 不因为最终分数调整指标、题目或提交格式；
- 不把 Full MACE 的 Guard/witness 写成操作归因。

**可以保留的结论：**

- 统一提交格式是可执行的；Direct Qwen 能按格式输出行号、关系和输入；
- Direct Qwen 在本机 1.5B 上能给出 witness 级成立的候选，但条件归纳仍是瓶颈（`True` 过报、cooperative 被拆成 independent、非法输入），与本项目 M5/M6 的“条件归纳是瓶颈”一致；
- Full MACE 的阻断是**接口级**的，不是“这题太难”或“模型太小”；
- 本轮没有证明任何方法的完整 recall，也没有证明 MACE 在开放发现上优于 Qwen。

**若未来要解锁（本轮不实施）：** 需要先给 Full MACE 增加一个**独立的操作集关系接口**：每个关系至少包含 `operations`（源码行集合）、`kind`（independent/cooperative/coexisting）、per-relation `input`、`condition`，并由现有 bounded checker 验证最小性；然后重新跑本门禁。这个扩展属于新阶段，不能在本轮为了“让 MACE 接受请求”而临时添加。

---

## 9. 复现

```bash
# 接口检查（本机 GPU；模型路径按实际替换）
python scripts/check_open_interface.py \
  --model-path D:/tmp/qwen15b \
  --rounds 2 --max-new-tokens 1200

# 只重新聚合，不调用模型
python scripts/summarize_open_interface.py

# 验证器自检：用 ctrl_01 的已知种子 {B}, condition=mode == 0
# （不调用模型；脚本内的 Verifier 会真实执行 P+/P− 和操作关闭变体）
python -c "from scripts.check_open_interface import Verifier, load_tasks, load_attribution; v=Verifier(load_tasks()['ctrl_01'], load_attribution()['ctrl_01']); print(v.verify_relation({'operations':[{'line':4}],'kind':'independent','input':{'mode':0,'x':0},'condition':'mode == 0','counterexample':None}))"
```

模型：`Qwen2.5-Coder-1.5B`（本地 `D:/tmp/qwen15b`，1,543,714,304 参数，bf16）。没有 API Key，没有 Ollama/DashScope；所有 prompt 与原始回答都落盘。

---

## 10. 产物索引

| 产物 | 路径 |
|---|---|
| 本协议 | `docs/MACE_open_discovery_protocol.md` |
| 通用提交格式 | `benchmark_open_v1/SUBMISSION_SCHEMA.json` |
| 接口总记录 | `benchmark_open_v1/interface/ctrl_interface.json` |
| 聚合指标 | `benchmark_open_v1/interface/interface_summary.json` |
| Direct 原始回答 | `benchmark_open_v1/interface/direct_qwen/ctrl_0*_raw.json` |
| Direct 评分/验证 | `benchmark_open_v1/interface/direct_qwen/ctrl_0*_scored.json` |
| Full MACE 原始运行 | `benchmark_open_v1/interface/runs/<task>/full_mace/` |
| Full MACE 规范化诊断 | `benchmark_open_v1/interface/runs/<task>/full_mace_norm/` |
| Neutral schema probe | `benchmark_open_v1/interface/runs/<task>/schema_probe/` |
| 接口检查脚本 | `scripts/check_open_interface.py` |
| 聚合脚本 | `scripts/summarize_open_interface.py` |

**本轮未修改：** M1–M6 的历史结果、commit、tag、日志、报告、标签；旧 `benchmark_pilot/` 数据。`benchmark_blind_v1/` 的既有差异来自上一阶段 M8，本轮未改；本文件只新增本轮接口检查记录与结论。
