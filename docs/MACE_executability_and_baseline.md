# MACE 可执行性与真实基线报告

生成日期：2026-11-01  
范围：只使用本轮实际执行的命令、实际模型输出和仓库中已有的冻结文件。  
证据等级：所有“正确/精确”均指在声明的有限域上逐输入相等，状态为 `BOUNDED` 或 `TESTED`；本文没有、也不能声称 `PROVEN`。

---

## 0. 结论速览

1. **真实题的故事成立。** `requests 2.31.0` 的 `parse_header_links` 中，删除 `value = value.strip(replace_chars)` 后，5 个原始测试在 P+ 与 P− 上全部通过；但隐藏的 4 个 `all_special` 输入会暴露删除。原始测试中只有 t1 真正执行了 A 的局部效应，且被下游吸收；t2–t5 根本没有执行 A。没有 assertion gap，也没有测试抓住删除。
2. **Direct Qwen 已真实运行，但没有给出正确提交。** 本机 `Qwen2.5-Coder-1.5B-Instruct` 返回了可解析 JSON；Guard 因使用受限语言之外的 `len()`/`all_special()` 调用被判 `INVALID`，掩盖归因 1/4 正确，反例 1 个有效，测试缺口没有逐项回答。Token 与时间已记录。
3. **在旧受控题 ctrl_01/02/03 上，Pure Symbolic 的 Guard 是 3/3 exact；Direct Qwen 是 1/3 exact；Full MACE 没有产出任何可解析契约。** Full MACE 的失败是本机 1.5B 模型把表达式写成 `<...>` 的记法错误，不是“接口不支持”，也不能写成“0% 正确率”。
4. **三种方法都没有“掩盖操作集合”和“测试缺口解释”的接口。** 这不是答错，而是 `UNSUPPORTED_INTERFACE`。反例只有 checker 生成的见证，不是模型自己写的反例。
5. **存在一次公平设置下的方法对照**（同一 ctrl_01/02/03、同一验证器、同一模型、同一 seed/temperature/轮数），但它受本机 1.5B 模型限制，不能替代 M5/M6 的 32B 历史结论，也不是新的独立测试集。

---

## 1. Q1：真实题是否真的满足“原始测试通过，但隐藏删除风险存在”？

### 1.1 独立复核方法

脚本：[scripts/verify_real_task_story.py](../scripts/verify_real_task_story.py)  
输出：[benchmark_blind_v1/executability/story_verification.json](../benchmark_blind_v1/executability/story_verification.json)、[story_verification.log](../benchmark_blind_v1/executability/story_verification.log)

复核步骤：

1. 从已安装的 `requests 2.31.0` 取真实 `parse_header_links` 源码；
2. 与冻结题面中的源码逐字比较（题面仅多出 `# TARGET_A` 标记，去掉后完全一致）；
3. 从冻结的上游测试块 `tests/test_utils.py:644–664` 还原 5 个 `(value, expected)`；
4. 分别对已安装函数、P+、P− 执行；
5. 用 `sys.settrace` 记录 A 目标行是否执行、A 之后 `value/replace_chars/links` 的局部快照；
6. 分类为 `would_be_caught / masked / unexercised / assertion_gap / test_broken`；
7. 与冻结 oracle 逐字段比对，结果完全一致（`oracle_agreement.matches = true`）。

来源与哈希：

| 项 | 值 |
|---|---|
| requests 版本 | `2.31.0` |
| 已安装源码 SHA-256 | `c9193a0df87262a9a6041998cfa34600d32e8152f508e79b862a31ab5482a720` |
| 冻结题面源码 SHA-256 | `30ec21977962e75df1741ca7d700668fa4d240f5635c3cb320c46eca4a3396aa` |
| P− 源码 SHA-256 | `f4b3b2b7822c8265a2a25f87a4936d4107668c650f427ca2abbc3444a2a2fccd` |
| 上游测试块 SHA-256 | `bc1dc592ba999659c69065eb51f9a6bf435edf3c98c76180f7e80dd4428791e9` |
| 上游测试位置 | `tests/test_utils.py`，644–664 行 |

注意：两个源码哈希不同，是因为冻结题面在目标行加了 `# TARGET_A` 标记；去掉标记后与安装源码相同。脚本在比较前显式做了这一步。

### 1.2 五个原始测试的实际结果

