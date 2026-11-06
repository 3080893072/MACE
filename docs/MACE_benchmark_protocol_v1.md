# MACE Benchmark Protocol v1

日期：2026-11-01  
分支：`benchmark-pilot`  
范围：冻结统一题面、公开/私有评价数据、最小盲测集与一次方法探测；不修改
M1–M6 历史结果，不重新训练，不优化 Prompt，不迭代评分器。

> **状态声明。** 已有的 5 道题（`ctrl_01/02/03`、`real_formatdef`、
> `real_setdiff`）是 **Pilot**。它们参与过多轮审查，不能被称为“全新独立测试
> 集”。本协议新增的 `blind_01_parse_header_links` 才是 v1 盲测题。已有题目的
> 数据、提交记录与历史标签全部保留，不因本协议改写。

---

## 0. 一句话结论

**协议与一道真实盲测题已经冻结；但最小方法比较无法执行。**
Direct Qwen 因本机没有可用的 Qwen 服务而 BLOCKED；Full MACE 的前端拒绝该真实
源码（UNSUPPORTED）；Pure Symbolic 的公开 fixture 接口没有 `str` 输入域
（UNSUPPORTED，诊断性直接调用返回 UNKNOWN）。三种方法都没有产生答案，因此
**不能报告任何正确率、Token 成本或解释质量对比**。

**论文实验最低证据：NO-GO。** 这不是“MACE 得了 0 分”，而是“这一轮没有可评分的
方法输出”。详见第 11 节。

---

## 1. 固定的研究故事

题目必须能表达四幕，而不是只表达“删掉 A 后输出变不变”：

1. **第一幕：怀疑。** 程序员看到后续代码对同一个值做了规范化，怀疑 A 冗余。
2. **第二幕：删除。** 删除 A 后，现有测试全部通过。
3. **第三幕：风险。** 在另一些**合法输入**下，掩盖操作没有执行，或多个操作不再
   共同掩盖 A；删除 A 后行为改变，而现有测试没有覆盖这些输入。
4. **第四幕：解释。** 系统要回答：A 能不能删？什么条件下安全？谁掩盖了它？
   为什么测试没发现？能否给出暴露问题的反例？

因此，一道合格的条件性掩盖题必须同时具备：

- 删除后行为不变的合法输入（masked）；
- 删除后行为改变的合法输入（exposed）；
- 对“现有测试为什么没发现”的可执行归因；
- 一个真实或明确标注为假设的删除 A。

完全冗余的真实删除题可以没有 exposed 输入，但必须明确报告“本域内不存在暴露
输入”；不得为了凑第三幕而人为制造不存在的反例。

---

## 2. 三类输入与三类局部效应

### 2.1 三类输入

| 名称 | 定义 | 是否公开 |
|---|---|---|
| `T_original` | 程序员已有的测试。真实项目测试必须有仓库/版本/路径/行号/哈希来源；人工编写的测试必须标记为“模拟测试”。 | 公开（作为题面背景） |
| `T_eval_masked` | 删除 A 后可观察行为不变的合法输入。 | 私有（只给评分器） |
| `T_eval_exposed` | 删除 A 后可观察行为改变的合法输入。 | 私有（只给评分器） |

条件性掩盖题：`T_eval_masked` 与 `T_eval_exposed` **都必须非空**。
完全冗余题：`T_eval_exposed` 可以为空，但私有 oracle 必须记录“本域内不存在
exposed 输入”，且报告中写 `none_exists` 而不是 `none_found`。

### 2.2 三类局部效应

在 A 所在程序点抓取 `locals()` 快照，比较 P+ 与 P−：

| 类别 | 局部快照 | 最终可观察行为 | 含义 |
|---|---|---|---|
| `no_local_effect` | 相同 | 相同 | A 对局部状态没有影响；删除它当然不可观察 |
| `masked_local_effect` | 不同 | 相同 | A 确实改变了局部状态，但下游操作把它掩盖了 |
| `exposed_local_effect` | 不同 | 不同 | A 的影响最终暴露 |

**三者必须分开报告。** 把“A 没有局部效应”写成“被某个操作掩盖”是错误归因；
把“测试没覆盖到 A 的局部效应”写成“测试被掩盖”也是错误归因。

`T_original` 的测试缺口类别因此细化为：

