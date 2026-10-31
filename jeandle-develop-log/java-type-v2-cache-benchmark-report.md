# JavaType V2 缓存层性能评估报告

**评估对象**：`feat/javatype-selective-invalidation` 分支（新的 getJavaType 缓存层 V2）
**评估目标**：使用 `codex/null-edge-benchmark` 的测试流程，判断新缓存层是否带来性能收益
**生成时间**：2026-10-30

---

## 1. 结论摘要

> **没有性能收益。五个合成 workload 全部判定为显著回退（regression），CPU 时间上升 29% ~ 99%，置信区间远超噪声门槛。**

- 与基线 `codex/null-edge-baseline` 相比，V2 缓存层在全部 5 个 workload 上更慢，且差异极大（最小 29%、最大 99%）。
- 回退完全来自 JavaType 查询机制本身：查询时间为基线的 1.7~2.9 倍，失效（invalidation）时间为基线的 4.7~8.2 倍。
- 主要原因：这些 workload 在每次查询之间都有 IR 修改，V2 的 **Facts / Final 缓存命中数为 0**，但仍需为每次查询维护这些表（插入后立即被失效）。Base 缓存命中很好（最高 211 万次），但不足以抵消其余开销。
- 补充隔离实验表明：**selective invalidation 机制本身是有效的**（V2 内部，相对全清最多加速 ~19%），但收益远不足以弥补 V2 框架整体的开销。

---

## 2. 测试配置

### 2.1 分支与二进制

| 角色 | 分支 | 提交 | 二进制 |
|---|---|---|---|
| A（基线） | `codex/null-edge-baseline` | `ac545bb21e89` | `/home/annya/playground/jeandle/jeandle/jeandle-llvm-null-edge-baseline/build/bin/opt` |
| B（新代码） | `feat/javatype-selective-invalidation` | `ad38f632672c` | `/home/annya/playground/jeandle/jeandle/jeandle-llvm/build/build-ninja-release/bin/opt` |

两个构建均为 `Release`、`LLVM_ENABLE_ASSERTIONS=OFF`、`X86`，编译器 `/home/annya/playground/jeandle/jeandle/tools/bin/gcc`。

### 2.2 测量方法（来自 `codex/null-edge-benchmark` 的 `benchmark.py`）

- 固定 CPU 8（SMT 兄弟 CPU 9），脚本设置单核 affinity
- 逐文件配对交错（A/B 顺序每轮随机），串行执行
- 31 轮正式配对 + 3 轮预热
- 指标：进程 CPU 时间（`getrusage` user+system）与墙钟时间
- 噪声门槛：来自同会话的 A/A 标定，取逐轮绝对百分比差异的 P95
- 判定规则：配对变化中位数 bootstrap 95% 区间整体越过噪声门槛才判定 improvement/regression，否则 inconclusive
- 样本时长门槛：每臂进程 CPU 时间 ≥ 200ms（全部满足）
- 正确性门禁：两臂输出 IR 逐字节一致；诊断 phase 跑 stats+verify，计时 phase 仅 `-disable-output`

### 2.3 输入

`/tmp/null-edge-workloads-20261030/cases.json`，五个 workload，每 1024 个独立函数，从原始输入重新构建 IR 和分析状态。

| workload | 每函数调用点数 | select 深度 |
|---|---:|---:|
| deep-static | 16 | 64 |
| wide-static | 64 | 16 |
| leaf-static | 32 | 0 |
| tce-cha | 16 | 64 |
| virtual-cfg | 32 | 0 |

> 已知边界：这五个合成输入经预过滤后 oracle 调用为零；本次结果衡量的是缓存机制开销，生产 JVM 语料结论可能不同。

---

## 3. 正确性检查（先决条件，全部通过）

| 检查项 | 结果 |
|---|---|
| 单测 `JavaTypeQueryTests` | 83 个中 82 通过；唯一失败 `CachedEntryNormalizesFreeze` 与基线完全相同（新增 `CachedJavaTypeV2Test` 全部通过） |
| Jeandle lit 测试 | 807 个全部通过（基线有 9 个已知失败，新代码反而全部修复） |
| A/B IR 一致性 | 两臂输出 IR 逐字节一致 |

---

## 4. 主 A/B 结果：基线 → V2 新缓存层

负值表示 B（V2）更快。**全部判定为 regression。**

### 4.1 CPU 时间（进程 CPU，主指标）

| workload | A 基线 (ms) | B V2 (ms) | 配对变化 | 95% 区间 | 噪声门槛 | 判定 |
|---|---:|---:|---:|---|---:|---|
| deep-static | 437.4 | 850.8 | +94.4% | [94.0, 95.3] | 4.77% | regression |
| tce-cha | 437.7 | 869.3 | +98.9% | [97.9, 99.6] | 4.02% | regression |
| wide-static | 1221.3 | 2074.2 | +69.8% | [68.9, 70.5] | 1.89% | regression |
| virtual-cfg | 842.9 | 1135.7 | +34.6% | [34.1, 35.8] | 3.42% | regression |
| leaf-static | 378.4 | 489.6 | +29.2% | [28.6, 29.6] | 2.76% | regression |

