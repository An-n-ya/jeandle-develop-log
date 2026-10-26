# LVI Argument-condition 实验记录

- `final/`：最终 Argument 快速路径，提交 `599e47ee8b8096695f6c723202573a5c12899520`。
- `eager-proposal/`：未保留的提前提取约束方案及其复杂条件回退证据。
- 主回放只采用 `final/timings-six-rounds.json` 和 `final/summary-six-rounds.json`，round 0–5，共 72 次运行。`selection.json` 记录用户指定的收口规则。
- `final/timings.json`、`summary.json`、`validation.log` 保留终止前观察到的全部记录，包括第六轮之后的数据；不用于最终六轮表。
- 四组压力测试已在收口前完成，各 10 轮，见 `stress-*`。
- `run-validation.py` 为实际执行时的脚本，原计划 10 轮，后由用户要求停止。重新跑六轮时应将轮数改为 6，并使用新的结果目录，避免覆盖记录。
- `run-profile.py` 和 `analyze-profile.py` 是准备的脚本；最终版本未执行采样，不存在最终版采样结果。
- 大型二进制和生成的压力输入保留在服务器；本地输入脚本与身份哈希用于复核和重建。