- `unexercised`：测试输入上 A 没有局部效应，测试根本没有触及删除点；
- `masked`：A 有局部效应，但最终输出相同，测试断言看不出差异；
- `would_be_caught`：P− 上测试失败；
- `assertion_gap`：P+/P− 输出不同但测试仍通过（断言太弱）；
- `test_broken`：P+ 上测试就失败；
- `not_covered`：测试没有执行到相关路径（无法从输入直接判定时使用）。

---

## 3. 公开题面与私有评价数据的分离

### 3.1 公开（方法可以读）

每道题公开：

- `task_id`、`kind`、`status`；
- P+ 源码、入口函数、目标 A 的行号/文本/种类；
- 明确的删除规则（v1 为“把目标行整体替换为同缩进的 `pass`”）与 P− 源码；
- 合法输入规则、可观察行为、异常是否算观察；
- 候选操作的中性编号 `op_1`、`op_2`、…，每个操作的源码位置、表达式、禁用方式；
- `T_original` 与测试来源（仓库、版本、路径、行号、SHA-256）；
- 为什么程序员会怀疑 A 冗余（不含操作角色）；
- Guard 的**特征词汇表**与受限语法；
- 证据等级规则。

公开文件示例：`benchmark_blind_v1/public/task_01_parse_header_links.json`。

### 3.2 私有（只有评分器可以读）

- 正确的 Guard 表达式；
- 正确的掩盖操作集合与掩盖类型（independent / cooperative）；
- `T_eval_masked`、`T_eval_exposed` 的具体输入；
- 每个输入的 P+/P− 观察、局部效应、是否相等；
- 每个输入的干预矩阵与极小掩盖集合；
- `T_original` 的逐测试缺口标签；
- 有限域穷举/随机检查的计数与反例。

私有文件：`benchmark_blind_v1/private/task_01_oracle.json`。

### 3.3 访问规则

1. 被评测方法只能读 `public/`，不得读 `private/`。
2. 评分器在方法输出**冻结之后**才读 `private/`；方法不能根据评分反馈迭代。
3. 公开题面不得包含私有 case id、bucket 名、`minimal_masking_sets`、
   `observations_equal`、`a_has_local_effect` 等字段。
4. `FREEZE.json` 记录公开/私有文件的 SHA-256；方法探测脚本在运行前核对公开
   哈希，哈希不符即拒绝运行。
5. 任何对题面、删除规则、合法输入域、观察量的修改都必须重新冻结并重跑所有
   方法；不得在看到结果后改隐藏输入。

`tests/test_blind_protocol.py` 对上述边界做自动检查。

---

## 4. 任务形式化

### 4.1 程序与删除

- P+：带唯一 `# TARGET_A` 标记的源码；
- A：一个单行赋值语句；
- P−：把该行整体替换为同缩进的 `pass`，其余逐字不变；
- 入口函数：`parse_header_links`；
- 可观察量：返回值；Python 异常也作为观察；
- 观察值规范化：类型感知（`bool` 与 `int` 不混同；dict 顺序无关）。

### 4.2 合法输入域

公开规则必须能被执行器直接检查。v1 盲测题：

> `value` 必须是 Python `str`（任意 Unicode，包括空串）。非 `str` 输入不在合法
> 域内；原函数对它们抛 `AttributeError`。

评价域是**私有有限代表集**，不是全输入域。报告必须写“在冻结评价域上”，不得
写“对所有输入成立”。

### 4.3 候选操作与干预语义

候选操作是源码中除 A 之外的字符串规范化表达式。v1 的干预语义：

> 若操作 `op_k` 未被启用，则在 P+ 与 P− 中同时把该表达式替换为它的接收者
> （例如 `url.strip(...)` → `url`）；其余代码不变。对每个“启用集合”S，比较
> P+ 与 P− 的观察值。

对 `op_k` 的源码位置、表达式和禁用方式都在公开题面中给出；方法不需要猜操作
边界。**操作的角色不公开**：哪个组合真正掩盖 A 只在私有 oracle 中。

### 4.4 掩盖集合的定义

对一个有局部效应的输入：

- 若启用集合 S、禁用其余全部候选操作时 P+ 与 P− 观察相同，且 S 的任意真子集
  都不满足，则 S 是一个**极小掩盖集合**；
