# JavaType 缓存设计测试执行报告

日期：2026-10-23。对应计划：
`JavaType-Cache-Design-Test-Plan-2026-10-23.md`。

## 执行身份

- 服务器：`annya@100.122.220.40`
- 仓库：`/home/annya/playground/jeandle/jeandle/jeandle-llvm`
- 分支：`test/javatype-cache-design`
- 基线提交：`357604c7724e49eace6fbfa42e4f671b12b5ff98`
- 源码状态：测试实现仍为未提交的 tracked/untracked 工作区改动，未 push。
- 两个正式 session 使用的完整 source patch SHA-256：
  `2bb2df22cdba3f8a483fa3f57abb31890a6551c0b068269f683ddafd8ba906be`
- 正式 session 的 `opt` SHA-256：
  `88b6b699d048802ec4421034aa868d8b8446161c999dd75ca821da91d1eb3ed9`
- 两个 session 的 HEAD、source patch、worktree 状态和二进制哈希完全一致。

完整 patch 与汇总保存在本目录：

- `artifacts/java-type-cache-2026-10-23/session1/source.patch`
- `artifacts/java-type-cache-2026-10-23/session1/manifest.json`
- `artifacts/java-type-cache-2026-10-23/session1/summary.json`
- `artifacts/java-type-cache-2026-10-23/session2/source.patch`
- `artifacts/java-type-cache-2026-10-23/session2/manifest.json`
- `artifacts/java-type-cache-2026-10-23/session2/summary.json`

## 已实现

### S0/S1 失效策略

- S0 保留全表扫描基线。
- S1 在非 CFG 修改中按 `Affected` 集合逐个删除 Base key；CFG 修改继续扫描 Base 表，并保留上下文无关的 Argument、Call、Load 叶子。
- 新增 `-jeandle-java-type-force-base-scan-invalidation`，允许同一二进制在 S0/S1 间做 A/B。
- 失效统计现在分别记录：
  - 访问的不同 Value 数；
  - 访问的 SSA use 边数；
  - Base/PathFacts/FinalTypes 扫描槽位；
  - 三层实际删除数；
  - full-clear 回退。

### 修改通知

- CFF 对没有普通 SSA 用户、但已经进入缓存的 narrow-oop load，在修改或删除前发出失效通知。
- 选择性失效会沿旧 use graph 遍历，不假设每个中间 Value 都存在缓存条目。

### 微基准

新增 `llvm/benchmarks/JeandleJavaTypeCacheInvalidation.cpp`：

- P1 SparseBaseEdit：S0/S1、N=64/1K/16K、A=1/8/64。
- P2 ContextFanout：C=1/4/16/64。
- P3 BatchOverlap：B=1/8/32/128、重叠率 0/50/90%、合并/分别通知。
- P4 ContextReset：Q=0/1/8/64。
- P5 HistoryAndChurn：高水位 0/4096、循环 100/1K/10K。

P1-P3 在 benchmark 内用复制前后 cache size 校验删除数，禁止陈旧目标文件或统计字段错位产生伪数据。

### 完整流水线脚本

扩展 `llvm/utils/jeandle/benchmark-java-type-cache-design.py`：

- 默认模式改为 S0、S1、FULL、REF。
- S0 使用强制 Base scan，S1 使用当前逐 key 删除。
- 正确性诊断与正式计时分开。
- 诊断模式比较输出 IR，并要求预期 CHA 变换数量。
- 正式模式关闭 stats、verification 和 logging，随机排列配对模式。
- 输出中位数、绝对时间、相对 FULL 的变化和 bootstrap 95% 区间。
- `manifest.json` 和 `source.patch` 现在同时记录 tracked diff 与 untracked 新文件正文/哈希。

## 正确性验证

`JavaTypeQueryTests`：44/44 通过。

本轮新增或强化的计划条目：

- C06 `CacheHoleInUseGraphIsTraversedBeforeMutation`
- C10 `GuardOperandChangeInvalidatesNonKeyDependencies`，增加全新 FAM/LVI 的独立参考
- C15 `InvalidateBeforeDeletionPreventsKeyReuse` 和 FAM 地址复用边界
- C17 `PhiWarmupOrderHonorsFiniteClassModel`
- C18 `InvalidationJustBelowValueLimitDoesNotClear`
- C18 `InvalidationUseThresholdUsesInclusiveBoundary`
- C21 `RepeatedTypeFactMutationRoundTripsThroughAValue`
- C22 `JavaTypeResultPreserveAndReuseBoundary`

FAM 测试观察到被删除的 analysis result 地址可以被新 result 立即复用。因此生命周期正确性不能依赖对象地址不同；当前实现通过“删除前从缓存移除 key”保证安全。如果未来改成 EntryID、epoch 或延迟删除，必须另加 generation/version 校验。

相关 lit 回归：96/96 通过。

- `java-type-analysis`
- `type-check-elimination`
- `cha-devirtualization`
- `constant-field-folding`
- `java-type-metadata-recovery`
- `repeated-constant-field-folding`

`git diff --check` 和脚本 `py_compile` 均通过。

## 正式配对实验

