# 关于 `comparison_summary.json` 的说明

本目录下的 `comparison_summary.json`、`task_01_direct_qwen.json`、`task_01_full_mace.json`、
`task_01_pure_symbolic.json`、以及 `../logs/methods.log` 是**恢复本地模型之前的 provider 探针**：

* 该探针只检查 Ollama 端点、`DASHSCOPE_API_KEY` 和 `mace.program.build_pair`；
* 它没有调用本地 `transformers` 模型；
* 因此其中 `direct_qwen.status = BLOCKED`、`answered_methods = 0` 只描述那次探针，不是本轮基线结果。

本轮实际执行的 Direct Qwen 与三方法对照在：

* `../executability/task_01_direct_qwen_v2_raw.json`（主提交的原始回答）
* `../executability/task_01_direct_qwen_v2_scored.json`（评分）
* `../executability/task_01_direct_qwen_v2_summary.json`（摘要）
* `../executability/controlled_comparison.json`（ctrl_01/02/03 的三方法对照）

完整说明见 `../../docs/MACE_executability_and_baseline.md`。

旧探针文件保留原样，不用于本轮“Direct Qwen 是否跑通”的判断，也不把它的 0 个回答写成模型 0% 正确率。