- `|S| = 1` 为 `independent`；
- `|S| >= 2` 为 `cooperative`；
- 若存在多个大小不同的极小集合，报告 `mixed`；
- 若所有候选操作都禁用仍然相同，报告 `unexplained`（操作模型不足以解释），
  不得硬塞一个集合。

`op_2` 在 v1 题中是一个真实存在但从不吸收 A 的候选操作（decoy）；它的存在
用于检查方法是否会把“最终输出相同”错误归因给任意操作。

### 4.5 证据等级

| 等级 | 含义 | 允许的表述 |
|---|---|---|
| `BOUNDED` | 只在冻结有限域上执行验证 | “在该域上 sound/complete/exact” |
| `UNKNOWN` | 方法明确弃权或分析器无法判断 | 计为 abstention，不是错误答案 |
| `INVALID` | 方法给出了不合法/不可执行的答案 | 计为 INVALID，不进入正确率分子 |
| `UNSUPPORTED` | 方法前端/接口不接受该题 | **不计作已经分析** |
| `PROVEN` | 需要 assumptions + 可人工复核的形式证明 | 评分器不能机器检查；只标“需人工复核” |

**有限域穷举永远不是 PROVEN。** 任何 `PROVEN` 声称都必须同时给出假设与证明，
且不能被自动计分器当成已证实。

---

## 5. 评分接口（分项报告，不合并）

评分器分别报告以下维度，**不得把其中一项正确写成总体 exact**，也不得加权成
一个单一“总分”冒充正确率。

### 5.0 v1 提交格式

完整字段见 `benchmark_blind_v1/public/SUBMISSION_SCHEMA.json`。最小结构：

```json
{
  "guard": {"expr": "<公开特征上的布尔表达式>", "status": "BOUNDED | UNKNOWN | INVALID"},
  "masking": {
    "probes": [
      {"probe_id": "p1", "absorber_sets": [["op_<k>"]],
       "kind": "independent | cooperative | mixed | none"}
    ]
  },
  "counterexample": {"claim": "exists | none_exists | none_found",
                     "value": "<claim=exists 时必填>"},
  "test_gap": {"tests": [{"name": "<T_original 中测试名>",
                          "verdict": "unexercised | masked | would_be_caught | assertion_gap | test_broken | not_covered",
                          "masking_ops": ["op_<k>"]}]},
  "evidence": "..."
}
```

上例只示意字段形状，**不含本题答案**；本题的正确 Guard、探针标签、反例与
测试缺口归因只在 `benchmark_blind_v1/private/`。

- Guard 与反例在**隐藏评价集**上评分；方法看不到这些输入。
- 掩盖归因在**公开探针**上评分：题面给出 `p1`–`p4` 的输入，不给出标签。
  方法可以对探针执行 P+/P− 或做静态分析，然后报告每个探针的极小掩盖集合与
  类型。这样所有方法拿到相同的探针输入，归因问题可执行、可复核。
- 评分时逐探针对比 `absorber_sets` 的集合是否与私有极小集合**完全相同**，并
  比较 `kind`；暴露探针的正确答案是 `[]` + `none`。
- 缺少某个探针的回答，报告 `uncovered`，不默认算对；把暴露探针报成非空集合，
  报告 `false_masking_claim`。
- 探针与隐藏评价集不相交；探针答案不能直接当作隐藏域的 Guard 正确性。

### A. Guard / 删除风险

在冻结评价域上逐输入执行 P+/P−，把提交表达式用公开特征求值：

- `false_accept`：表达式为真但实际未掩盖 → soundness 失败；
- `false_reject`：表达式为假但实际掩盖 → completeness 失败；
- 报告 `sound`、`complete`、`exact`、逐 case 的反例；
- `evidence_level` 恒为 `BOUNDED`；
- 表达式只允许公开语法；字符串常量、函数调用、属性、下标一律拒绝。

### B. 掩盖操作集合与类型

在**公开探针** `p1`–`p4` 上评分。评分器重新执行全部启用子集，验证提交声明的
集合：

- 集合是否极小；
- 是否真的在“只启用它”时掩盖；
- `kind`（independent / cooperative / none）是否正确；
- 是否漏报、错报、把 decoy 操作算进去；
- 逐探针报告 precision / recall / exact 与 evidence 是否有效；
- 缺少回答：`uncovered`；暴露探针报非空集合：`false_masking_claim`。