| 测试 | 输入 | P+ 通过 | P− 通过 | A 局部效应 | P+/P− 可观察值相同 | 分类 |
|---|---|---|---|---|---|---|
| t1 | `<http:/.../front.jpeg>; rel=front; type="image/jpeg"` | 是 | 是 | 是 | 是 | `masked` |
| t2 | `<http:/.../front.jpeg>` | 是 | 是 | 否 | 是 | `unexercised` |
| t3 | `<http:/.../front.jpeg>;` | 是 | 是 | 否 | 是 | `unexercised` |
| t4 | `<http:/.../front.jpeg>; type="image/jpeg",<http://.../back.jpeg>;` | 是 | 是 | 否 | 是 | `unexercised` |
| t5 | `""` | 是 | 是 | 否 | 是 | `unexercised` |

计数：

```json
{
  "all_original_tests_pass_on_p_plus": true,
  "all_original_tests_pass_on_p_minus": true,
  "caught": 0,
  "masked_with_local_effect": 1,
  "unexercised": 4,
  "assertion_gap": 0,
  "test_broken": 0,
  "a_exercised": 1,
  "p_plus_minus_observations_differ": 0
}
```

### 1.3 风险是什么、为什么测试看不见

A 是：

```python
value = value.strip(replace_chars)  # replace_chars = " '\""
```

删除后，P− 不再剥掉整串首尾的引号/空格。对普通 URL 输入，后续 `url.strip("<> '\"")` 和各参数的 `strip(replace_chars)` 会把差异吸收，所以 t1 的返回值相同。

但当输入本身只由这些特殊字符组成时，差异暴露。例如：

```text
输入：' "'
P+： []
P−： [{'url': ''}]
```

oracle 的隐藏 eval 中有 4 个这样的暴露输入。它们不在 5 个原始测试中。

### 1.4 Q1 的精确回答

**是，真实题确实满足“原始测试通过，但隐藏删除风险存在”。**

但必须把话说准，不能夸大：

* 5 个原始测试在 P+ 和 P− 上全部通过；
* 只有 t1 真正执行了 A 的局部效应，且被下游吸收（`masked`）；
* t2–t5 是 `unexercised`，不是“执行了 A 但被掩盖”；
* 没有 `assertion_gap`（不存在“P+/P− 可观察值不同但测试仍然通过”的用例）；
* 没有测试抓住删除（`caught = 0`）。

所以正确的表述是：**“原始测试全过；其中 1 个执行了 A 但被掩盖，4 个根本没执行 A；没有任何测试到达暴露输入。”** 这比“所有测试都掩盖了删除”更准确，也足以支持四幕故事。

---

## 2. Q2：Direct Qwen 是否完成了真实题的有效提交？

### 2.1 模型与运行环境

| 项 | 值 |
|---|---|
| 模型 | `Qwen2.5-Coder-1.5B-Instruct` |
| 路径 | `D:/tmp/qwen15b` |
| 参数 | 1,543,714,304 |
| 精度 | bfloat16 |
| 设备 | `cuda:0`（本机 RTX 5060） |
| 传输层 | `transformers` 本地推理；无 API Key、无 Ollama、无 DashScope |
| 解码 | `do_sample=False`，`temperature=0.0`，`seed=42`，`max_new_tokens=1536` |
| Prompt 中的私有信息 | 无 |
| 原始回答写入时机 | 在读取私有 oracle 之前 |
| 私有 oracle 用途 | 仅评分；没有回写或修正模型输出 |

传输适配器：[scripts/local_qwen_client.py](../scripts/local_qwen_client.py)  
基线脚本：[scripts/run_blind_baseline.py](../scripts/run_blind_baseline.py)

### 2.2 两次提交与协议修正

第一次运行（v1）时，发现一个**评测协议自身的不一致**：

* 公开提交 schema 的 counterexample 字段是 `{"claim": ..., "value": ...}`；
* 但 prompt 的示例写成了 `{"exists": true, "value": "..."}`。

模型按 prompt 返回了 `{"exists": false}`，评分器按 schema 读取 `claim`，因此该项无法计分。这是我们的示例错误，不是模型没有回答。

修正只做了字段名对齐（`exists` → `claim`），没有加入任何私有标签、正确 Guard、归因或新提示信息；随后用 `--out-prefix task_01_direct_qwen_v2` 重跑。v1 与 v2 的原始文件都保留，未覆盖。

此外，在两次运行前，prompt 中曾发现一处会泄露 probe 正确标签的示例（`op_1`/`op_3` 的具体组合），已改为占位符 `op_<k>`；两次实际发送的 prompt 均不含私有标签。

Prompt 哈希：