### 4.2 墙钟时间

| workload | A (ms) | B (ms) | 变化 | 判定 |
|---|---:|---:|---:|---|
| deep-static | 438.8 | 853.5 | +94.6% | regression |
| tce-cha | 439.8 | 872.9 | +98.8% | regression |
| wide-static | 1224.8 | 2081.4 | +69.7% | regression |
| virtual-cfg | 845.9 | 1139.0 | +34.7% | regression |
| leaf-static | 379.8 | 492.0 | +29.1% | regression |

wall 与 cpu 结论一致。回退幅度是噪声门槛的 7 ~ 25 倍，结论稳健。

---

## 5. 归因分析（诊断计数器）

诊断阶段开启 stats，对比两臂的 `total query time` 与 `total invalidation time`：

| workload | 基线 query (ms) | V2 query (ms) | 倍数 | 基线 invalidation (ms) | V2 invalidation (ms) | 倍数 |
|---|---:|---:|---:|---:|---:|---:|
| deep-static | 212 | 608 | 2.9x | 4.2 | 34.5 | 8.2x |
| tce-cha | 212 | 613 | 2.9x | 4.3 | 34.9 | 8.0x |
| wide-static | 644 | 1416 | 2.2x | 19.1 | 132.3 | 6.9x |
| leaf-static | 116 | 207 | 1.8x | 7.8 | 36.6 | 4.7x |
| virtual-cfg | 357 | 600 | 1.7x | 11.3 | 62.0 | 5.5x |

以 deep-static 为例，V2 端到端 CPU 时间从 437ms 升至 851ms，**其中 query time 增量（212→608ms）就解释了绝大部分回退**。

### 关键观察

- Base 缓存命中良好（deep-static：2,112,512 hits / 1,024 misses），说明 V2 的 Base 选择性失效工作正常。
- **Facts / Final 缓存命中为 0**：deep-static 插入 245,760 条 edge-facts、16,384 条 final，但全部在复用前被失效（每次查询之间有 IR 修改，Facts/Final 表被整体清空）。
- V2 将 Facts 拆成 root guard 与 null-edge 两张表，使每查询插入量翻倍，进一步放大了“建表即失效”的开销。

---

## 6. 补充实验：V2 内部 selective vs 全清失效

同一 V2 二进制，A 加 `-jeandle-java-type-force-full-invalidation=true`，B 为默认（selective）。用于判断 selective invalidation 机制本身是否有效。

| workload | A 全清 (ms) | B selective (ms) | 变化 | 95% 区间 | 判定 |
|---|---:|---:|---:|---|---|
| deep-static | 1044.2 | 851.2 | **-18.7%** | [-19.1, -18.4] | improvement |
| tce-cha | 1085.3 | 876.9 | **-19.2%** | [-19.3, -18.9] | improvement |
| wide-static | 2237.9 | 2072.8 | **-7.5%** | [-7.9, -7.3] | improvement |
| leaf-static | 487.9 | 489.7 | +0.5% | [-0.1, 0.7] | inconclusive |
| virtual-cfg | 1140.2 | 1134.8 | -0.3% | [-0.8, -0.2] | inconclusive |

**结论**：selective invalidation 在 V2 内部确实有效（deep-static / tce-cha 约 -19%，wide-static 约 -7.5%），但该收益被 V2 框架相对 V1 基线的整体开销吞没，最终对基线仍为大幅回退。

---

## 7. 边界与说明

- 结论基于 `codex/null-edge-benchmark` 的五个合成 workload（1024 函数 / 输入，预过滤后 oracle 调用为零）；这衡量的是 JavaType 缓存机制的开销，不代表生产 JVM 语料的整体编译性能。
- 新代码在 lit 层面没有新增失败；唯一已知单测失败与基线一致。
- 测量在共享机器上进行，governor 为 powersave，未修改系统设置；A/A 标定已捕获本机噪声。

---

## 8. 产物

所有实验均生成 `SUCCESS` 标记，原始数据可复现：

| 实验 | 目录 | 内容 |
|---|---|---|
| A/A 标定（feat 二进制自比） | `/tmp/null-edge-aa-feat/` | manifest / samples / summary（噪声门槛来源） |
| 主 A/B（基线 → V2） | `/tmp/null-edge-ab-selective/` | manifest / samples / summary / 两臂诊断 IR 与 stderr |
| V2 隔离实验（全清 → selective） | `/tmp/null-edge-ab-v2iso/` | manifest / samples / summary / 两臂诊断 IR 与 stderr |

二进制 SHA256（来自主 A/B manifest）：

- 基线 `opt`：`9178f7ecec31eb734f573d2e0144b908e5525f700673c9623672ac0e091db86f`
- V2 `opt`：`c6687f37c47b538e0f2c3e5b1378d6480e5cef28a608d946252aa2e79de56182`
