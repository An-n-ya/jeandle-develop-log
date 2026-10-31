# JavaType 四版本统一性能对比（含原始无缓存）

日期：2026-10-31。服务器：`annya@100.122.220.40`。本报告更新此前的三版本对比，十组全部重新进行四版本交错计时，未拼接不同实验的时间中位数。

## 版本定义

| 标识 | 实现 | 版本与设置 |
|---|---|---|
| raw | 原始无缓存 | 原版 V1 的 ac545bb21e8931152ad9149e01f8304b214dbd91；opt 开启 `-jeandle-disable-java-type-cache=true`；native 编译 `BENCH_REFERENCE`，直接调用该版本原始 getJavaType |
| base | 原版 V1 缓存 | 同一 ac545bb2，使用原有 CachedJavaType 共享缓存 |
| null | V1 + null-edge 优化 | codex/null-edge-benchmark，e5475bb0df4671302665c6986e762bf892c3c98a，默认配置，可选块级 LVI 保持关闭 |
| v2 | V2 默认缓存 | feat/javatype-selective-invalidation，ad38f632672c881708d0894acf56b72414c095f2 |

“无缓存”只关闭 JavaType 的跨查询缓存，不禁用正常 DT/LVI 分析；原始引擎的单次查询内部状态仍正常工作。它不是 V2 关闭 Final，也不是 V2 关闭全部缓存的消融。参考实现自身的版本差异应在解释结果时保留。

## 汇总表

时间为各版本中位成本，百分比为同轮配对变化的中位数。负值表示 V2 更快；百分比不能简单由表内两个中位数相除得到。† 表示未越过本次噪声门槛或时长要求，不能判定改善/回退。

| 场景 | 时间单位 | 原始无缓存 | 原版 V1 缓存 | V1 + null-edge | V2 | V2 对无缓存 | V2 对 null-edge |
|---|---|---:|---:|---:|---:|---:|---:|
| deep-static | ms / opt 进程 | 866.95 | 437.00 | 246.00 | 847.60 | -2.06%† | +244.88% |
| wide-static | ms / opt 进程 | 1722.24 | 1217.91 | 835.75 | 2066.28 | +20.17% | +146.86% |
| leaf-static | ms / opt 进程 | 388.44 | 376.48 | 320.58 | 487.23 | +25.62% | +51.83% |
| tce-cha | ms / opt 进程 | 892.24 | 438.50 | 248.58 | 874.96 | -1.95%† | +251.71% |
| virtual-cfg | ms / opt 进程 | 880.45 | 840.95 | 705.51 | 1131.86 | +28.46% | +60.55% |
| 同 key、无修改 | μs / 32 次查询批次 | 153.52 | 8.69 | 4.25 | 17.09 | -88.87% | +302.58% |
| 32 个不同上下文、仅一轮 | μs / 32 次查询批次 | 259.46 | 22.98 | 20.61 | 232.10 | -10.64% | +1028.01% |
| 16 个上下文、两轮 | μs / 32 次查询批次 | 202.21 | 15.81 | 12.13 | 103.56 | -48.70% | +752.31% |
| 同块无关修改 | μs / 32 次查询批次 | 285.74 | 13.52 | 8.82 | 460.47 | +61.95% | +5137.89% |
| 不同块无关修改 | μs / 32 次查询批次 | 287.10 | 13.54 | 8.76 | 217.40 | -24.38% | +2382.21% |

**前五行是完整 opt 进程 CPU 毫秒；后五行是每批 32 次查询的 CPU 微秒，排除 IR 构建/解析。两组不可混合求总平均或相加。** 生产 JVM 编译及 Java 运行性能不在本次测量范围内。

## 方法与正确性

- 复用原来五种 1024 函数 opt 输入、callback 与 Pass 管线；另外五份补充 .ll 使用相同 guard、查询与修改序列。
- native 每批重置 JavaType/LVI 缓存、固定 32 次查询，版本分别校准批次数来取得约 360ms 样本，比较归一化每批 CPU 成本。无缓存模式不维护 JavaType 缓存，但同样维护 LVI；计时不含差分验证。每版本每场景 2 批诊断，逐查询对照全新 DT/AC/LVI 的原始引擎，检查完整 JavaType，要求 class 22；V1 不允许跳过验证。
- opt 每个样本新建进程、重新解析原输入；正式计时关闭输出/统计/验证。各版本单独验证的 IR 与诊断 IR 一致，四版本最终优化 IR 逐字节一致。raw 的命令明确包含禁用缓存开关，诊断摘要中的 bypasses 必须大于零。
- CPU 8、SMT 兄弟 9，未修改 governor 或系统服务。每负载 3 轮预热 + 15 个 V1/V1 A/A 标定对，再做 3 轮预热 + 31 轮四版本随机交错计时，全部串行。
- bootstrap 95% CI 复用 benchmark 分支的 4000 次重采样函数；区间须整体越过该行 A/A 绝对变化 P95，且所有正式 CPU 样本 >=200ms，才给性能判定。
- 三个生产 worktree 不修改；独立驱动分别链接各版本的静态构建库。测试前后核对二进制 SHA256，结束后额外审计 native .ll 的跨版本字节一致性与无缓存命中计数。