每个 session 的条件：

- 5 个合成场景；
- 每次 8 个函数；
- 3 个 warmup；
- 30 个随机顺序的配对轮次；
- S0/S1/FULL/REF 使用相同输入、pass 和 callback model；
- 所有模式先产生相同优化 IR，再进入计时。

结构性结果非常稳定：

| 场景 | S0 base slots scanned | S1 base slots scanned |
| --- | ---: | ---: |
| deep-static | 16,896 | 0 |
| wide-static | 18,432 | 0 |
| leaf-static | 512 | 0 |
| tce-cha | 17,424 | 0 |
| virtual-cfg | 256 | 256 |

该表说明 S1 完全消除了非 CFG 场景的 Base 全表扫描；CFG 场景仍按设计扫描。S0/S1 的 `ValuesVisited` 和三层删除数一致，选择性只改变了查找方式。

进程墙钟时间在两个 session 中波动明显。下表中的单元格格式为
`median ms（相对 FULL 的降低比例 [95% bootstrap 区间]）`；正数表示比
FULL 快，负数表示比 FULL 慢。FULL 是每个 session 的参考模式。

Session 1：

| 场景 | S0 | S1 | FULL | ORIGIN |
| --- | --- | --- | ---: | --- |
| deep-static | 27.102（+16.44% [-5.15, +34.03]） | 23.595（+27.26% [-1.99, +41.25]） | 32.435 | 32.243（+0.59% [-16.58, +19.89]） |
| wide-static | 27.196（-0.66% [-42.52, +33.62]） | 30.428（-12.62% [-78.30, +28.34]） | 27.017 | 42.348（-56.74% [-129.09, +13.85]） |
| leaf-static | 28.448（-16.21% [-73.77, +18.75]） | 26.143（-6.79% [-64.64, +21.37]） | 24.481 | 24.686（-0.84% [-46.58, +22.34]） |
| tce-cha | 27.957（+5.04% [-45.29, +30.10]） | 26.025（+11.60% [-32.02, +24.45]） | 29.440 | 26.285（+10.72% [-41.18, +25.47]） |
| virtual-cfg | 31.780（-29.43% [-71.73, +20.66]） | 25.072（-2.11% [-44.08, +33.87]） | 24.554 | 26.998（-9.96% [-59.43, +29.28]） |

Session 2：

| 场景 | S0 | S1 | FULL | ORIGIN |
| --- | --- | --- | ---: | --- |
| deep-static | 21.196（+33.39% [+12.34, +48.32]） | 27.371（+13.99% [-12.26, +47.81]） | 31.822 | 29.686（+6.71% [-19.02, +27.73]） |
| wide-static | 26.289（+9.60% [-16.94, +37.06]） | 28.117（+3.32% [-31.50, +33.83]） | 29.082 | 23.860（+17.96% [-87.41, +41.14]） |
| leaf-static | 26.138（-7.98% [-35.39, +13.91]） | 20.529（+15.19% [-20.39, +33.32]） | 24.207 | 25.784（-6.52% [-44.73, +29.23]） |
| tce-cha | 16.484（+37.55% [-2.13, +53.02]） | 26.158（+0.90% [-65.76, +30.24]） | 26.396 | 27.282（-3.36% [-64.64, +41.20]） |
| virtual-cfg | 21.860（+14.70% [-26.42, +50.60]） | 24.292（+5.21% [-24.46, +47.51]） | 25.626 | 27.677（-8.01% [-52.77, +42.04]） |

Session 2 的 deep-static/S0 区间 `[+12.34, +48.32]` 没有跨零，但相同
场景在 Session 1 的区间跨零，S1 在两个 session 中也都跨零，因此这项
结果没有跨 session 复现。其余模式相对 FULL 的区间均跨零。当前数据不能
支持“端到端编译已获得稳定收益”，也不足以支持为了性能立即替换
DenseMap。

## 设计判断

当前证据支持保留 S1：

- 实现直接复用现有 `DenseMap`；
- 非 CFG 修改的复杂度从扫描 N 变为按 A 个 key 删除；
- 语义边界与 S0 一致；
- 额外内存为零；
- CFG 修改仍可用保守扫描处理。

暂时不建议进入 S2/S3/S4：

- P2 结构性上下文数量可控，但尚无真实 workload 证明两级索引收益；
- P3 表明合并通知能明显减少重复 Value/use 遍历，下一步应优先考虑在 pass 内合并同一修改窗口，而不是先换容器；
- 墙钟区间跨零，说明当前合成流水线主要成本可能不在 Base 删除；
- EntryID/反向依赖图只有在真实运行中 `A << N`、SSA 图大但缓存覆盖低、修改频繁时才有充分理由。

## 尚未完成

- P6-P8 和 P1-P5 的长时正式微基准尚未执行；本轮微基准只做 smoke。
- 尚无来自真实 JVM/Jeandle 编译样本的分层 workload。
- S2/S3/S4 尚未实现，当前数据不支持先做。
- 受限随机 Query-Mutate-Query 生成器和完整 pre-pea-high-tier replay 仍是下一阶段工作。
- 测试分支未 commit、未 push。