| 运行 | prompt SHA-256 | public task SHA-256 |
|---|---|---|
| v1 | `423c5fa2aa9f56df37658a189b7834c65e2d486172d49a061578ac89c9b01be7` | `a20efe0664a8539553c64c122222b2debbef12c1ed55f4fab30f29aeb4472486` |
| v2 | `d9e97d428fcbc5d522f240f9277194e70999985cb619483d0389cef73a430575` | 同上 |

### 2.3 实际提交（v2，主提交）

```json
{
  "guard": {
    "expr": "len(value) > 0 and not all_special(value)",
    "status": "BOUNDED"
  },
  "masking": {
    "probes": [
      {"probe_id": "p1", "absorber_sets": [["op_1"]], "kind": "independent"},
      {"probe_id": "p2", "absorber_sets": [["op_2"]], "kind": "independent"},
      {"probe_id": "p3", "absorber_sets": [["op_3"]], "kind": "independent"},
      {"probe_id": "p4", "absorber_sets": [["op_1"], ["op_2"], ["op_3"]], "kind": "cooperative"}
    ]
  },
  "counterexample": {"claim": "exists", "value": "' \"'"},
  "test_gap": {"verdict": "none", "tests": []},
  "evidence": "The deletion is observable on probe p1 because it removes the strip operation."
}
```

原始回答：[task_01_direct_qwen_v2_raw.json](../benchmark_blind_v1/executability/task_01_direct_qwen_v2_raw.json)  
评分结果：[task_01_direct_qwen_v2_scored.json](../benchmark_blind_v1/executability/task_01_direct_qwen_v2_scored.json)

### 2.4 逐维评分

| 维度 | 结果 | 说明 |
|---|---|---|
| 提交状态 | `ANSWERED` | 返回了一个可解析的 JSON 对象 |
| Guard | `INVALID` | `len(value)` 和 `all_special(value)` 不在公开受限语言内；每个隐藏用例都在求值前报 `ValueError` |
| Guard 语义（把同一谓词改写成 `nonempty and not all_special` 后） | `sound=true`，`complete=false`，`exact=false` | 只漏掉空串 1 个用例（n1）；若只看语义，比“完全错误”更接近正确，但仍然是错的 |
| 掩盖归因 | 1/4 exact | p1 正确；p2 应为 `op_3`，p3 应为 `{op_1, op_3}` cooperative，p4 应为 `[] / none` |
| 反例 | 有效 | `' "'` 使 P+ 返回 `[]`，P− 返回 `[{"url": ""}]`；这是真实执行差异，不是 checker 代写 |
| 测试缺口 | 聚合结论错误 | 模型说“no gap”，但实际是 1 个 `masked` + 4 个 `unexercised`；没有给出 t1–t5 的逐项 verdict，逐项覆盖 0/5 |

v1 的对照：

| 维度 | v1 | v2 |
|---|---|---|
| Guard | `INVALID`（`len(value) <= 0`） | `INVALID`（`len(value) > 0 and not all_special(value)`） |
| Guard 语义改写 | `not nonempty`，sound 但漏 9 个用例 | `nonempty and not all_special`，sound 但漏 1 个用例 |
| 掩盖归因 | 1/4 exact | 1/4 exact |
| 反例 | `{"exists": false}`，因 schema 字段不一致未计分 | `{"claim": "exists", "value": "' \"'"}`，有效 |
| 测试缺口 | 0/5 覆盖，聚合“no gap”错误 | 0/5 覆盖，聚合“no gap”错误 |

v2 的 Guard 语义比 v1 更接近正确，但这是因为 prompt 的字段名改动改变了生成文本，**不能归因于模型能力提升，也不能算作我们为了提高分数所做的提示调优**。两次 Guard 都是 `INVALID`，都没有得到 exact。

### 2.5 Token 与时间

| 运行 | Prompt tokens | Completion tokens | Total tokens | 生成时间 | 外层墙钟（含模型加载） |
|---|---|---|---|---|---|
| v1 | 1,131 | 217 | 1,348 | 7.599 s | 17.236 s |
| v2 | 1,138 | 229 | 1,367 | 7.504 s | 18.425 s |

### 2.6 Q2 的精确回答

**Direct Qwen 完成了一次“协议上可解析”的提交，但没有完成“正确或完全有效”的提交。**

