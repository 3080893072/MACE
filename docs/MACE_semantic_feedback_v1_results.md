# MACE Semantic Feedback v1：实现、四题验证与结论

日期：2026-11-04  
代码分支：`research/mace-role-separated-search`  
基线 HEAD：`7591c5d`（本轮新增文件尚未提交）  
产物目录：`runs/v3_semantic_feedback_v1/`

## 1. 本轮做了什么

新增一个独立模式 `semantic_feedback`，不替换 C0，也不替换旧 Qwen 排序。流程是：

```text
AST + Graph 候选
  -> Qwen 显式提出 MSMS 候选集和 MMBS 候选集
  -> 真实执行器/Verifier 逐候选核验
  -> 把真实失败输入和集合级证据反馈给 Qwen
  -> 最多一次修正
  -> 重新执行核验，Verifier 最终确认
```

关键实现：

- `scripts/run_semantic_feedback.py`
  - 新增显式 schema：`msms_candidates` / `mmbs_candidates`，每项包含
    `operations`、`condition`、`source_evidence`、`rationale`、`hypotheses`。
  - 操作粒度：Graph 中已有的可执行单元直接进入候选；新的赋值语句只有经过
    AST 身份映射后才进入 `U_qwen`；新的 `if` / `for` / `while` / `try` 只作为
    `control_context`，绝不进入可删除集合。
  - 保留 `U_graph`，分别记录 `U_qwen` 和 `U_union`，不裁剪任何 Graph 操作。
  - pilot 题用 `Verifier.verify_relation` 核验 MSMS（单元素 independent，
    多元素 cooperative）；MMBS 单元素不能走 `coexisting` 的“至少两个操作”
    门槛，因此新增独立的 singleton 检查。
  - 真实题用 `run_v3_arm` 在 `U_union` 和 `U_graph` 上分别执行；集合是否被
    确认只由执行器返回的 `msms_ids` / `mmbs_ids` 决定，模型输出始终是假设。
  - 反馈内容只包含模型自己候选的真实执行结果：失败 case、参数、条件真假、
    集合是否确认、被剥离的 control context、AST 映射错误；不提供 HIDDEN
    参考答案或真实关系表。
  - 每题最多一次初始调用 + 一次修正调用；修正后必须重新核验，不能直接计为
    正确。
- `scripts/analyze_semantic_feedback.py`：只读汇总，不调用模型或执行器。
- `tests/test_semantic_feedback.py`：CPU 测试，覆盖显式 schema、control
  context 剥离、AST 映射、singleton MMBS、真实反例反馈、无 HIDDEN 泄漏。

历史 A（C0）、B（Direct Qwen）、C（旧语义协议）全部复用
`runs/v3_semantic_relations/results_live.json` 和
`runs/v3_semantic_relations/direct_end_to_end/rescored/results.json`，没有重跑。

## 2. 运行条件与成本

- 云端：AutoDL RTX 4090 D 24564 MiB；`qwen2.5-coder:32b`
  （digest `b92d6a0b…bef41`，Q4_K_M），8192 ctx，100% GPU，21 GB。
- 本机 RTX 5060 未使用。
- 四题各 1 次初始调用 + 1 次修正调用，共 8 次；`retries=0`，0 次调用错误。
- Token：18,822 prompt + 5,648 completion = **24,470**。
- 模型墙钟：**307.876 s**；含本地执行核验的整个实验：**558.301 s**（9.3 分钟，
  低于 30 分钟目标）。
- 没有新增题目，没有运行 515 个旧目标，没有运行 SQLAlchemy coverage，没有修改
  HIDDEN scorer、冻结 Benchmark、执行器语义或数据集工作目录。

逐题调用：

