# benchmark_real_v3 — 真实开源项目操作删除与掩盖关系试点

本目录只做题目构造与资格判定，不运行 MACE/Qwen，不修改 M1–M6 历史结果。

## 1. 固定项目

| id | 项目 | 版本 | 源码 | 测试 | Python / pytest | 测试范围 |
|---|---|---|---|---|---|---|
| click-8.4.1 | click | 8.4.1 | `src/` | `tests/` | `D:/Anaconda3/python.exe`, 7.4.0 | 项目自带配置 dselect 30000 条 stress 测试；94 skipped、1 xfailed |
| jinja2-3.1.3 | Jinja2 | 3.1.3 | `src/` | `tests/` | `D:/Anaconda3/python.exe`, 7.4.0 | 无协议级排除 |
| werkzeug-2.2.3 | Werkzeug | 2.2.3 | `src/` | `tests/` | `<local-path>`, 7.2.0 | 协议排除 24 条 `dev_server` 测试（本机无法起本地 dev server）；不声称未过滤套件全部通过 |

项目树位于 `<local-path>/`，只读使用；所有实验在 `<local-path>/` 的副本中进行。

## 2. 复现流程

```bash
cd <local-path>
python -m benchmark_real_v3.run_all scan      # AST 候选 -> candidates/candidates_static.json
python -m benchmark_real_v3.run_all trace     # P+ 全套件 + 逐测试行覆盖
python -m benchmark_real_v3.run_all screen    # 删除筛选漏斗
python -m benchmark_real_v3.run_all verify    # 每个题目的启用/禁用矩阵
python -m benchmark_real_v3.run_all report    # 汇总候选、题目、可行性数字
```

单步也可以直接运行对应模块。所有子进程使用固定的项目解释器，并通过
`PYTHONPATH` 指向变体副本的 `src/`，不会从控制器进程导入被测包。

## 3. 筛选漏斗

1. AST 提取：同一函数内、同名局部变量的多次单行赋值；A 为较早赋值，B 为后续赋值。
2. 保留 A 在 P+ 全套件逐测试覆盖中至少被一条原测试执行过的候选。
3. 在 P-（A 行替换为等缩进 `pass`）上运行这些命中测试；任何失败即 `TARGETED_TEST_DETECTS_DELETION`。
4. 对仍通过的候选运行项目适用全套件；失败即 `PROJECT_SUITE_DETECTS_DELETION`，通过才记为
   `TEST_SURVIVING_DELETION`。

`pass` 替换保持行号不变，是单语句删除变异，不是其他类型的变异算子。

## 4. 版本化说明（必须与结果一起阅读）

第一轮筛选使用了一个把嵌套函数赋值同时记到外层函数的扫描器（852 行 / 815 个不同 id），
并且审查预算 160、targeted 子预算 140 未被代码强制。该轮全部日志保留在
`evidence/superseded_scanning_round1/`，**不作为最终结果**。

修正后：

* 扫描器只把赋值记给最内层函数，得到 799 个不同候选；
* 其中 403 个同时具有 P+ 覆盖与“先读后写 / 后续写读取 A”的静态形状；
* 本轮对 403 个全部审查（预算即全体），因此不存在按 P- 结果挑选候选；
* 完整套件 P- 运行上限 60 次。

## 5. 题目资格

每题必须同时具备：

1. A 在真实源码中可定位；
2. P- 下原项目适用套件通过（日志见 `evidence/`）；
3. A 被至少一条原测试执行（T_task 只由 P+ 覆盖选出）；
4. 存在合法 witness 使 P+ 与 P- 可观察结果不同；
5. 在至少一个执行 A 的掩盖 witness 上，存在执行确认的操作级掩盖关系；
6. 版本、测试范围、环境、双版本结果可复现。

题目目录：`tasks/<task_id>/spec.json`；矩阵结果：`evidence/<task_id>_matrix.json`。

矩阵对声明的候选全集 U 枚举全部子集，因此 MSMS/MMBS 的最小性检查在 U 内是穷尽的；
结论不覆盖 U 之外的语句，也不覆盖未执行的自然语言“全部合法输入”。

## 6. 本轮产出（2026-11-02）

* 799 个去重静态候选 → 403 个合格候选全部审查 → 374 个被原测试抓住 → 29 个全套件存活。
* 29 个存活候选逐条判定：5 个 `QUALIFIED`、8 个无暴露输入、16 个未建立操作级掩盖
  （其中 1 个是 MSMS-only 补充案例）。
* 5 个合格题目：

| task_id | 项目 | 机制 | T_task |
|---|---|---|---:|
| `jinja2_bytecode_cache_read` | Jinja2 | 共存备份路径 | 1 |
| `werkzeug_filestorage_stream_name` | Werkzeug | 条件覆盖 | 10 |
| `werkzeug_bind_server_name_lower` | Werkzeug | 跨函数再推导 + 控制前置条件 | 8 |
| `werkzeug_get_host_default_empty` | Werkzeug | 两条互斥替代覆盖路径 | 118 |
| `werkzeug_secure_filename_ascii_filter` | Werkzeug | 下游规范化吸收 | 1 |

逐候选理由见 `evidence/qualification_registry.json`；完整可行性报告与六个问题的回答见
`docs/MACE_benchmark_v3_feasibility.md`。

## 7. v3 验收、评分与冻结（2026-11-02）

```bash
cd <local-path>

# 独立验收（自建复制/删除/probe/子集枚举/pytest，不复用 verify_task）
python -m benchmark_real_v3.acceptance_v3

# 补充：冻结 T_task 是否真的执行 A（sys.settrace）
python -m benchmark_real_v3.acceptance_t_task_trace

# 评分器回归测试
python -m unittest discover -s benchmark_real_v3/scoring/tests -v

# 无模型端到端评分演示
python -m benchmark_real_v3.scoring.demo

# 构建公开/隐藏发布包与 SHA-256
python -m benchmark_real_v3.release_build

# 公开包泄漏检查
python -m benchmark_real_v3.leak_check --check-only
```

- 公开包：`release/PUBLIC/`（14 个文件）
- 隐藏包：`release/HIDDEN/`（41 个文件）
- 发布版本：`v3.0-dev-pilot-2026-11-02`，标签 `DEVELOPMENT/PILOT`
- bundle SHA-256：`470f32fa7efd9a2db4e5ee203b4a374db93da4c907876c923f09dd07b49b80d3`
- 完整验收报告与六个问题的回答：`docs/MACE_benchmark_v3_acceptance.md`

评分器重新执行 P+/P− 与 U 的子集枚举，不信任提交的期望状态；当 A
未被执行时，MSMS/MMBS 不得通过。所有结论只在声明的有限输入和 U 内成立，
没有 `PROVEN`，也没有全合法域声明。
