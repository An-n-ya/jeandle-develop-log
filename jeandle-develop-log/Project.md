#  类型分析结果缓存

## 背景

Jeandle 是基于 OpenJDK 与 LLVM 的 JVM JIT 编译器，包含一组面向 Java 的优化 pass。编译期 Java 类型信息是 TypeCheckElimination、Devirtualization 等优化的关键输入，它以 attribute 与 metadata 形式编码在 LLVM IR 中，并由 getJavaType 接口统一查询。

查询分两层:
- 基础查询(context-insensitive)：从 load指令、参数、调用返回上的 attribute 与 metadata 读出已知类型，并经由Select、PHI等指令传播;
- 上下文敏感锐化(context-sensitive sharpening)：从查询点沿支配树(DominatorTree)向上遍历，追踪子类型检查的分支条件，利用当前程序点生效的类型断言收窄类型。

## 现有问题  

每次调用都从零重新计算，没有任何缓存。每一次 getJavaType 调用会重新遍历 IR、沿支配树向上重走分支条件图、并重新向 VM 发起十余次回调(IsSubtype、GetCommonSuperKlass、IsEffectivelyFinal 等)。同一值可能在多个上下文下被反复查询——于是相同的类型分析在整个编译过程中被一遍遍重算。这是 JIT 编译热路径上的重复 CPU 开销，也阻碍了更多 pass 复用该类型查询。

## 项目目标

为上述 Java 类型分析引入一个可复用、参与 PassManager 生命周期管理的缓存层，并整合进 LLVM AnalysisManager。
复用结果：同一查询在缓存命中时以 O(1) 返回，不再重走 IR、重发 VM 回调;
接入 AnalysisManager：作为受托管的分析结果参与 new PassManager 的分析与失效生命周期：一次计算、跨 pass/跨轮复用、IR 变更时由框架按既定纪律失效;
迁移现有调用：现有 getJavaType 的直接调用点切换为经分析结果缓存查询。
正确性验证：通过现有 Jeandle 编译器测试，包括 jeandle-llvm 和 jeandle-jdk 两个仓库的全部测试。设计针对类型分析缓存的 LLVM 侧 lit 测试，保证无正确性问题。
性能验证：通过 LLVM 的编译速度测试工具对类型分析缓存的实质收益进行评估，要求显著降低 Jeandle 编译器在类型分析接口上的耗时，显著降低类型相关优化 Pass 的耗时。通过 cache hit 和 cache miss 统计信息量化类型分析缓存带来的性能贡献。

## 项目产出要求
1. 为 Java 类型分析引入一个可复用、参与 PassManager 生命周期管理的缓存层，并整合进 LLVM AnalysisManager
1.1. 复用结果：同一查询在缓存命中时以 O(1) 返回，不再重走 IR、重发 VM 回调;
1.2. 接入 AnalysisManager：作为受托管分析结果参与 new-PM 的分析与失效生命周期：一次计算、跨 pass/跨轮复用、IR 变更时由框架按既定纪律失效;
1.3. 迁移现有调用：现有 getJavaType 的直接调用点切换为经分析结果缓存查询。
1.4. 正确性验证：通过现有 Jeandle 编译器测试，包括 jeandle-llvm 和 jeandle-jdk 两个仓库的全部测试。设计针对类型分析缓存的 LLVM 侧 lit 测试，保证无正确性问题。
1.5. 性能验证：通过 LLVM 的编译速度测试工具对类型分析缓存的实质收益进行评估，要求显著降低 Jeandle 编译器在类型分析接口上的耗时，显著降低类型相关优化 Pass 上的耗时。通过 cache hit 和 cache miss 统计信息量化类型分析缓存带来的性能贡献。