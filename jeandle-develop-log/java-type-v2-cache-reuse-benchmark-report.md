# V2 上下文复用补充测试报告

日期：2026-10-31。V2 提交：`ad38f632672c881708d0894acf56b72414c095f2`。

## 结论

V2 在稳定同 key 查询、可复用边事实及依赖区域外修改中有收益；同块无关修改和仅查询一次的 Final 建表仍有明显成本。结果支持“保留选择性失效，并按复用机会启用上下文缓存”，不支持笼统否定全部缓存，也不证明生产 JVM 一定获益。

## 实现与输入

服务器目录：`/home/annya/playground/jeandle/jeandle/benchmarks/v2-reuse-20261031`。

复用 `JavaTypeCacheReuseTestSupport.h` 中的 guard fixture，生成五份 `.ll`。每种模式实际解析对应 `.ll`，再由 native driver 控制查询与失效顺序。对象没有 java-klass 属性，必须通过 `check_instanceof(22,obj)` guard 得到类型，避免只测 Base 属性命中。

每批 32 次查询，批次开始清空 JavaType 缓存和 LVI：

- `same.ll`：固定 `(obj,path32)`，同 key 查询 32 次。
- `cross.ll`：16 个上下文依次访问两轮，用于观察上下文复用与第二轮 Final 命中。
- `cross-unique.ll`：32 个完全不同上下文各访问一次，单独观察边 Facts 复用，不混入 Final 热命中。
- `same-edit.ll`：固定查询上下文，每次后续查询前修改同一块中无关 add 的常量操作数。
- `other-edit.ll`：相同操作，但修改位于 guard 失败块、查询依赖区域之外。修改不改变 CFG。

修改顺序为通知旧 IR、清理 LVI、修改操作数、再次查询。DT 无需更新，因为仅改变 add 的常量操作数。

## 比较与正确性

- `cached`：默认 V2，StableOracleEpoch + 选择性失效。
- `nofinal`：同一 V2 求解器，关闭 Final；Base、Defined、Facts 保留。
- `full`：在发生修改时全清 V2，替代选择性通知。无修改场景与 cached 是等价控制组。
- `reference`：原始 `getJavaType` 无 JavaType 共享缓存，同样维护 LVI。它不是 V1 缓存基线。

每场景、每模式诊断 2 批，共 20 个配置、1280 次查询；逐次比较完整 JavaType 与全新 DT/AssumptionCache/LVI 下的原始查询，并验证 Klass=22。全部通过。计时关闭统计和差分重算，仅保留各模式相同的结果校验和。两组正式流程均生成 SUCCESS。

## 计时方法与边界

参考 `codex/null-edge-benchmark` 的方法，复用其 4000 次 bootstrap 区间函数；由于原脚本驱动 opt，另写 native runner 而不是伪装成 opt 测试。

CPU 8，SMT 兄弟 9，governor powersave；不修改系统设置。每场景单独 cached/cached A/A 标定；3 轮预热、31 轮正式配对，A/B 顺序随机、串行。95% 区间须整体越过该场景 A/A 绝对变化 P95 才判定。全部正式样本 native CPU 时间均 >=200ms。

**指标是归一化的每个 32-query 批次 CPU 成本，不是等大小 opt 输入的进程总时间。** 使用 native getrusage user+system，排除构造/解析 IR，包含批次缓存重置、查询、通知、修改和 LVI clear。各模式分别校准批次数，使样本约 360ms，再除以批次数比较。因此不能把下列百分比直接与原报告端到端 opt 的百分比相加或对照。

计时区间内重复使用同一个 fixture，批次间清空分析缓存；没有模拟每个函数重新分配 IR 的局部性。当前只覆盖一种深度和 guard 形状、简单模拟 VM 类型层次，不代表生产输入分布。初始生成器原型的中止数据位于服务器 results-generator-only-discarded，未纳入本报告。

## 主结果

下表均为 cached 相对相应基线的配对中位变化；负值表示 V2 更快。

| 场景 | 对原始无缓存查询 | 对同一 V2 关闭 Final | 对修改时全清 V2 |
|---|---:|---:|---:|
| 同 key、无修改 | -88.90%（improvement） | -81.35%（improvement） | +0.11%（inconclusive） |
| 16 上下文、访问两轮 | -48.72%（improvement） | -12.95%（improvement） | -0.11%（inconclusive） |
| 32 不同上下文、仅一轮 | -10.33%（improvement） | +51.25%（regression） | -0.69%（inconclusive） |
| 同块无关修改 | +59.54%（regression） | +36.16%（regression） | -1.76%（inconclusive） |
| 不同块无关修改 | -24.92%（improvement） | -36.28%（improvement） | -53.70%（improvement） |