## 所有配对比较

| 场景 | 比较 | 配对变化 | bootstrap 95% CI | A/A 门槛 | 判定 |
|---|---|---:|---|---:|---|
| deep-static | raw->base | -49.60% | [-49.65, -49.47] | 2.18% | improvement |
| deep-static | raw->null | -71.65% | [-71.78, -71.49] | 2.18% | improvement |
| deep-static | raw->v2 | -2.06% | [-2.38, -1.87] | 2.18% | inconclusive |
| deep-static | base->null | -43.93% | [-44.17, -43.58] | 2.18% | improvement |
| deep-static | base->v2 | +93.60% | [+92.94, +94.55] | 2.18% | regression |
| deep-static | null->v2 | +244.88% | [+243.05, +246.09] | 2.18% | regression |
| wide-static | raw->base | -29.26% | [-29.35, -29.15] | 1.79% | improvement |
| wide-static | raw->null | -51.34% | [-51.61, -51.27] | 1.79% | improvement |
| wide-static | raw->v2 | +20.17% | [+19.81, +20.49] | 1.79% | regression |
| wide-static | base->null | -31.30% | [-31.53, -31.13] | 1.79% | improvement |
| wide-static | base->v2 | +69.40% | [+68.95, +69.97] | 1.79% | regression |
| wide-static | null->v2 | +146.86% | [+146.40, +148.19] | 1.79% | regression |
| leaf-static | raw->base | -2.84% | [-3.67, -2.32] | 2.19% | improvement |
| leaf-static | raw->null | -17.43% | [-17.83, -17.23] | 2.19% | improvement |
| leaf-static | raw->v2 | +25.62% | [+25.25, +25.77] | 2.19% | regression |
| leaf-static | base->null | -14.86% | [-15.49, -14.38] | 2.19% | improvement |
| leaf-static | base->v2 | +29.42% | [+28.83, +29.77] | 2.19% | regression |
| leaf-static | null->v2 | +51.83% | [+51.20, +52.23] | 2.19% | regression |
| tce-cha | raw->base | -50.86% | [-51.08, -50.55] | 1.87% | improvement |
| tce-cha | raw->null | -72.13% | [-72.23, -72.06] | 1.87% | improvement |
| tce-cha | raw->v2 | -1.95% | [-2.18, -1.75] | 1.87% | inconclusive |
| tce-cha | base->null | -43.27% | [-43.63, -43.17] | 1.87% | improvement |
| tce-cha | base->v2 | +99.50% | [+98.87, +100.07] | 1.87% | regression |
| tce-cha | null->v2 | +251.71% | [+250.58, +253.06] | 1.87% | regression |
| virtual-cfg | raw->base | -4.50% | [-4.75, -4.20] | 2.46% | improvement |
| virtual-cfg | raw->null | -19.84% | [-20.10, -19.80] | 2.46% | improvement |
| virtual-cfg | raw->v2 | +28.46% | [+27.97, +28.73] | 2.46% | regression |
| virtual-cfg | base->null | -16.26% | [-16.46, -16.05] | 2.46% | improvement |
| virtual-cfg | base->v2 | +34.32% | [+33.74, +35.06] | 2.46% | regression |
| virtual-cfg | null->v2 | +60.55% | [+59.91, +61.26] | 2.46% | regression |
| 同 key、无修改 | raw->base | -94.37% | [-94.38, -94.35] | 1.96% | improvement |
| 同 key、无修改 | raw->null | -97.24% | [-97.26, -97.23] | 1.96% | improvement |
| 同 key、无修改 | raw->v2 | -88.87% | [-88.96, -88.82] | 1.96% | improvement |
| 同 key、无修改 | base->null | -51.37% | [-51.56, -51.05] | 1.96% | improvement |
| 同 key、无修改 | base->v2 | +96.99% | [+95.87, +97.41] | 1.96% | regression |
| 同 key、无修改 | null->v2 | +302.58% | [+298.70, +305.41] | 1.96% | regression |
| 32 个不同上下文、仅一轮 | raw->base | -91.17% | [-91.23, -91.11] | 2.09% | improvement |
| 32 个不同上下文、仅一轮 | raw->null | -92.03% | [-92.10, -91.99] | 2.09% | improvement |
| 32 个不同上下文、仅一轮 | raw->v2 | -10.64% | [-11.18, -10.25] | 2.09% | improvement |
| 32 个不同上下文、仅一轮 | base->null | -10.00% | [-10.93, -9.52] | 2.09% | improvement |
| 32 个不同上下文、仅一轮 | base->v2 | +910.05% | [+905.43, +916.33] | 2.09% | regression |
| 32 个不同上下文、仅一轮 | null->v2 | +1028.01% | [+1021.42, +1033.53] | 2.09% | regression |
| 16 个上下文、两轮 | raw->base | -92.20% | [-92.25, -92.12] | 2.96% | improvement |
| 16 个上下文、两轮 | raw->null | -94.02% | [-94.05, -93.98] | 2.96% | improvement |
| 16 个上下文、两轮 | raw->v2 | -48.70% | [-49.20, -48.32] | 2.96% | improvement |
| 16 个上下文、两轮 | base->null | -23.30% | [-23.70, -22.48] | 2.96% | improvement |
| 16 个上下文、两轮 | base->v2 | +558.24% | [+549.28, +562.45] | 2.96% | regression |
| 16 个上下文、两轮 | null->v2 | +752.31% | [+743.44, +765.37] | 2.96% | regression |
| 同块无关修改 | raw->base | -95.28% | [-95.30, -95.24] | 4.69% | improvement |
| 同块无关修改 | raw->null | -96.90% | [-96.94, -96.87] | 4.69% | improvement |
| 同块无关修改 | raw->v2 | +61.95% | [+60.93, +62.43] | 4.69% | regression |
| 同块无关修改 | base->null | -34.39% | [-35.53, -34.04] | 4.69% | improvement |
| 同块无关修改 | base->v2 | +3319.92% | [+3286.21, +3361.92] | 4.69% | regression |
| 同块无关修改 | null->v2 | +5137.89% | [+5089.63, +5198.50] | 4.69% | regression |
| 不同块无关修改 | raw->base | -95.31% | [-95.35, -95.26] | 6.50% | improvement |
| 不同块无关修改 | raw->null | -96.94% | [-96.99, -96.92] | 6.50% | improvement |
| 不同块无关修改 | raw->v2 | -24.38% | [-25.00, -23.85] | 6.50% | improvement |
| 不同块无关修改 | base->null | -35.16% | [-36.05, -34.16] | 6.50% | improvement |
| 不同块无关修改 | base->v2 | +1510.46% | [+1500.97, +1518.20] | 6.50% | regression |
| 不同块无关修改 | null->v2 | +2382.21% | [+2347.53, +2404.67] | 6.50% | regression |

