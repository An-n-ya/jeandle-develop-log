# NullEdge 优化收益重新量化（2026-10-30）

结论：五种合成输入的端到端 CPU 耗时下降 **14.69%～43.64%**，均超过预先标定的噪声门槛。八个仓库 null-edge 用例的放大版本变化为 **−7.91%～+2.77%**，没有一项越过门槛，因此尚不能确认这些形状上的端到端收益或回退。查询内部诊断中也存在变慢的形状，不能将“oracle 调用归零”的合成结果外推到所有输入。

本次比较的是编译成本，不是生成程序的运行速度。性能结论来自关闭统计/校验/IR 输出的 opt 端到端 CPU 时间；墙钟时间作为辅助。查询内部墙钟时间另以统计模式重复诊断，不能当作无插桩的生产耗时。

基线为 `ac545bb21e8931152ad9149e01f8304b214dbd91`，由优化前 `b121fa56710a` 回填非 NullEdge 的 pass-local 钩子、分析失效和诊断调整得到；优化侧为 `e5475bb0df4671302665c6986e762bf892c3c98a`。两侧独立 Release / -O3 / assertions OFF / X86 / GCC 16.1.1 构建。基线原本没有 oracle 内部计时，优化侧在 stats 关闭时不计时。

不使用 E0（恒 false oracle）作为基线：它会改变 oracle 的答案和部分优化结果。比较中块级 LVI 开关保持默认关闭，预算保持默认 128，pass-local ablation 关闭。

固定 CPU 8，SMT 兄弟 CPU 9；共享机器，未修改全局 governor。正式计时不与构建或其他本任务测试并行。每种输入分别对基线和优化版本做 15 轮 A/A，取两侧逐轮绝对差异 P95 的较大值作为噪声门槛；之后进行 31 轮随机交错 A/B，预热 3 轮。负变化表示优化后更快；报告的是配对变化的中位数和 bootstrap 95% 区间，不能由两列独立中位数完全还原。

全部正式样本要求进程 CPU 时间不少于 200ms；进程退出、缺统计、缓存校验失败、输出 IR 不一致都会使该用例停止，不填零或继续当作成功。A/B 置信区间须完全超过 A/A 噪声门槛才认定改善/回退。

合成输入保留每个函数的结构，均复制成 1024 个独立函数。额外用例来自旧报告确实触达 oracle 的 11 个仓库用例；它们是测试用例的放大版本，不能称为生产 JVM 编译输入。


## 无统计插桩的端到端结果


### 五种合成输入

| 输入 | 基线 CPU ms | 优化 CPU ms | 配对 CPU 变化 | 95% 区间 | A/A 门槛 | 结论 |
|---|---:|---:|---:|---|---:|---|
| deep-static | 437.1 | 246.7 | -43.64% | [-43.81%, -43.35%] | 9.00% | 确认改善 |
| wide-static | 1218.6 | 837.8 | -31.24% | [-31.51%, -31.17%] | 3.18% | 确认改善 |
| leaf-static | 377.1 | 321.1 | -14.69% | [-14.95%, -14.54%] | 12.95% | 确认改善 |
| tce-cha | 439.2 | 248.7 | -43.32% | [-43.47%, -43.22%] | 8.43% | 确认改善 |
| virtual-cfg | 840.2 | 703.2 | -16.10% | [-16.32%, -15.94%] | 6.94% | 确认改善 |

墙钟变化：deep-static -43.63%（确认改善）；wide-static -31.23%（确认改善）；leaf-static -14.79%（确认改善）；tce-cha -43.32%（确认改善）；virtual-cfg -16.10%（确认改善）。


### 八个 null-edge 用例的放大版本

| 输入 | 基线 CPU ms | 优化 CPU ms | 配对 CPU 变化 | 95% 区间 | A/A 门槛 | 结论 |
|---|---:|---:|---:|---|---:|---|
| recover-null-arm-vacuous | 409.5 | 406.4 | -0.78% | [-1.32%, -0.02%] | 2.14% | 无法确认差异 |
| checkcast-expanded-phi | 431.0 | 434.6 | +0.89% | [+0.54%, +1.07%] | 7.81% | 无法确认差异 |
| frozen-null-edge | 423.3 | 413.2 | -2.34% | [-2.71%, -2.02%] | 8.06% | 无法确认差异 |
| null-both-edges | 308.6 | 316.2 | +2.77% | [+1.78%, +2.96%] | 6.25% | 无法确认差异 |
| null-threaded-edge | 387.3 | 356.2 | -7.91% | [-8.27%, -7.26%] | 10.49% | 无法确认差异 |
| checkcast-dissolved | 457.4 | 423.8 | -7.27% | [-7.66%, -6.64%] | 8.69% | 无法确认差异 |
| recover-osr-checkcast-edge | 365.8 | 354.3 | -3.25% | [-3.57%, -2.87%] | 10.08% | 无法确认差异 |
| method-handle-link-to-virtual | 400.4 | 405.2 | +1.48% | [+1.10%, +2.02%] | 7.95% | 无法确认差异 |

墙钟变化：recover-null-arm-vacuous -0.80%（无法确认差异）；checkcast-expanded-phi +0.85%（无法确认差异）；frozen-null-edge -2.30%（无法确认差异）；null-both-edges +2.80%（无法确认差异）；null-threaded-edge -7.89%（无法确认差异）；checkcast-dissolved -7.26%（无法确认差异）；recover-osr-checkcast-edge -3.28%（无法确认差异）；method-handle-link-to-virtual +1.43%（无法确认差异）。


## 查询内部成本：单独诊断