| 任务 | 初始 prompt/completion | 修正 prompt/completion | 模型墙钟 |
|---|---:|---:|---:|
| ctrl_02 | 1,376 / 554 | 2,300 / 468 | 63.798 s |
| ctrl_03 | 1,729 / 715 | 4,464 / 810 | 79.723 s |
| get_host | 1,882 / 986 | 3,240 / 1,010 | 105.876 s |
| filestorage | 1,506 / 545 | 2,325 / 560 | 58.479 s |

GPU 与模型证据：`runs/v3_semantic_feedback_v1/gpu_evidence.json`。  
测试：`tests.log`（定向 44 通过）、`tests_full.log`（全套 **387 通过**）。

## 3. 四题结果

### 3.1 总表

| 任务 | 初始候选 | 最终候选 | 最终确认 | `U_graph` / `U_qwen` | 条件 exact | 最终 FA/FR | 修正修复 |
|---|---:|---:|---:|---:|---:|---:|---:|
| ctrl_02 | 3 | 2 | 0 | 2 / 0 | 0 | 1 / 0 | 0 / 3 |
| ctrl_03 | 4 | 4 | 0 | 4 / 0 | 0 | 0 / 3 | 0 / 4 |
| get_host | 6 | 6 | 4 | 5 / 0 | 不适用 | 0 / 0 | 0 / 2 |
| filestorage | 3 | 3 | 2 | 3 / 0 | 不适用 | 0 / 0 | 0 / 1 |
| **合计** | **16** | **15** | **6** | — | **0** | **1 / 3** | **0 / 10** |

说明：

- pilot 的“确认”要求集合和条件都通过 `Verifier`；真实题没有冻结条件核验器，
  条件一律 `NOT_EVALUATED`，因此真实题的“确认”只是集合被执行器确认。
- `U_qwen=0`、`control_context=0`、`rejected=0` 在四题上都成立。
- 最终候选 15 个，其中 6 个被确认；pilot 6 个候选全部未确认，真实题 9 个候选
  中 6 个确认。

### 3.2 逐题证据

**ctrl_02**

- 初始：MSMS 分别提 `{C}`、`{D}`，MMBS 提 `{C,D}`；三个集合都被 Verifier
  判为 FALSE（单元素不能单独掩盖，`{C,D}` 的 MMBS 有真子集已经暴露 A）。
- 修正后：MSMS 变成 `{C,D}`，条件 `c == 0 or d == 0`；MMBS 仍是 `{C,D}`，
  条件 `c != 0 and d != 0`。
- `{C,D}` 的集合是对的（MSMS set precision/recall 1.0/1.0），但条件仍不对：
  `false_accept` 13 个 case，包含 `case_0020`（`x=6,c=0,d=0`）。正确条件需要
  `x < 6`，模型没有补上。最终 0 个 VERIFIED，条件 exact 0。
- 初始反馈没有条件级反例：前三个候选在“集合是否成立”这一步就被拒绝，
  `verify_relation` 没有进入条件评分；因此 ctrl_02 的修正没有看到
  `case_0020`。这是本轮反馈设计的一个具体缺口。

**ctrl_03**

- 初始：MSMS 提 `{B,C,D,E}` 且条件 `True`；MMBS 提 `{B,E}`、`{D}`、`{C}`。
- 修正后：MSMS 仍是 `{B,C,D,E}`（条件 `True`）；MMBS 三个集合保留，条件改成
  含 `d/c` 的合取式。
- `{B,E}` 作为 MMBS 集合被保留，集合匹配正确；但条件仍不 exact，Verifier 返回
  FALSE。旧 C 臂中验证通过的 `B(p==0)`、`E(q==0)` 两个单元素 MSMS 没有被本轮
  找到；最终 0 个 VERIFIED。
- 初始 MMBS `{B,E}` 的反馈确实带了 `false_accept case_0012/0013` 和
  `false_reject case_0000…0011`；模型修正后仍然没有给出正确条件。这说明即使
  提供了真实反例，32B 模型也没有完成条件归纳。

**get_host**

