# MACE Benchmark V4 Dataset

本目录是 MACE Benchmark 数据集建设的**唯一交付目录**。V3 冻结包与
`benchmark_real_v4` 的探索性产物只读引用，不在此目录之外新增交付。

## 目录

```
PROTOCOL.md                     验收协议、定义、DEV/HELDOUT 规则、计数口径
split/
  projects.json                 V4-DEV 与 V4-HELDOUT 项目清单
  seal.json                     HELDOUT 封存哈希（开封前不得运行）
registry/
  candidates.json               全部候选及 V4 状态（由只读审计生成）
  existing_v4_audit.json        探索性 v4 资产的汇总审计
  accepted.json                 已验收题目（当前为空）
tasks/                          验收后的题目包
evidence/
  qualification/                数据集本地的筛选/资格证据
acceptance/                     独立验收脚本
stats/
  dataset_stats.json            严格分口径的统计
results/                        Broad Discovery 轮清单与统计
discovery/                      Broad Discovery 池（71 个新增项目）
  manifest/                     项目清单、PyPI 元数据、HELDOUT_BROAD 封存
  sdists/                       70 个 sdist（SHA-256 已逐位校验）
  stage0/                       Stage 0 项目/测试可用性
  stage1/                       Stage 1 AST 候选
  stage2_3/                     Stage 2/3 动态验证、检查点与逐项目排除项
  evidence/                     每个进入 Stage 3 的候选的独立证据目录
  stage3_5/                     同函数同 RHS 重算结构排名
  stage4/                       Stage 4 探针脚本与判定记录
tools/
  audit_existing_v4.py          只读审计探索性 v4 资产
  run_qualification.py          复用现有资格工具，但写入本目录
  broad_manifest.py             项目清单、封存、下载与校验
  stage0_stage1.py              Stage 0/1
  stage23_run.py                Stage 2/3
  stage35_rank.py               同函数同 RHS 重算结构排名
  stage4_probe.py               删除/子集枚举/观察等价探针
  build_inventory.py            生成 results/ 清单与统计
  build_stats.py                从实际产物重建 stats/dataset_stats.json
  export_evidence.py            导出逐候选证据目录
docs/
  MACE_v4_dataset_phase1.md     Phase 1 报告
  MACE_v4_broad_dataset_mining.md  Broad Discovery 轮报告
  MACE_v4_source_registry.md    数据源登记表
```

## 当前状态

- V4 已验收题目：**1**（`tabulate_numparses_header_wrap`，DEV，
  `FULL_MASKING_STORY`，单元素 MSMS；AC1–AC12 独立验收通过）
- 协同掩盖确认题：**0**
- V4-DEV 项目：5 个既有 + 58 个 Broad Discovery 项目
- V4-HELDOUT：8 个既有（封存）+ 12 个 HELDOUT_BROAD（封存），均未开封
- 探索性 v4 的 5 个 release candidate：**0 个满足 V4 协议**
- Broad Discovery：15,902 个 AST 候选；12 个项目完成动态筛选；33 个
  `TEST_SURVIVING_DELETION` 候选全部有 Stage 4 判定：1 个升为正式题，
  7 个 `REJECT_NO_EXPOSING_INPUT`，25 个 `REJECT_NO_MASKING_RELATION`
- 候选选择对同一文件设上限（`--max-per-file`，默认 3），只改变预算分配，
  不改变任何验收条件；`exclusions.json` 的 `__ignore__` 记录收集期即失败的
  可选依赖（`--deselect` 对收集错误无效）

## 规则

1. 先读 `PROTOCOL.md`，任何状态提升都必须附证据路径。
2. 不修改 V3 冻结包、不修改 MACE 算法/Graph/Qwen 接口。
3. HELDOUT 在 `split/seal.json` 的 `unsealed` 为空前不得运行或阅读源码。
4. 统计必须区分题目数、原测试数、输入数、操作关系数。