这部分开启统计，以 15 轮交错重复测量。计时器为查询内部 steady_clock；没有混入 reference 重算。基线没有 oracle 细粒度计时，优化侧在诊断时有，因此这组结果用于解释路径成本，不能替代上面的无统计插桩进程 CPU 收益。下表为每个完整模块内所有顶层查询的累计时间。

| 输入 | 基线查询 ms | 优化查询 ms | 配对查询时间变化 | 95% 区间 | 优化侧 oracle calls |
|---|---:|---:|---:|---|---:|
| deep-static | 210.08 | 33.61 | -83.97% | [-84.04%, -83.91%] | 0 |
| wide-static | 642.18 | 312.39 | -51.39% | [-51.55%, -51.12%] | 0 |
| leaf-static | 115.08 | 74.02 | -35.66% | [-36.16%, -35.14%] | 0 |
| tce-cha | 210.06 | 34.05 | -83.85% | [-83.86%, -83.70%] | 0 |
| virtual-cfg | 352.76 | 257.58 | -26.81% | [-27.08%, -26.63%] | 0 |
| recover-null-arm-vacuous | 28.68 | 34.20 | +19.03% | [+18.23%, +19.85%] | 16384 |
| checkcast-expanded-phi | 105.46 | 114.63 | +9.93% | [+7.69%, +10.58%] | 32768 |
| frozen-null-edge | 111.33 | 107.60 | -2.88% | [-3.99%, -2.49%] | 16384 |
| null-both-edges | 62.03 | 66.73 | +8.27% | [+7.76%, +8.82%] | 32768 |
| null-threaded-edge | 99.89 | 82.16 | -18.52% | [-18.75%, -17.42%] | 16384 |
| checkcast-dissolved | 120.92 | 103.54 | -14.93% | [-15.67%, -13.78%] | 40960 |
| recover-osr-checkcast-edge | 34.19 | 29.68 | -13.11% | [-13.37%, -12.83%] | 40960 |
| method-handle-link-to-virtual | 47.66 | 51.35 | +7.73% | [+6.65%, +9.38%] | 12288 |

所有诊断中优化侧的 oracle 预算耗尽计数均为 0。五种合成输入的优化侧 oracle 调用均为 0；基线未添加 oracle 计数插桩，当前对照不提供基线 oracle 调用次数。


## 覆盖、排除与输入验证

11 个原始 oracle 用例先做原始规模的输出及 cached/reference 检查：

| 用例 | 输出一致 | 基线差分验证 | 优化侧差分验证 | 处理 |
|---|---|---|---|---|
| recover-null-arm-vacuous | 是 | 通过 | 通过 | 8192 份独立函数 |
| checkcast-expanded-phi | 是 | 通过 | 通过 | 16384 份独立函数 |
| frozen-null-edge | 是 | 通过 | 通过 | 8192 份独立函数 |
| null-arm-type | 是 | 失败 | 失败 | 排除性能对照，保留行为记录 |
| null-both-edges | 是 | 通过 | 通过 | 16384 份独立函数 |
| null-guard-forms | 否 | 失败 | 通过 | 排除性能对照，保留行为记录 |
| null-threaded-edge | 是 | 通过 | 通过 | 16384 份独立函数 |
| checkcast-dissolved | 是 | 通过 | 通过 | 20480 份独立函数 |
| condition-value-domain | 是 | 失败 | 失败 | 排除性能对照，保留行为记录 |
| recover-osr-checkcast-edge | 是 | 通过 | 通过 | 20480 份独立函数 |
| method-handle-link-to-virtual | 是 | 通过 | 通过 | 12288 份独立函数 |

`null-guard-forms` 的精度一致性修复仍然存在；它的输出变化是行为收益，未混入等价输出的性能表。`null-arm-type`、`condition-value-domain` 两侧都有既有差分失败，未把它们当作正确性已验证的性能样本。


放大输入保留原函数体、模块常量、属性和 metadata，新增不同名称的函数定义；每个函数有独立的 JavaType/LVI 分析生命周期。另检查优化侧原始输入的 queries、oracle calls、structural hits、true answers、prefilter hits、预算耗尽数，必须乘以复制倍数后与放大输入计数一致，见 amplification-checks.json。


基线单测为 46/47，仍只有 CachedEntryNormalizesFreeze 失败；优化版本先前验证为 47/48，新增预算测试通过。本次两侧测量输入均通过 IR 验证及 cached/reference 检查，优化前后输出逐字一致。


## 可复现产物与限制

产物位于 `artifacts/null-edge-requantification-2026-10-30/`：versions.json 绑定版本、编译配置与二进制 SHA256；各 aa/ab 目录含 manifest、逐轮 samples.jsonl、summary 和日志；*-queries 含诊断原始计数；baseline-controls.patch 记录基线控制改动；scripts/ 保存生成、审计、测试和收集脚本。SUCCESS 只表示流程完成，不代表每项均有显著收益。


测试机完整 IR 和诊断日志保存在 `/tmp/null-edge-requant-results`，输入在 `/tmp/null-edge-workloads-20261030` 与 `/tmp/null-edge-requant-inputs`。使用现有 benchmark.py，通过 --a/--b 指向两侧 opt、--calibration 指向本组 calibration.json 即可重跑；完整命令已逐轮写入 manifest/samples 和 run-suite.py。原始 11 个用例列表及其计时入选结果见 corpus-audit.json；生成时使用了旧 oraclefocus.py 的文件列表。scripts/amplify.py 已固化相同列表，消除对临时历史脚本的依赖。


这些结果量化的是五种合成结构与八种单元测试形状上的编译成本。没有提供真实 JVM 编译录制输入，本次不据此给出生产整体提速率或 Java 程序执行速度。也没有将整体改动的收益进一步分摊到 S1/S2/S3/S4/S5。共享机器仍有尾部波动，接近门槛的结果应在独占机器上复核。