- 最终 MSMS：85 `SET_CONFIRMED`、87 `SET_CONFIRMED`、90
  `UNCONFIRMED_INCOMPLETE`；MMBS 同样 85/87 确认、90 未确认。
- 模型只引用了 Graph 中的赋值语句，没有把 `if` 行当作可删除操作；
  `control_context=0`，严格映射干净。这是粒度提示起作用的地方，也是它相对
  Direct Qwen 严格口径（0/8，8 条关系全部含 `if` 控制节点）的表面改善。
- 但相对 C0 没有新增收益：C0 已经确认 85/87 两个 MSMS 和两个 MMBS；D 的 4 个
  确认集合全部落在 C0 已确认集合内，90 号仍未确认，探针数同样是 194。

**filestorage**

- 最终 MSMS：2924 确认、2926 确认；MMBS：2921 `NOT_CONFIRMED`。
- 模型找到了 2924 和 2926 两个正确的 MSMS 集合；但它没有给出 C0 已确认的
  2921/2924 MMBS 组合，2921 的 MMBS 条件也没有被确认。
- 本模式没有“assertion gap”接口：输出只有 MSMS/MMBS，2921 未被确认时不能
  自动解释为 assertion gap。该题只验证了 masking 一侧，没有区分 masking 与
  assertion gap。

## 4. 与 A/B/C 的对照

| 方法 | pilot | 真实题 | 成本 | 探针 |
|---|---|---|---|---:|
| A C0 | 集合由执行器确认；无条件评分 | get_host 4 个唯一集合；filestorage 4 个 | 0 token | 240 / 680 / 194 / 68 |
| B Direct Qwen | 2/8 VERIFIED | 严格 get_host 0/8；filestorage 2/4 | 8,102 token / 176.3 s | 不搜索 |
| C 旧语义协议 | 2/14 VERIFIED | get_host 2/12 条记录、filestorage 5/7 条记录；确认集合与 A 相同 | 12,223 token / 327.4 s | 240 / 680 / 194 / 68 |
| D Feedback v1 | **0/6 VERIFIED**；2/6 集合正确；0 exact | **6/15 候选确认**（4 get_host + 2 filestorage）；无新增 | **24,470 token / 307.9 s** | **240 / 680 / 194 / 68** |

D 的探针数与 C0 完全相同，说明反馈假设没有改变搜索成本，也没有减少探针。
D 的首确认探针在 ctrl_02（MSMS 4.0 vs A 3.0）、ctrl_03（MSMS 8.143 vs A 6.0、
C 3.714）、filestorage（MMBS 6.0 vs A/C 3.0）上更差；get_host 与 C 相同
（2.667/3.667）。

## 5. 五个必须回答的问题

### 5.1 Qwen 是否发现了 Graph 未发现的操作？

**没有。** 四题 `U_qwen` 都是 0，`rejected` 都是 0，`control_context` 都是 0。
模型的所有候选操作都来自 prompt 中列出的 `U_graph`；它没有提出新的赋值语句。
因此本轮既没有证明也没有否证“Qwen 能发现新操作”，只证明了在这个提示和这四题上
它没有尝试。

### 5.2 是否修正了协同条件？

**没有。** ctrl_02 的 `{C,D}` 集合正确，但最终条件 `c == 0 or d == 0` 仍漏
`x < 6`，`case_0020` 仍是 `false_accept`；ctrl_03 的 `{B,E}` MMBS 集合正确，
但最终条件仍不 exact。两个 pilot 题的条件 exact 都是 0，0 个 VERIFIED。真实题
没有条件核验器，不能评价。

### 5.3 是否减少了错误关系？

**只有边缘减少，不能算改善。** 初始 10 个失败候选，最终 9 个；只删掉了
ctrl_02 的一个候选（3→2），ctrl_03 4→4，get_host 2→2，filestorage 1→1。
10 个初始失败候选中修正成功 0 个（0%）。同时没有增加任何新的正确关系。

### 5.4 相对 C0 是否有额外收益？