真实题若没有可安全干预的操作，报告 `applicable=false`，不得伪造因果。
探针归因成绩不能直接外推为隐藏域 Guard 正确性。

### C. 回归反例

提交的每个输入都实际跑 P+/P−，只有观察真的不同才算有效反例；异常也算观察。

- 声称有反例但全部无效：`invalid_witnesses_only`；
- 声称 `none_exists` 但实际有：`wrong_none_exists_claim`；
- 实际没有且明确声称：`correctly_none_exists`；
- `none_found` 只表示“没找到”，不等于“不存在”。

不得为了给某方法凑分而新增隐藏输入；也不得把人工写的反例算作自动算法输出。

### D. 测试缺口

对每个 `T_original` 测试重新运行 P+/P−，按第 2.2 节分类：

- `unexercised` / `masked` / `would_be_caught` / `assertion_gap` /
  `test_broken` / `not_covered`；
- 若提交把某测试标为 `masked`，还必须命名实际起作用的操作集合；该集合必须是
  真实极小掩盖集合，或包含一个极小集合且其中每个操作单独都能掩盖；
- 报告 `named_ops_valid` 与 `named_ops_minimal`，不能只凭“最终输出相同”得分。

### E. 状态与弃权

每个方法/任务的结果必须有且只有一个状态：

`ANSWERED` / `UNKNOWN` / `INVALID` / `UNSUPPORTED` / `BLOCKED`。

- 只有 `ANSWERED` 可以进入 A–D 的评分；
- `UNKNOWN`/`INVALID` 是弃权或非法答案，单独计数；
- `UNSUPPORTED` 是前端不支持，**不计作已经分析**；
- `BLOCKED` 是环境不可用（例如没有模型服务），不是方法答错。

---

## 6. 冻结流程

1. `python scripts/blind_build.py`：从嵌入的上游源码重建 P+/P−，执行全部标签，
   写 `public/`、`private/`、`FREEZE.json`、`logs/build.log`。
2. `python scripts/blind_build.py --check`：重新推导并逐字节比对；必须输出
   `FREEZE CHECK OK`。
3. 冻结内容：
   - 公开题面 SHA-256；
   - 私有 oracle SHA-256；
   - 构建脚本 SHA-256；
   - 上游函数/测试/许可证 SHA-256；
   - `frozen_at_utc`（内容不变时保留原时间）。
4. 方法探测 `python scripts/blind_probe_methods.py`：
   - 只读公开文件；
   - 运行前核对公开哈希；
   - 记录方法状态、Token、时间、可验证解释；
   - 不读私有 oracle。
5. 方法输出必须先落盘，再进入独立评分；评分阶段才允许读私有 oracle。
6. 若题面/删除规则/合法域/观察量有任何变化：重新冻结、重新运行全部方法；
   不允许只改隐藏输入让某个方法“答对”。

---

## 7. 最小方法比较协议

三种方法接收**相同的公开信息**：

| 方法 | 输入 | 前端检查 | 失败时的状态 |
|---|---|---|---|
| Direct Qwen | 公开题面构造的 prompt | 模型服务可达 | `BLOCKED` |
| Full MACE | 同一 P+ 源码 + 入口 | `mace.program.build_pair` | `UNSUPPORTED` |
| Pure Symbolic | 同一 P+ 源码 + fixture | `mace.domain.build_domain` | `UNSUPPORTED` |

统一记录：

- 方法名、provider、model、temperature、seed、num_ctx；
- 原始答案（若有）与 prompt SHA-256；
- prompt/completion/total tokens 与 LLM 调用次数；
- wall-clock 时间；
- 状态（ANSWERED / UNKNOWN / INVALID / UNSUPPORTED / BLOCKED）；
- 是否 `counted_as_analyzed`；
- 可验证解释（执行证据、命中的源码位置、反例）；
- 分项评分（Guard / 掩盖集合 / 掩盖类型 / 反例 / 测试缺口），不合成总分。

禁止：

- 把 `UNSUPPORTED` 或 `BLOCKED` 计作“答错”或“已分析”；
- 为了让某个方法能跑而修改隐藏输入；
- 在看到结果后改 prompt、改题面、改评价域；
- 把人工写的正确摘要算作自动算法成绩。