## 诊断证据

以下为每场景 2 批、64 次查询的 cached 计数，独立于正式计时：

| 场景 | Final hits | Facts hits | oracle 回调次数 |
|---|---:|---:|---:|
| 同 key、无修改 | 62 | 0 | 68 |
| 16 上下文、访问两轮 | 32 | 2460 | 98 |
| 32 不同上下文、仅一轮 | 0 | 6076 | 130 |
| 同块无关修改 | 0 | 0 | 2176 |
| 不同块无关修改 | 62 | 0 | 2176 |

- 同 key 无修改：每批一冷、31 热，Final 命中行为符合设计。
- 唯一上下文：Final=0、Facts=6076。相比 reference 仍快约 10%，说明共享边事实有价值；但相比 nofinal 慢约 51%，说明为没有二次访问的 Final 收集依赖和建索引确实不划算。
- 同块修改：Final/Facts hits 均为 0；相比 reference 慢约 60%，相比 nofinal 慢约 36%。需要降低低复用路径上的维护成本。
- 不同块修改：Final 保留，每批 31 次命中；相比 full 快约 54%。但 oracle 回调数与 reference 一样多，因为每次通知后仍需重新验证记录的 null-edge 观察。命中不等于完全避免上下文工作。
- 无修改组 cached/full 无显著差异，符合二者没有执行不同失效操作的预期。

## 完整统计

| 场景 | 基线 → cached | 配对变化 | bootstrap 95% CI | A/A 噪声 P95 | 判定 |
|---|---|---:|---|---:|---|
| 同 key、无修改 | reference | -88.90% | [-88.97, -88.86] | 3.78% | improvement |
| 同 key、无修改 | nofinal | -81.35% | [-81.48, -81.29] | 3.78% | improvement |
| 同 key、无修改 | full | +0.11% | [-0.41, +0.77] | 3.78% | inconclusive |
| 16 上下文、访问两轮 | reference | -48.72% | [-49.14, -48.24] | 3.71% | improvement |
| 16 上下文、访问两轮 | nofinal | -12.95% | [-13.86, -12.42] | 3.71% | improvement |
| 16 上下文、访问两轮 | full | -0.11% | [-1.18, +0.69] | 3.71% | inconclusive |
| 同块无关修改 | reference | +59.54% | [+59.15, +60.15] | 3.00% | regression |
| 同块无关修改 | nofinal | +36.16% | [+35.51, +36.99] | 3.00% | regression |
| 同块无关修改 | full | -1.76% | [-2.21, -1.18] | 3.00% | inconclusive |
| 不同块无关修改 | reference | -24.92% | [-25.25, -24.62] | 2.58% | improvement |
| 不同块无关修改 | nofinal | -36.28% | [-36.48, -36.02] | 2.58% | improvement |
| 不同块无关修改 | full | -53.70% | [-54.11, -53.39] | 2.58% | improvement |
| 32 不同上下文、仅一轮 | reference | -10.33% | [-10.97, -9.18] | 2.50% | improvement |
| 32 不同上下文、仅一轮 | nofinal | +51.25% | [+50.35, +52.94] | 2.50% | regression |
| 32 不同上下文、仅一轮 | full | -0.69% | [-1.16, +0.41] | 2.50% | inconclusive |

## 复现与产物

服务器保留 driver.cpp、driver-unique.cpp、run.py、run-unique.py、五份 .ll、两个静态链接 replay 二进制和全部结果。生产源码工作区保持干净，未提交、推送或修改生产实现。

本机副本：`artifacts/v2-reuse-20261031/`，包含源码、输入、manifest、diagnostics、全部 samples.jsonl、summary 和 SUCCESS。二进制保留在服务器，SHA256 见各 manifest。

先按 README 构建原 driver，运行 `python3 run.py`；完成后再以相同编译参数构建 driver-unique.cpp 为 replay-unique，运行 `python3 run-unique.py`。两个结果目录必须尚不存在；重新测试请保留旧目录并改用新输出目录。不可在正式计时期间重新构建驱动或并行运行两套 runner。