**没有可测量的额外收益。**

- 没有新操作、没有新确认集合；D 的 6 个确认集合都能在 C0 已确认集合中找到。
- pilot 上 D 的 0/6 VERIFIED 低于 C 的 2/14 和 Direct 的 2/8。
- 真实题 D 覆盖 C0 8 个唯一集合中的 6 个（漏 filestorage 的 2921 MSMS 和
  2924 MMBS 两个组合），没有超过 C0。
- 探针数与 C0 完全相同；token 成本约为 C 的 2 倍、Direct 的 3 倍。
- 唯一可辩护的表面改善是严格粒度：get_host 不再把 `if` 控制行当成可删除操作，
  因而没有 Direct Qwen 的 0/8 严格失败；但 C0 本来就没有这个问题。

### 5.5 这个机制值得保留吗？

**不作为核心机制保留。** 反馈基础设施（显式 MSMS/MMBS、AST 粒度、真实执行
证据、最多一次修正）可以作为诊断 harness 保留；但当前 Qwen 32B 在这四题上
不会利用反例完成最小集合或条件归纳，修正成功率为 0，且成本更高、没有新发现。
按本轮约束，到此停止，不扩大题目、不重跑 515 个目标、不新增 Benchmark。

如果要继续，最小可辩护的下一步不是再调 prompt，而是先修反馈协议：

1. 候选集合错误时也要生成条件级反例（当前 ctrl_02 在集合检查处提前返回，
   没有把 `case_0020` 给模型）；
2. 让模型显式输出“最小性理由/被排除的子集”，而不是只给一个集合；
3. 在真实题上提供可执行的条件语法子集，才能评价条件质量。

这些都属于下一轮，不属于本轮交付。

## 6. 产物与复现

代码：

- `scripts/run_semantic_feedback.py`
- `scripts/analyze_semantic_feedback.py`
- `tests/test_semantic_feedback.py`

运行产物：

- `runs/v3_semantic_feedback_v1/results.json`：完整逐题记录
- `runs/v3_semantic_feedback_v1/summary.json`：只读汇总指标
- `runs/v3_semantic_feedback_v1/tasks/<task>.json`：逐题候选、反馈、核验证据
- `runs/v3_semantic_feedback_v1/requests/<task>_{initial,correction}.json`：
  真实请求（含 messages、模型参数）
- `runs/v3_semantic_feedback_v1/raw/<task>_{initial,correction}.json`：
  原始响应
- `runs/v3_semantic_feedback_v1/gpu_evidence.json`：GPU / Ollama / token 证据
- `runs/v3_semantic_feedback_v1/tests.log`、`tests_full.log`：测试日志

复现实验（需要已启动的 Ollama 端点）：

```bash
python -u -m scripts.run_semantic_feedback \
  --endpoint http://127.0.0.1:11434 \
  --model qwen2.5-coder:32b \
  --num-ctx 8192 --num-predict 4096 \
  --tasks ctrl_02 ctrl_03 \
          werkzeug_get_host_default_empty \
          werkzeug_filestorage_stream_name \
  --out runs/v3_semantic_feedback_v1/results.json

python scripts/analyze_semantic_feedback.py
```

## 7. 泄漏与边界检查

- 请求 prompt 中没有 `HIDDEN`、`absorber_sets`、`coexisting_unmasking_sets`、
  `attribution.json`、`per_case` 等字段。
- 修正 prompt 中的 `case_00xx` 只来自模型自己候选的 Verifier 反馈，是真实执行
  证据，不是隐藏参考答案；`witness` 只出现在 Verifier 的拒绝理由字符串里。
- 真实题条件全部 `NOT_EVALUATED`，没有把模型假设计为正确关系。
- 没有修改 HIDDEN scorer、冻结 Benchmark、执行器语义、数据集专用工作目录。
- 本机 RTX 5060 未使用；云端 GPU 证据见 `gpu_evidence.json`。