* 它确实调用了模型，返回了 JSON，没有 BLOCKED，也没有伪造；
* Guard 字段因受限语言违规被判 `INVALID`，不是 0% 正确率，而是“无法进入有界评分”；
* 掩盖归因 1/4，测试缺口聚合结论错误；
* 反例是本次唯一完全正确的维度，且是模型自己给出的值，不是 checker 代填；
* 所有 token、时间、prompt、原始回答和评分均已落盘。

---

## 3. Q3/Q4/Q5：旧受控题上的功能对照

### 3.1 设置与边界

* 任务：`ctrl_01`、`ctrl_02`、`ctrl_03`，来自 `benchmark_pilot/tasks.json`；
* 这是**旧开发/受控 Pilot 题**，不是新的独立测试集；没有修改任何历史标签；
* 同一有限域、同一 `sandbox.analyze`/`verify` 验证器、同一模型、同一 `seed=42`、同一 `temperature=0`；
* Direct Qwen 与 Full MACE 都是 2 轮（`rounds=2`）；
* Pure Symbolic 为 `derive_guard(fixture, use_summaries=False)`，0 token；
* 所有方法都只使用公开题面构造 fixture；没有把私有 oracle 传给模型。

脚本：[scripts/run_controlled_comparison.py](../scripts/run_controlled_comparison.py)  
结果：[benchmark_blind_v1/executability/controlled_comparison.json](../benchmark_blind_v1/executability/controlled_comparison.json)  
逐次运行记录：`benchmark_blind_v1/executability/runs/ctrl_0*/`

### 3.2 Guard 结果

| 任务 | Pure Symbolic | Direct Qwen | Full MACE |
|---|---|---|---|
| ctrl_01 | `mode == 0`，exact | `(mode == 0)`，`GUARD_VERIFIED`，exact | `NO_RESULT`，无可解析契约 |
| ctrl_02 | exact（长表达式，见下） | `(c == 0) and (d == 0)`，`REFUTED`，unsound=1 | `NO_RESULT`，无可解析契约 |
| ctrl_03 | exact（长表达式，见下） | `(p == 0) and (q == 0) and (d == 0)`，`REFUTED`，incomplete=14 | `NO_RESULT`，无可解析契约 |

Pure Symbolic 的 ctrl_02 Guard：

```text
(6 + x) // 6 * 6 // 7 * 7 == 6 * (x // 6) // 7 * 7 and c == 0 and (d == 0)
or (not d == 0 and (6 + x) // 6 * 6 == 6 * (x // 6) and (c == 0))
or (not c == 0 and (6 + x) // 7 * 7 == 7 * (x // 7) and (d == 0))
```

Pure Symbolic 的 ctrl_03 Guard：

```text
q == 0 or p == 0
or ((4 + x) // 3 * 3 // 7 * 7 == 3 * (x // 3) // 7 * 7 and c == 0 and (d == 0))
or (not d == 0 and (4 + x) // 7 * 7 == 7 * (x // 7) and (c == 0))
or (not c == 0 and (4 + x) // 3 * 3 == 3 * (x // 3) and (d == 0))
```

Direct Qwen 的错误是语义错误：

* ctrl_02：`(c == 0) and (d == 0)` 对 `x=6,c=0,d=0` 预测“被掩盖”，但 P+ 返回 7、P− 返回 0，属于 unsound；
* ctrl_03：`(p == 0) and (q == 0) and (d == 0)` 漏掉 `p=0,q=1` 等回退路径，属于 incomplete。

Full MACE 的失败是**模型记法/格式错误**，不是接口不支持：

* 两轮都返回了 `<v_post == v>`、`<mode == 0>` 这类用尖括号包住表达式的文本；
* `parse_bundle` 在 `T1.expr` 报 `invalid syntax`；
* 目标表达式本身（`v_post == v` 等）在 MACE 的受限语言里是可表达的，所以这不是“接口无法表达”，而是模型没有按语法输出；
* 因为没有任何一轮进入验证，**不能给 Full MACE 记 0% 正确率**；正确记录是 `0/3 typed`，正确性 `UNKNOWN`。

### 3.3 能力矩阵

| 能力 | Pure Symbolic | Direct Qwen（guard-only） | Full MACE |
|---|---|---|---|
| Guard | `SUPPORTED`，3/3 exact，0 token | `SUPPORTED`，1/3 exact；1 unsound，1 incomplete | `INVALID/UNKNOWN`，0/3 typed；模型记法错误，未评分 |
| 掩盖操作与组合 | `UNSUPPORTED_INTERFACE` | `UNSUPPORTED_INTERFACE` | `UNSUPPORTED_INTERFACE` |
| 有效反例 | `UNSUPPORTED_INTERFACE`（guard exact，不需要反例；没有模型写反例的接口） | `CHECKER_GENERATED_ONLY`：checker 在 ctrl_01/02/03 都给出了真实 P+/P− 暴露见证；不是模型自己写的 | `NOT_PRODUCED`：验证器接口存在，但本次没有契约可验证，未产生见证 |
| 测试缺口解释 | `UNSUPPORTED_INTERFACE` | `UNSUPPORTED_INTERFACE` | `UNSUPPORTED_INTERFACE` |

