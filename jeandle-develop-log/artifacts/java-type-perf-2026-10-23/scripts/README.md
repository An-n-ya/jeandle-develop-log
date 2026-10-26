# 本轮执行与分析脚本

这些脚本用于 2026-10-23 的冻结 profiling run。服务器大数据目录、四模式开关及输入哈希见报告和 manifest.json。

## 脚本身份

- `../frozen-runner/`：仓库中实际冻结的原始 runner，内容哈希与 manifest 一致；其已知 RSS/runtime 字段问题由外置分析修正，没有修改冻结源码。冻结 runner 的初版 report 阶段未用作本报告数据源，请用下列分析脚本重算。
- `record-script-only.py`：L1 原始 perf.data + 完整内联栈导出；模式顺序固定，报告明确列为偏差。
- `profile-l2.py`：CFF 基线/stat/record。三种 phase 各为独立进程；profile 原生栈使用 --no-inline，完整 DWARF 原始数据仍保留。流式 SHA-256 与原哈希算法内容结果相同。
- `queue-l2.py`：确保 L1 完成后才启动 L2。
- `rss-launch.py`：小内存父进程 wait4，取得 opt 子进程 user/system/RSS/切换数。
- `final-diagnostics.py`：L2 完成后的软件事件/RSS 补测、频率/栈深抽查、annotate、结束身份核验。
- `quality-more.py`：再做 virtual/wide 长栈抽查，为全部 perf.data 生成 native self 与事件统计，并补全 ledger。
- `capture-source.py`：与热点有关的有限源码片段及源文件哈希。

外置 helper 在结果目录演进以修正采集问题，实际 opt 参数和每轮原始 stderr/JSON 均保留；不能把修改后的 helper 当作所有早期 phase 的相同脚本身份。测量的源码、二进制与每组输入始终保持冻结，已在结束时复核。

## 本地重算

先将 `../run-records.tar.gz` 解压到新的临时目录，例如 `/tmp/javatype-raw`，不要覆盖服务器原始 run。

```sh
python3 analyze-perf.py --run /tmp/javatype-raw --out ../analysis
python3 analyze-perf.py --run /tmp/javatype-raw/l2 --out ../l2-analysis
python3 attribute-stacks.py --run /tmp/javatype-raw --symbols ../opt-symbols.gz --out ../attribution
python3 check-attribution.py ../attribution
python3 summarize-quality.py --run /tmp/javatype-raw --artifact ..
python3 report-data.py --artifact ..
python3 flamegraph.py ../attribution/deep-static-s1.folded ../deep-static-s1-flamegraph.svg
python3 build-report.py --artifact .. --output /tmp/JavaType-Perf-Report.md
```

`attribution.csv` 是排他分组，百分比之和为 100%。`profile-runs.csv` 与 quality-summary.json 中 inclusive 视图有重叠，不能相加。重算脚本按 opt + cpu_atom/cycles/u 限定分母，使用 event period 权重，以冻结 opt 原生符号表修补所属函数，匹配时排除形参类型。

`native-stats.txt` 是原始事件计数；`native-self.txt` 是独立的 perf self 报告。perf report 的 --stats 只打印事件统计，不能把它当 self 表。主 runner 原始 JSON 的 enabled_pct 也是历史命名错误，保存的是 runtime 数值，不是百分比。

软件事件在当前 perf 权限下仍实际报告为 :u。零 context-switches/migrations 不能用于证明无调度；本轮切换数与 RSS 取自 wait4。原始 L1 RSS 受到父进程大文件哈希高水位污染，已在报告中排除。

火焰图生成器版本：javatype-flamegraph-1。源码、数据与生成器哈希记录在 artifact-sha256.json。