---

## 8. v1 盲测题：`blind_01_parse_header_links`

### 8.1 来源与删除

| 项 | 值 |
|---|---|
| 项目 | `psf/requests` |
| 版本 / tag | `2.31.0` / `v2.31.0` |
| commit | `147c8511ddbfa5e8f71bbf5c18ede0c4ceb3bba4` |
| 源文件 | `requests/utils.py`，函数行 912–946 |
| 函数 SHA-256 | `c9193a0df87262a9a6041998cfa34600d32e8152f508e79b862a31ab5482a720` |
| 许可证 | Apache-2.0 |
| 测试 | `tests/test_utils.py::test_parse_header_links`，行 644–664，5 个参数化用例 |
| 测试文件 SHA-256 | `5a98862b9e19412592ff497fd9df5920e6c3ab5852f581c21280bbb6af773fc2` |
| A | `value = value.strip(replace_chars)` |
| 删除 | 假设性删除：把 A 行替换为 `pass` |

**A 的删除是假设性的，不是历史提交。** 上游 2.31.0 中 A 仍然存在；本题没有
把它伪装成真实维护 commit。来源与版本已记录，删除规则明确。

### 8.2 为什么怀疑 A 冗余

后续代码对 URL、参数 key 和参数 value 都做了 `strip`，看起来会再次去掉同样的
首尾空格/引号，因此维护者可能认为开头的整串 `strip` 冗余。

### 8.3 候选操作

| ID | 位置 | 表达式 | 禁用方式 |
|---|---|---|---|
| `op_1` | 第 26 行 | `url.strip("<> '\"")` | 替换为 `url` |
| `op_2` | 第 34 行 | `key.strip(replace_chars)` | 替换为 `key` |
| `op_3` | 第 34 行 | `value.strip(replace_chars)` | 替换为 `value` |

第 26/34 行是 P+ 中的行号；公开题面给出行号、列号与表达式。

### 8.4 冻结评价域

14 个合法输入，分为：

- 6 个 `masked_local_effect`：A 改变局部值，但最终观察相同；
- 4 个 `exposed_local_effect`：A 的局部效应最终暴露；
- 4 个 `no_local_effect`：A 对局部值没有影响，删除当然不可观察。

这 14 个输入只在私有 oracle 中；公开题面只给合法输入规则与“私有有限代表集”
的说明。

另有 4 个**公开探针**（输入公开、标签私有），用于掩盖归因评分：

| 探针 | 输入 |
|---|---|
| `p1` | `' "<http://p>" '`（首尾空格/引号） |
| `p2` | `'<http://p>; rel=y '`（尾部空格） |
| `p3` | `' "<http://p>; rel=y" '`（首尾都有） |
| `p4` | `'  '`（两个空格） |

探针与 14 个隐藏输入不相交；公开题面只给 `p1`–`p4` 的输入，标签只在
`private/task_01_oracle.json`。本节及 8.6–8.7 的标签与计数是**事后协议审查
材料**，不是方法输入；方法只能读 `public/`。

### 8.5 T_original 的测试缺口

5 个真实上游测试在 P+ 与 P− 上全部通过：

- 4 个 `unexercised`：测试输入上 A 没有局部效应；
- 1 个 `masked`：A 有局部效应，但下游 `strip` 把差异吸收；
- 0 个 `would_be_caught`，0 个 `assertion_gap`，0 个 `test_broken`。

这正是第二幕/第三幕的核心：**现有测试通过，并不等于删除安全；其中一个测试
甚至触发了 A 的局部效应，但仍然看不到最终差异。**

### 8.6 正确 Guard 与有限检查

正确的 Guard（私有）：

```text
not (nonempty and all_special)
```

公开特征：

- `nonempty = len(value) > 0`
- `all_special = all(ch in " '\"" for ch in value)`

含义：只有“非空且所有字符都是空格/单引号/双引号”的输入会暴露差异；其余输入
要么为空（A 无局部效应），要么包含普通字符（下游 `strip` 仍能吸收）。

验证结果：

| 检查 | 规模 | 结果 |
|---|---|---|
| 冻结评价域 | 14 | sound、complete、exact |
| 穷举 | 字母表 `" '\"<>;=,abc"`，长度 0–5，共 177,156 串 | 0 mismatch |
| 随机 | 长度 0–30，20,000 串，seed 0 | 0 mismatch |