关键说明：

* **掩盖操作集合**不是这三种方法的能力。MACE 的 prompt/verify 明确不枚举 source-operation 子集；Pure Symbolic 的文档也写明不枚举操作子集。`benchmark_pilot/engine.py` 能计算这些集合，但它是**评测引擎**，不是被比较的方法。因此这里应记 `UNSUPPORTED_INTERFACE`，不能记为“答错”。
* **测试缺口**在 `mace/` 中没有任何接口；三种方法都不解析 `existing_tests` 的来源、局部效应或吸收关系。这里也是 `UNSUPPORTED_INTERFACE`。
* **反例**：checker 会在配对执行中给出真实见证；这是验证器能力，不是模型生成反例的能力。例如 ctrl_02 的 `x=1,c=0,d=1`：P+ 返回 6，P− 返回 0，是有效暴露见证。三个 ctrl 题都有这类见证，但不能写成“模型自己找到了反例”。

### 3.4 成本

| 任务 | Pure Symbolic | Direct Qwen | Full MACE |
|---|---|---|---|
| ctrl_01 | 0 token / 0.096 s | 608 token / 12.223 s（decode 2.106 s；首轮含模型加载） | 3,444 token / 17.960 s（decode 17.867 s） |
| ctrl_02 | 0 token / 0.098 s | 1,562 token / 2.757 s（decode 2.390 s） | 3,397 token / 14.876 s（decode 14.783 s） |
| ctrl_03 | 0 token / 0.102 s | 1,807 token / 2.724 s（decode 2.318 s） | 3,476 token / 13.356 s（decode 13.251 s） |
| 合计 | 0 token / 0.296 s | 3,977 token / 17.704 s | 10,317 token / 46.192 s |

Token 为 prompt + completion；Full MACE 2 轮共 2 次调用（每轮 1 次），Direct Qwen ctrl_01 只用了 1 轮就 `GUARD_VERIFIED`，ctrl_02/03 用满 2 轮。

### 3.5 Q3/Q4/Q5 的精确回答

**Q3：原版 MACE 在旧受控题上能完成哪些核心功能？**

* Guard：接口存在，但本次 1.5B 模型没有产出任何可解析契约，所以这三次运行没有完成 Guard；不能据此判断 32B 配置的上限。
* 掩盖操作与组合：没有接口，`UNSUPPORTED_INTERFACE`。
* 有效反例：验证器接口存在，但本次没有契约可验证，未产生见证。
* 测试缺口解释：没有接口，`UNSUPPORTED_INTERFACE`。

**Q4：哪些失败是语义错误，哪些只是接口不支持？**

| 失败/限制 | 归类 | 理由 |
|---|---|---|
| Direct Qwen blind Guard `INVALID` | 受限语言/格式违规 + 语义不完整 | 使用 `len()`、`all_special()` 调用；改写成允许谓词后仍漏 1 个空串用例 |
| Direct Qwen blind 掩盖 p2/p3/p4 错误 | 语义错误 | 操作集或 kind 与 oracle 不符 |
| Direct Qwen blind 测试缺口“no gap” | 聚合语义错误；逐项未回答 | 实际存在 1 masked + 4 unexercised |
| Direct Qwen ctrl_02 unsound | 语义错误 | 对暴露输入预测为掩盖 |
| Direct Qwen ctrl_03 incomplete | 语义错误 | 漏掉真实掩盖输入 |
| Full MACE ctrl `NO_RESULT` | 模型记法/格式错误 | `<...>` 不是合法表达式；不是接口不支持，也不是已验证的语义错误 |
| Full MACE blind `UNSUPPORTED` | 接口/语法子集限制 | `build_pair` 拒绝 `split`/`strip`/`import`/`try` |
| Pure Symbolic blind `UNSUPPORTED` | 接口限制 | `mace.domain` 没有 `str` sort |
| 掩盖操作集合、测试缺口 | 接口不支持 | `mace/` 没有对应接口；不能记作答错 |

**Q5：是否存在至少一次公平的方法对照？**