## 诊断命中行为

每场景、每版本 64 次诊断查询（两批），均不计入正式样本。

| 场景 | 版本 | Final hits | Facts hits | 外层 oracle 回调次数 |
|---|---|---:|---:|---:|
| 同 key、无修改 | raw | 0 | 0 | 2176 |
| 同 key、无修改 | base | 62 | 0 | 68 |
| 同 key、无修改 | null | 62 | 0 | 0 |
| 同 key、无修改 | v2 | 62 | 0 | 68 |
| 32 个不同上下文、仅一轮 | raw | 0 | 0 | 3168 |
| 32 个不同上下文、仅一轮 | base | 0 | 62 | 130 |
| 32 个不同上下文、仅一轮 | null | 0 | 62 | 0 |
| 32 个不同上下文、仅一轮 | v2 | 0 | 6076 | 130 |
| 16 个上下文、两轮 | raw | 0 | 0 | 2656 |
| 16 个上下文、两轮 | base | 32 | 30 | 98 |
| 16 个上下文、两轮 | null | 32 | 30 | 0 |
| 16 个上下文、两轮 | v2 | 32 | 2460 | 98 |
| 同块无关修改 | raw | 0 | 0 | 2176 |
| 同块无关修改 | base | 62 | 0 | 68 |
| 同块无关修改 | null | 62 | 0 | 0 |
| 同块无关修改 | v2 | 0 | 0 | 2176 |
| 不同块无关修改 | raw | 0 | 0 | 2176 |
| 不同块无关修改 | base | 62 | 0 | 68 |
| 不同块无关修改 | null | 62 | 0 | 0 |
| 不同块无关修改 | v2 | 62 | 0 | 2176 |

Facts hits 的定义在旧版与 V2 不同：旧版保存完成的 `(Value,Block)` 路径结果，V2 保存 guard/null 边事实；不能按命中数大小直接排名。Final 命中后 V2 仍可能重验证 null-edge 观察。旧 null-edge 优化的预过滤可避免这些合成输入中的 oracle 回调。

解释时应分别回答两件事：缓存是否比原始无缓存更快，以及 V2 是否优于旧缓存。V2 对无缓存有收益，并不意味着它超过 V1 或旧 null-edge 优化。旧版本还存在已知的其他精度/正确性测试问题，单凭本表不能无条件恢复所有旧语义。

## 产物与复现

服务器目录：`/home/annya/playground/jeandle/jeandle/benchmarks/four-way-cache-20261031`。

执行 `python3 build.py`、`python3 run.py`，输出目录须为新目录。详见该目录 README。保留四个 replay 二进制、统一源代码、fixture、五份补充 .ll、验证/诊断 IR 与 stderr、原始采样、manifest、summary、audit 及 SUCCESS。不得在计时中重建二进制。

本机副本：`artifacts/four-way-cache-20261031/`，保存源码、输入、所有统计样本和审计。较大的 opt 输出 IR/stderr 保留在服务器 results/。之前三版本实验的完整数据保留在 `artifacts/null-v2-comparison-20261031/`；未覆盖或删除。

审计：1540 个正式 A/A/比较样本，最短 CPU 239.59 ms；所有流程完成标记和门禁通过。