**这些只是 `BOUNDED` 证据，不是 PROVEN。** 反对“所有 Unicode 字符串”的证明
需要形式化论证；本协议不把有限枚举写成全称正确。

### 8.7 私有标注摘要

| case 类 | 数量 | 极小掩盖集合 |
|---|---|---|
| masked 局部效应 | 6 | 2 个 `{op_1}`、2 个 `{op_3}`、2 个 `{op_1, op_3}` |
| exposed 局部效应 | 4 | 无（任何候选操作组合都不能掩盖） |
| no local effect | 4 | 不适用（不是“被掩盖”） |

`op_2` 在冻结域中从不进入极小集合；它是一个真实但无吸收作用的 decoy。

---

## 9. 最小盲测结果

结果目录：`benchmark_blind_v1/results/`，日志：`benchmark_blind_v1/logs/methods.log`。

| 方法 | 状态 | counted_as_analyzed | 答案 | LLM calls | Tokens | 时间 |
|---|---|---|---|---|---|---|
| Direct Qwen | `BLOCKED` | false | 无 | 0 | 0 | 0.6 s |
| Full MACE | `UNSUPPORTED` | false | 无 | 0 | 0 | 0.02 s |
| Pure Symbolic | `UNSUPPORTED`（诊断 `UNKNOWN`） | false | 无 | 0 | 0 | 0.01 s |

### 9.1 Direct Qwen：BLOCKED

- 本机没有 `ollama` 可执行文件；
- `127.0.0.1:11434` 连接超时；
- 环境变量 `DASHSCOPE_API_KEY` 未设置；
- 没有发起任何模型调用，因此 tokens 为 0，不能报告答案或正确性；
- 已保存将要发送的公开 prompt 与 SHA-256，便于在服务可用后按同一输入重跑。

### 9.2 Full MACE：UNSUPPORTED

`mace.program.build_pair(source, "parse_header_links")` 返回 `supported=False`，
在调用 Qwen 之前就拒绝：

- `str.split` / `str.strip` 属性访问与方法不在支持子集；
- `import re`（Import）不在支持语法；
- 两处 `try/except`（Try）不在支持语法。

这些是真实函数的结构性特征，不是题面写法问题。**UNSUPPORTED 不计作已分析。**

### 9.3 Pure Symbolic：UNSUPPORTED（诊断 UNKNOWN）

- 公开 fixture 接口 `mace.domain.build_domain` 只支持 `bool` / `int` /
  `list[int]`，没有 `str` 参数域，报
  `TermError: unsupported argument sort in domain: str`；
- 作为诊断，绕过 fixture 接口、直接调用 `mace.symbolic.derive_guard`，返回
  `UNKNOWN`，原因 `unsupported constant ' \'"'`，覆盖 3/19 条语句；
- 两个结果都**不计作已分析**，也不把 UNKNOWN 当答错。

### 9.4 这组结果能说明什么

能说明：

- 真实字符串处理函数会落在 Full MACE 当前支持子集之外；
- Pure Symbolic 的公开接口连合法输入域都无法表示；
- 本机没有可复现的 Qwen 服务，Direct Qwen 无法产生基线；
- 因此这一轮**没有**可比较的答案，不能编造正确率。

不能说明：

- MACE 在这些题上“准确率 0%”；
- MACE 不如 Direct Qwen；
- 任何关于方法优劣的统计结论。

---

## 10. 与 Pilot 的关系

| 项目 | 5 道 Pilot 题 | v1 盲测题 |
|---|---|---|
| 是否参与过协议开发 | 是，多轮审查 | 否（本阶段新冻结） |
| 能否称为独立测试集 | **不能** | 只有这一道，仍不足以泛化 |
| 历史标签 | 保留，不改 | 新生成 |
| 真实题性质 | 2 道完全冗余/退化删除，安全删除负例 | 1 道真实函数 + 假设性删除，含 masked 与 exposed |
| 用途 | 机制自检与案例 | v1 盲测与可执行性检查 |

Pilot 的结论仍只适用于“评分机制可执行”；不能把 Pilot 的受控题成绩外推成
真实项目泛化能力。Pilot 真实题的选择偏差（用 `redundant` 关键词筛提交）已在
`docs/MACE_benchmark_pilot.md` 记录：这类筛选系统性偏向安全删除负例。

