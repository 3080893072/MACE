# 现有实验冻结记录（2026-11-02）

本文件只做冻结登记，不重跑、不覆盖、不删除任何开发 fixture、真实源码题、资格记录、测试协议或原始日志。

## 1. 保留的资产

| 类别 | 位置 | 状态 |
|---|---|---|
| 开发控制题与 private attribution | `benchmark_pilot/tasks.json`、`benchmark_pilot/attribution.json`、`fixtures/` | 原样保留 |
| 三个真实源码题 | `benchmark_real_pilot/tasks/`、`benchmark_real_pilot/specs.py` | 原样保留 |
| 真实题结果与资格 | `benchmark_real_pilot/results/`、`benchmark_real_pilot/qualification/out/` | 原样保留 |
| 测试协议 v2 | `benchmark_real_pilot/protocol_v2/` | 原样保留；只新增分类登记 |
| M1–M6 / 开放式接口历史 | `docs/M1_report.md` … `docs/M6_decision.md`、`benchmark_open_v1/` | 原样保留 |
| 旧 open-discovery 基线 | `open_ops/` | 原样保留；本轮在其上新增最小机制 |

新增的登记文件是
`benchmark_real_pilot/protocol_v2/real_case_classification.json`。它引用现有证据，不改变任何证据。

## 2. 真实案例的两种研究用途

### TEST_SURVIVING_DELETION

判据：声明的完整适用项目测试在 P− 下仍全部通过。

| 题 | T_task | T_project P− | 结论 |
|---|---|---|---|
| `real_click_truncate_visible` | 1 passed | 1562 passed, 94 skipped, 1 xfailed | 第一类 |

这一类的证据上限：

- T_task 只有 1 条原始测试，不是广泛覆盖；
- A 的局部效果是绑定覆盖型，删除后暴露为 `UnboundLocalError`；
- “存活”来自项目套件，不是从 T_task 外推。

### VERIFIED_MASKING_ONLY

判据：掩盖关系本身有执行验证，但不满足第一类的项目测试存活条件。

| 题 | T_task P− | T_project P− | 为什么不是第一类 |
|---|---|---|---|
| `real_werkzeug_headerset_update` | 1 failed, 2 passed | 1 failed, 815 passed | 项目套件检测到删除 |
| `real_werkzeug_url_unparse` | 6 failed, 12 passed | collection error, 0 run；`PROJECT_SUITE_NOT_FULLY_RUN=true` | 项目套件检测到删除，且未完整运行 |

第二类不能写成第一类。它们可以支持“掩盖关系存在且可执行验证”，不能支持“原项目测试漏掉了危险删除”。

## 3. 本轮不动的边界

- 不减少 T_task 测试；
- 不新增真实 Benchmark 题；
- 不修改 M1–M6 历史结果或历史日志；
- 不把 `VERIFIED_MASKING_ONLY` 改名为 `TEST_SURVIVING_DELETION`；
- 不因后续发现结果重写上面的分类。