是：在 ctrl_01/02/03 上，三种方法使用同一有限域、同一验证器、同一模型、同一 seed/temperature、同一轮数；Pure Symbolic 不使用 LLM。这是一次真实的、设置可比的小规模对照。

但它有明确限制：

* 模型是 1.5B，不是 M5/M6 使用的 32B；不能把本次 Full MACE 的 `NO_RESULT` 与历史 32B 结果直接比较；
* ctrl_01/02/03 是旧 Pilot 受控题，不是新的独立测试集；
* Full MACE 在本次没有 typed 输出，因此这次对照只真正比较了 Pure Symbolic 与 Direct Qwen 的 Guard，另外两项能力没有方法实现；
* 没有在 blind 真实题上做三方法对照，因为 Full MACE 和 Pure Symbolic 都在前置接口处 `UNSUPPORTED`。

---

## 4. 本轮没有做的事

* 没有新增 Agent、没有训练、没有为了分数做 prompt 调优；
* 没有修改 M1–M6 的历史结果、提交、tag、日志、报告或标签；
* 没有把人工摘要当成算法分数；
* 没有把有限域结果写成 `PROVEN`；
* 没有把 `UNSUPPORTED_INTERFACE` 或 `NO_RESULT` 写成 0% 正确率；
* 没有把私有 oracle、正确 Guard、隐藏标签或标准归因传入 Prompt；
* 没有在提交答案之前用私有真值修正模型输出；
* 没有把旧 Pilot 题称为全新独立测试；
* 没有为 Full MACE 增加“让它能接受请求”的新算法能力。

本轮未重跑完整 pytest；只在本阶段实际运行了上述脚本。此前阶段的完整测试结果不能当作本轮新代码的验证。

---

## 5. 复现命令

```bash
cd <local-path>

# Q1: 独立复核五个上游测试
python scripts/verify_real_task_story.py

# Q2: 真实题 Direct Qwen 基线
python scripts/run_blind_baseline.py --model-path D:/tmp/qwen15b \
  --max-new-tokens 1536 --out-prefix task_01_direct_qwen_v2

# Q3/Q4/Q5: 三道旧受控题的三方法对照
python scripts/run_controlled_comparison.py \
  --methods pure_symbolic,direct_qwen,full_mace \
  --model-path D:/tmp/qwen15b --rounds 2
```

---

## 6. 证据文件索引

| 内容 | 路径 |
|---|---|
| Q1 复核结果 | [benchmark_blind_v1/executability/story_verification.json](../benchmark_blind_v1/executability/story_verification.json) |
| Q1 可读日志 | [benchmark_blind_v1/executability/story_verification.log](../benchmark_blind_v1/executability/story_verification.log) |
| Direct Qwen v1 原始回答 | [benchmark_blind_v1/executability/task_01_direct_qwen_raw.json](../benchmark_blind_v1/executability/task_01_direct_qwen_raw.json) |
| Direct Qwen v1 评分 | [benchmark_blind_v1/executability/task_01_direct_qwen_scored.json](../benchmark_blind_v1/executability/task_01_direct_qwen_scored.json) |
| Direct Qwen v2 原始回答（主提交） | [benchmark_blind_v1/executability/task_01_direct_qwen_v2_raw.json](../benchmark_blind_v1/executability/task_01_direct_qwen_v2_raw.json) |
| Direct Qwen v2 评分 | [benchmark_blind_v1/executability/task_01_direct_qwen_v2_scored.json](../benchmark_blind_v1/executability/task_01_direct_qwen_v2_scored.json) |
| 三方法对照 | [benchmark_blind_v1/executability/controlled_comparison.json](../benchmark_blind_v1/executability/controlled_comparison.json) |
| 逐次运行记录 | `benchmark_blind_v1/executability/runs/ctrl_0*/` |
| 旧环境探针（不是本轮基线） | [benchmark_blind_v1/results/comparison_summary.json](../benchmark_blind_v1/results/comparison_summary.json) |

关于最后一项：`comparison_summary.json` 是**恢复本地模型之前的 provider 探针**，它记录的是“当时没有 Ollama/DashScope，所以 0 个方法回答”。它不是本轮的 Direct Qwen 基线；本轮的基线在 `executability/`。两者不矛盾，但读者不能把旧探针的 `answered_methods: 0` 当成“Direct Qwen 跑不通”。新增说明见 [benchmark_blind_v1/results/README_executability_addendum.md](../benchmark_blind_v1/results/README_executability_addendum.md)。