---

## 11. GO / NO-GO

### 结论：**NO-GO（论文实验最低证据）**

理由：

1. **只有一个新真实任务。** `blind_01` 来自单一仓库、单一函数；即使它有
   masked/exposed 两类输入，也不足以支撑“真实项目泛化”的论文主张。
2. **没有方法产生答案。** Direct Qwen BLOCKED，Full MACE UNSUPPORTED，
   Pure Symbolic UNSUPPORTED/UNKNOWN；0 个 `ANSWERED`，0 个
   `counted_as_analyzed`。没有正确率、Token、时间或解释质量的可比数据。
3. **支持子集与真实代码错位。** Full MACE 拒绝 `split`/`strip`/`try`/`import`；
   Pure Symbolic 没有 `str` 域。这不是靠再写几道题能解决的，需要前端/域扩展
   或明确报告 UNSUPPORTED 率。
4. **Pilot 不是独立测试集。** 5 道题已经参与多轮审查，不能拿来补足样本量。

### 什么条件下可以翻成 GO

- 有可复现的 Qwen 服务（Ollama 或 DashScope），冻结 provider/model/seed；
- 至少 3–5 道**不同仓库**的真实任务，每道都先冻结合法域、观察量、评价域、
  T_original 来源，再运行方法；
- 每道条件性掩盖题同时有 masked 与 exposed 隐藏输入；完全冗余题明确报告
  `none_exists`；
- Full MACE 至少能接受其中一部分真实源码，或论文明确报告“支持率/UNSUPPORTED
  率”而不是把它算作答错；
- Pure Symbolic 支持 `str` 域，或同样明确报告不支持；
- 独立评分（不由方法作者临时写标签），并保留全部冻结哈希与日志。

### 投稿路线建议

在满足上述条件前，不要把当前材料写成“MACE 在真实任务上优于 Direct Qwen”的
方法论文。更诚实的定位是：

- 一个**冻结协议 + 可执行评分机制**的方法学贡献；
- 一个**真实函数上的条件性掩盖案例**；
- 一个**支持子集错位/无可用基线**的负结果与局限分析；
- 或者先扩展 Full MACE 的输入子集，再回到方法对比。

本阶段到此停止题库工程迭代，转入论文写作或投稿路线调整。

---

## 12. 反造假检查表

- [x] 真实函数来源、版本、commit、路径、行号、SHA-256 已记录；
- [x] 删除 A 明确标注为“假设性”，没有伪装成历史 commit；
- [x] 没有为了让任何方法答对而修改隐藏输入；
- [x] 没有把有限域正确写成 PROVEN；
- [x] 没有把人工写的正确摘要算作自动算法成绩；
- [x] 没有把 UNSUPPORTED/BLOCKED 计作已分析或答错；
- [x] 公开题面与私有 oracle 分离，并有哈希与自动测试；
- [x] 方法运行前已冻结题面；结果文件记录 `private_data_used: false`；
- [x] Pilot 的历史数据与标签未修改；
- [x] 没有编造独立测试结果。

---

## 附录：复现命令与文件

```bash
# 1. 重建并冻结盲测题（不需要联网）
python scripts/blind_build.py
python scripts/blind_build.py --check

# 2. 只读公开题面，运行最小方法探测
python scripts/blind_probe_methods.py

# 3. 全部回归测试（含 blind 协议完整性检查）
python -m pytest
```

关键文件：

```text
docs/MACE_benchmark_protocol_v1.md                 本文件
benchmark_blind_v1/public/task_01_parse_header_links.json
benchmark_blind_v1/private/task_01_oracle.json
benchmark_blind_v1/public/SUBMISSION_SCHEMA.json
benchmark_blind_v1/FREEZE.json
benchmark_blind_v1/results/task_01_direct_qwen.json
benchmark_blind_v1/results/task_01_full_mace.json
benchmark_blind_v1/results/task_01_pure_symbolic.json
benchmark_blind_v1/results/comparison_summary.json
benchmark_blind_v1/logs/build.log
benchmark_blind_v1/logs/methods.log
scripts/blind_build.py
scripts/blind_probe_methods.py
tests/test_blind_protocol.py
```
