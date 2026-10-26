#!/usr/bin/env python3
"""Assemble the Chinese execution report from measured artifacts."""
import argparse,csv,json,statistics
from collections import defaultdict,Counter
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();a=args.artifact
    q=json.loads((a/'quality-summary.json').read_text())
    manifest=json.loads((a/'manifest.json').read_text())
    post=json.loads((a/'identity-post.json').read_text())
    assert manifest['identity']==post, 'source/binary identity changed'
    assert q['native_stats_profiles']==77, q['native_stats_profiles']
    assert len(q['quality_checks'])==5
    assert len(q['scheduling'])==24 and all(r['repeats']==3 for r in q['scheduling'])
    profiles=json.loads((a/'attribution/summary.json').read_text())
    assert len(profiles['profiles'])==72
    assert all(r['runs']==3 for r in profiles['summary'])
    by={(r['case'],r['mode']):r for r in profiles['summary']}
    baseline=json.loads((a/'analysis/baseline-summary.json').read_text())
    l2baseline=json.loads((a/'l2-analysis/baseline-summary.json').read_text())
    times={**baseline['metrics'],**l2baseline['metrics']}
    source_identity=manifest['identity']
    tables=(a/'report-tables.md').read_text().splitlines()
    out=[]
    def add(text):out.append(text.strip()+'\n')
    def table(headers,rows):
        add('| '+' | '.join(headers)+' |\n| '+' | '.join('---' for h in headers)+' |\n'+
            '\n'.join('| '+' | '.join(map(str,row))+' |' for row in rows))
    def measured(prefix):
        index=next(i for i,line in enumerate(tables) if line.startswith(prefix))+1
        while index<len(tables) and not tables[index].startswith('|'):index+=1
        rows=[]
        while index<len(tables) and tables[index].startswith('|'):
            rows.append(tables[index]);index+=1
        add('\n'.join(rows))
    link='artifacts/java-type-perf-2026-10-23'
    add('''# JavaType 缓存 perf 性能诊断执行报告

日期：2026-10-23。执行依据：[JavaType-Perf-Profiling-Plan-2026-10-23.md](JavaType-Perf-Profiling-Plan-2026-10-23.md)。

状态：已完成 L1 五场景、一个 L2 CFF 回放的四模式基线、事件计数和调用栈采样，并完成调度/RSS 补测与频率/长栈抽查。源码、输入和二进制身份在测量结束后复核一致。质量限制与未覆盖项保留在本报告中。

## 1. 结论与适用范围

当前 S1 已减少重复的基础类型计算；这批回放中的下一处主要成本是上下文事实查询，尤其是 LVI，而非 Base 表删除。deep-static、tce-cha 的诊断性 CPU 数据显示 S1 比 ORIGIN 低约 13%；leaf-static、virtual-cfg 则略高。原先短进程实验无法区分收益，不能据此认定缓存没有作用。

S1 的失效入口在主采样中约占整进程 cycles 的 0.6%–1.7%，样本量不足以细排其中的 erase、集合操作与析构。继续替换失效数据结构，当前可见收益空间较小。优先实验应针对 LVI 的重复子问题，以及修改后分析结果的保留契约。

以上结论限于本轮 LLVM 回放。L1 是 CHA 或 TCE→CHA 合成输入，L2 是从现有 lit fixture 克隆的 CFF 单 pass 回放；没有把它们视作完整 Jeandle pipeline 或真实 JVM 编译。每个缓存仍是函数级缓存，独立函数放大没有把单个 Base 表扩为 8192 倍。deep 的单函数 Base 规模约 66，wide 约 18；本轮不覆盖超大单函数缓存。

所有时间差均为一个 session、10 个随机配对轮次的诊断数据。没有执行两个 session × 30 轮的正式速度验收，故不作生产编译性能承诺。

## 2. 身份、环境与正确性
''')
    add(f'''- 主机：`annya@100.122.220.40`；仓库：`{manifest['source']['root']}`。
- 分支：`test/javatype-cache-design`；HEAD：`{source_identity['head']}`。
- 完整 tracked + untracked source patch SHA-256：`{source_identity['source_patch_sha256']}`。
- profiling opt SHA-256：`{source_identity['opt_sha256']}`。
- opt build-id：`376a5dc08ddadd66005d07a52358796599405b56`。
- 原有未提交改动完整保留；没有 commit、push、reset 或 clean。

profiling build 沿用原 Release 的 GCC 15、`-O3 -DNDEBUG`、X86-only、无 LTO/RTTI/EH，增加 `-g`。四模式来自同一二进制。配置差异见 [配置对比]({link}/build/configuration-comparison.json)，完整配置与构建日志见 [build-records.tar.gz]({link}/build-records.tar.gz)。

固定 CPU 16，为 atom PMU 对应的核，没有 SMT sibling；governor 为 powersave。服务器为 Linux 7.1.3，`perf_event_paranoid=2`。未修改 sysctl、capability、governor 或整机频率设置。硬件计数仅使用 `cpu_atom/*`；`cpu_core/*` 的 0% running 行已排除。有效硬件事件的 pcnt-running 最低为 99%，没有低于 90% 的有效记录。

JavaTypeQueryTests **44/44**、六组相关 lit **96/96** 通过。首次 lit 因 profiling build 缺 llvm-config/llvm-readobj 失败，补齐后重跑通过，失败日志仍保留。小输入诊断中四模式输出 IR 哈希一致，预期优化调用点数量全部满足，缓存校验 skip 为 0。诊断启用的重算和计数未混入正式计时或采样。

证据：[单测]({link}/build/JavaTypeQueryTests.log)、[lit]({link}/build/Jeandle-JavaType-lit.log)、[首次失败]({link}/build/Jeandle-JavaType-lit.failed-missing-tools.log)、[manifest]({link}/manifest.json)、[source.patch]({link}/source.patch)、[结束时身份]({link}/identity-post.json)。''')
    add('''## 3. 策略、输入与测量口径

| 模式 | 开关 | 解释 |
| --- | --- | --- |
| ORIGIN | `-jeandle-disable-java-type-cache` | 原始查询引擎 |
| FULL | `-jeandle-java-type-force-full-invalidation` | 缓存引擎，每次通知全清 |
| S0 | `-jeandle-java-type-force-base-scan-invalidation` | 选择性失效，Base 扫描 |
| S1 | 无上述开关 | 选择性失效，Base 逐 key 删除 |

ORIGIN/FULL 涉及不同查询引擎，不能将其全部差异归为容器开销。S0/S1 才隔离 Base 删除方式。所有性能运行关闭 stats、verification 和 debug logging，保留必需的 VM callback 回放。

| 输入 | 独立函数数 | 每函数形状/消费者 |
| --- | ---: | --- |
| deep-static | 8192 | 64 层 select，16 个 CHA 位置 |
| wide-static | 8192 | 16 层 select，64 个 CHA 位置 |
| leaf-static | 8192 | 叶子，32 个 CHA 位置 |
| tce-cha | 8192 | 64 层 select，TCE→CHA |
| virtual-cfg | 8192 | 叶子，32 个 virtual/CFG 改写位置 |
| cff-cache-reuse | 262144 | 原 cache-reuse fixture 克隆，6 次 JavaType 查询/函数 |

deep/S1 的放大 pilot 用户态 CPU：512/2048/4096/8192 函数分别约为 0.354/1.428/2.855/5.730 秒。保持单函数形状和预算不变，没有通过加深 DAG 放大。

基线：每模式预热 3 次，再做 10 个随机配对轮次；stat：每组 3 次；主 profile：每 case/mode 3 份。record 使用 `cycles:u`、199 Hz、DWARF 8192 bytes。性能运行串行，不与构建或其他 benchmark 并发。L1 profile 的实际模式顺序固定，为本轮与计划随机 profile 顺序的偏差；无采样基线和 L2 profile 使用固定 seed 随机排列。未将固定顺序 profile 的 elapsed 用于速度排名。

所有占比使用 event period 权重。排他分类每样本只计一次，分组和为 100%；inclusive 按样本栈是否包含入口判断，递归帧不重复计权。父子 inclusive 不可相加。JavaType 视图包含查询、失效和分析结果回收；LVI 子树是其子集。容器/分配共享函数依调用栈归属，不将所有 DenseMap、malloc/free 都算给三层缓存。''')
    add('## 4. 无采样基线与硬件计数\n\n下表为中位数，单元格为 **user 秒 / wall 秒**。')
    measured('无采样中位数')
    add('配对中位差 **S1 − 对照**，单位秒；负数表示 S1 用户态 CPU 更少。区间、每轮原始值及 system CPU 见附件 JSON/CSV。这是诊断比较。')
    pairs={**baseline['paired_s1_user_delta_s'],**l2baseline['paired_s1_user_delta_s']}
    cases=['deep-static','wide-static','leaf-static','tce-cha','virtual-cfg','cff-cache-reuse']
    table(['场景','S1−ORIGIN','S1−FULL','S1−S0'],[
        [case]+[f"{pairs[case+':s1_minus_'+mode]['delta_s']['median']:+.4f}" for mode in ['origin','full','s0']]
        for case in cases])
    add('硬件事件每组 3 次，下表为 **十亿 cycles / IPC / branch miss %**。IPC 来自同一次运行的 instructions/cycles；branch miss % 为 misses/branches，分母不是 instructions。完整 instructions 和原始 runtime 字段保留在 stat 附件。')
    measured('硬件事件')
    add('deep 的 ORIGIN/S1 IPC 都约 2.40，cycles 随工作量下降；这些数据支持减少重复计算的解释，不能据此宣称改善了硬件 cache miss。generic cache-misses 未被用来解释 JavaType 缓存命中。')
    add('## 5. 调用栈归因\n\n### 5.1 整进程与 JavaType 子树\n\n每格为 **JavaType inclusive % / 其中 LVI inclusive 占整进程 %**，取三份 profile 的中位数。后者并非以 JavaType 为分母。')
    measured('采样中位数')
    add('失效入口 inclusive 占整进程 cycles 的中位数如下。多个格子累计不足 100 个失效样本，只用于判断量级，不细排 erase、worklist 或析构。ORIGIN 的空缓存通知也可能产生少量调用开销，零样本不代表数学上的零成本。')
    measured('失效 inclusive')
    add('S1 的排他分组如下，三份 profile 合并计算。与前表的“每份百分比中位数”不同，数值会略有差异。其余/未细分包括查询剩余部分、其他 pass 工作、模块回收和无法确定的操作；没有将它们强归为缓存成本。')
    measured('S1 排他分组')
    add('''### 5.2 查询为何仍然昂贵

主要调用链：

```text
CHA::tryNarrowJavaObjType
  → JavaTypeAnalysisResult::getJavaType
  → getCachedJavaType → factsAt → isNullEdge
  → LVINullEdgeOracle::operator()
  → LazyValueInfo::getPredicateOnEdge / getValueOnEdge
  → solve → solveBlockValueSelect
  → isGuaranteedNotToBeUndef → programUndefinedIfUndefOrPoison
```

`CachedJavaType.cpp:1337` 附近的 predecessor 循环会查询 null edge；`LVINullEdgeOracle.cpp:37` 委托 LVI。LVI 的 `LazyValueInfo.cpp:939` 附近对 select condition 做 undef 证明；`ValueTracking.cpp:8270` 起会扫描后续指令/uses，带 32 条指令的扫描界限。生成输入的多层 select 反复使用同一个 `%c`。

BaseTypes 缓存的是 JavaType 基础类型，不会代替 LVI 的值格与 undef/poison 分析。Klass 已知也不等于指针非 null，不能直接省略 null-edge 证明。

CHA 的 `CHADevirtualization.cpp:477/483` 在对应改写路径清空 LVI；`JavaTypeCache::invalidate` 对 call/memory/terminator 保守清空上下文结果。这解释了 Base 保留后，上下文计算仍反复发生。

对于 virtual-cfg，查询之外还有约 20% 的 DT 更新成本，原生 self 栈中出现 SemiNCAInfo::DeleteReachable、getNodeInfo、runSemiNCA 等。这里应称为 DT 更新，不能仅凭函数名断言每次都完整重建。

对于 CFF，query 基本在 entry block，factsAt 提前返回，LVI 为零样本符合源码路径；这不代表 CFF 的其他输入也没有 LVI 成本。其进程约 47% 用于 IR 解析，因此查询层的小优化会被摊薄。
''')
    add(f'热点源码与文件哈希见 [source-context.json]({link}/source-context.json)；`perf annotate` 原始输出见 [poison]({link}/annotate/poison.txt)、[LVI select]({link}/annotate/lvi-select.txt)、[invalidate]({link}/annotate/invalidate.txt)。失效的 annotate 仅作源码定位，样本不足以细分内部成本。')
    add('### 5.3 结构诊断：保留是否转化为复用\n\n以下为独立的 8 函数正确性诊断，不能将带重算校验的 query time 作为性能结果。')
    structural=json.loads((a/'structural-diagnostics.json').read_text())
    sd={(r['case'],r['mode']):r for r in structural}
    table(['场景','查询数','FULL Base 插入','S1 Base 插入','S1 Path hit/miss','S1 Final hit/miss'],[
        [c,sd[c,'s1']['queries'],sd[c,'full']['base insertions'],sd[c,'s1']['base insertions'],
         f"{sd[c,'s1']['path facts hits']}/{sd[c,'s1']['path facts misses']}",
         f"{sd[c,'s1']['final type hits']}/{sd[c,'s1']['final type misses']}"] for c in cases])
    add('''deep 的 Base 插入从 8448 降为 528，wide 从 9216 降为 144，配合同工作量 CPU/cycles 下降，支持 Base 复用产生收益。现有 BaseHits 只统计 base-only 顶层查询，不代表递归 Base 命中数；本报告没有把该字段为 0 当作 Base 没有复用。

L1 的 Path/Final hit 均为 0，主要成本持续落在上下文计算与其支持分析。CFF 中 FULL 和 S1 都有 24 次 Final hit，因此不能把这些命中全部归功于选择性失效；S1 的额外保留主要体现为更少的 Base 重新填充。

累计 retained 数不等于后来命中数。本轮未为每条 Base entry 建立跨修改的永久身份轨迹，尚不能精确给出每类保留条目的重访收益。
''')
    add('### 5.4 按消费者与值存储成本观察\n\n下表以 S1 的 JavaType 相关 cycles 为分母，来自实际栈；未恢复到调用者的部分保留为未识别，不分配给猜测的消费者。')
    consumers=defaultdict(Counter)
    for r in csv.DictReader((a/'attribution/consumers.csv').open()):
        if r['mode']=='s1':consumers[r['case']][r['consumer']]+=int(r['period_sum'])
    labels=['CHA','TCE','CFF','FAM lifecycle','unresolved consumer']
    table(['场景','CHA %','TCE %','CFF %','FAM 回收 %','未识别 %'],[
        [c]+[f'{100*consumers[c][label]/sum(consumers[c].values()):.2f}' for label in labels] for c in cases])
    add('RecoverTypeInfo、RepeatedCFF、ArrayCopySpecialization、PEA 及完整 pre-PEA/JVM pipeline 未在本轮放大采样中覆盖；其缺失不是零成本。TCE→CHA 中主要采样成本仍由 CHA 产生，查询数量不能代替成本权重。')
    table(['S1 场景','JavaType 构造/复制/移动/析构 %','相关堆分配/释放 %'],[
        [c,f"{by[c,'s1']['jt_value_transfer_pct_median']:.2f}",f"{by[c,'s1']['jt_heap_pct_median']:.2f}"] for c in cases])
    add('这是调用栈交叉视图，分母仍为整进程，可能与 LVI、失效或回收重叠，不能再加到排他表中。堆操作也包含 LVI 等被调用分析的分配；未将其全部归于 Base/Path/Final。未知 libc 叶帧使精确的 copy/allocator/缓存层细分仍不完整。')
    add('## 6. 样本质量、失败记录与限制\n\n主 profile 共 72 份，另有 5 份抽查。每 case/mode 3 份累计样本如下，格式为总样本/JavaType 相关样本。')
    measured('样本数量')
    add('L1 每模式跨场景已超过调查样本目标。部分 leaf 单元格略低于 1000，CFF 只有约 281–391 个 JavaType 样本，因此 CFF 只作总体占比观察，不为其缓存内部子热点排名；少于 100 样本的子项也不排名。没有通过不断提高频率制造热点。')
    add(f"原始事件统计核验 {q['native_stats_profiles']} 份 perf.data：LOST record={q['lost_record_count']}，LOST_SAMPLES record={q['lost_sample_record_count']}，THROTTLE record={q['throttle_record_count']}。原始统计、record stderr 与数据哈希均保留。")
    measured('采样质量')
    add('未知比例包含 DSO 已知但符号未知的 libc 叶帧。先前只看 DSO unknown 得到的 pilot 0.17% 口径不完整，已撤回。匹配 libc build-id 的官方 debuginfod 请求返回 404，未安装系统包或改变安全配置；JavaType 子树未知叶帧未全部达到 <1% 目标，故 allocator 内部和细粒度缓存层成本明确标为归因不完整。')
    add('8 KiB 栈很多未到进程根，但多数能够恢复查询/helper 边界。使用冻结 opt 的原生符号表补全所属函数；分类只匹配函数所属类与名字，不匹配形参中的 LazyValueInfo/DominatorTree。原生/内联两种栈已对同一 pilot 校验粗粒度一致性。频率与长栈抽查如下；它们每档一份，仅作稳定性调查。')
    table(['抽查','样本','JavaType %','查询 LVI %','栈到根 %','相对同规模无采样 wall 开销'],[
        [r['tag'],r['samples'],f"{r['pct'].get('jt',0):.2f}",f"{r['pct'].get('jt_lvi',0):.2f}",
         f"{r['pct'].get('root_complete',0):.2f}",
         f"{100*(r['elapsed_s']/times[r['case']]['s1']['wall_s']['median']-1):+.2f}%"] for r in q['quality_checks']])
    add('上述 wall 开销包含 perf 启动、收尾和数据写入，只用来检查扰动；sample duration 与 user CPU 的比较不能替代这个同口径对照。超过 5% 的档位仅用于调查，不进入无采样速度排名。32 KiB 的消费者恢复程度也见 quality-summary.json；它不能使未解析 libc 符号自动可用。')
    add('本轮 399 Hz 档的 wall 开销约 5.15%，超过调查阈值，因此用 49/199 Hz 检查；低/高频 LVI 占整进程分别约 44.31%/45.41%，主采样继续采用 199 Hz。三组 32 KiB 抽查相对主表的 JavaType 占比变化不超过约 1.5 个百分点，virtual/wide 的消费者已几乎全部恢复到 CHA/FAM。32 KiB 仍非完整进程根栈，精细调用者和未知 libc 内部操作不作完整归因。')
    add('### 调度与 RSS 补测\n\nL1 原始 runner 的 RSS 所有场景/模式均为 1,892,964 KiB；其哈希函数整块读取约 1.8 GiB opt，父进程高水位污染了子进程峰值记录。原始 RSS 保留但不作缓存空间比较。补测改为流式哈希，并通过小内存父进程 wait4 直接取得 opt 的 RSS、user/system CPU 和 context switches。')
    add('在 paranoid=2 下，即使请求不带 `:u` 的软件事件，perf 仍将本机实际事件报告为 `:u`，switch/migration 继续为零。因此 context switches 使用 wait4，migration 只确认固定 affinity，不将 perf 的零值解释为实测无迁移。软件 task-clock 包含小型 Python launcher，补测不进入正式时间排名。')
    sched={(r['case'],r['mode']):r for r in q['scheduling']}
    table(['场景','ORIGIN RSS MiB','FULL RSS MiB','S0 RSS MiB','S1 RSS MiB','S1 voluntary/involuntary 切换'],[
        [c]+[f"{sched[c,m]['max_rss_kb_median']/1024:.1f}" for m in ['origin','full','s0','s1']]+[
            f"{sched[c,'s1']['voluntary_context_switches_median']:g}/{sched[c,'s1']['involuntary_context_switches_median']:g}"] for c in cases])
    add('原 stat JSON 的 `enabled_pct` 是历史字段命名错误，实际保存 perf 分隔格式的事件 runtime 数值；`running_pct` 才是 pcnt-running。本报告不将前者当百分数。软件调度受限和 RSS 问题均保留原始记录与修正后的解释。')
    add('''### 其余执行边界

- 没有运行 P1–P5 全进程 perf 并将其叫作纯失效；PauseTiming 不会暂停 perf 的范围问题没有被引入。
- 主测量期间源码与 opt 冻结；外置辅助脚本放结果目录，避免改变测量身份。没有为了统计重访而保留已删除 Value。
- 原计划三份 perf self/inclusive 文本改为：完整原始栈、每份原生 self、原始事件统计，以及可重算的 inclusive/排他 CSV。pilot 还保留原版 self/inclusive。L1 栈展开内联；L2 为减少重复源码解析导出原生 DWARF 栈，原始 perf.data 仍支持内联/源行分析。
- 64 层 select、同一个 condition、频繁调用改写/分析清空是本轮输入的特征，可能放大 LVI 的该路径。不能外推为所有真实 Java 方法的热点比例。
- 尚无完整 RecoverTypeInfo、RepeatedCFF、pre-PEA high-tier 或 JVM 采样；没有新增 L3 驱动器，现有 L1 已能解释主要成本，CFF 的细分仍标为证据不足。
''')
    add('''## 7. 下一轮优先实验

### 实验 1：在一次 LVI solve 内缓存重复 condition 的 undef 证明

依据：deep/tce 的 LVI 子树约占整进程 cycles 的 44%–45%；select 链反复使用相同 `%c`，`solveBlockValueSelect` 重复调用 `isGuaranteedNotToBeUndef(Cond, AC)`，并进入 ValueTracking 扫描。热点源行见本报告 5.2 和 annotate。

方案：先加默认关闭的计数，确认每次 solve 中相同 Cond 的重复评估，再试 query/solve 局部 memo。不要直接建立跨 IR 修改的全局缓存。memo 的有效期必须覆盖同一 IR、同一 AC 状态、同一种证明请求；缓存 false 也要验证精度未变。

受益预期：优先 deep-static、tce-cha，其次有重复 select condition 的真实回放。维护成本较低：局部生命周期无需新增跨修改依赖图，但须确认求解过程不会改变证明所依赖的状态。

验收：相同 Cond 的实际 ValueTracking 评估数显著下降；对照记录 LVI/ValueTracking cycles 与总体 user CPU。undef、poison、freeze、assume、循环/预算边界和所有既有正确性测试通过，关键优化数和完整输入的输出精度保持。建议将 ≥5% 的 deep/tce CPU 改善作为继续投入的目标，正式性能结论再用两 session × 30 轮验证。

### 实验 2：明确修改事件的分析影响，减少不必要的 LVI/上下文重算

依据：L1 Path/Final 0 hit，Base 插入已大幅减少；CHA 对应路径多次清空 LVI。wide 和 virtual 除 LVI 外仍有 factsAt 遍历与类型值构造成本。相比优化删除入口，避免重建被删掉的上下文结果可能有更大的空间。

方案：让改写 helper 报告实际影响，例如是否改变 CFG、call 的 nullability/dereferenceable/assume 事实、内存行为、Value operands 或仅修改不影响分析的元数据。先审计 LVI 的依赖与更新接口；仅在能证明保留正确的事件上保留结果，其余继续保守清空。调用目标变化、CallBase 新建、Klass 已知均不能单独作为保留 null/poison 事实的理由。

必须继续在旧 Value/use 图存活时通知；考虑批量通知时，先界定无查询穿插的修改窗口。跨删除身份与 FAM 生命周期仍遵守既有边界。

验收：记录每种清空原因、oracle 调用数、实际 retained→hit，而非累计 retained。与全新 DT/LVI/FAM 参考逐次比较 Query—Mutate—Query；覆盖 call attrs 增删、null guard、assume、内存访问、CFG、PHI、RAUW/删除及地址复用。以 LVI 相关 CPU 至少降低 20%、deep/wide 总体 user CPU 至少降低 5% 为实验目标，同时审查 leaf/virtual 是否回退；这些是验收目标，不是本轮已证明的收益。

目前不建议直接实现 S2/S3/S4 或替换 DenseMap。本轮 S1 失效只占约 1% 量级；完全消除它也只有同量级 CPU 收益空间，而且样本不足以给精确上限。相比之下，deep 的 LVI 约 45% 提供更大的理论空间，但其中并非全部可缓存，cycles 的 Amdahl 上限也不是墙钟承诺。若未来真实 workload 出现高 C 或巨大单函数表，再以该 workload 重新比较分组索引、epoch 或反向依赖登记的净成本。
''')
    add(f'''## 8. 产物与复现

服务器持久目录：

```text
/home/annya/playground/jeandle/perf-results/2026-10-23-javatype-perf/
  build/                         配置、符号、单测与 lit 日志
  run/manifest.json              身份与输入
  run/baseline/                  L1 无采样每轮记录
  run/stat/                      L1 原始分组计数
  run/profiles/<case>/<mode>/    60 份主 profile
  run/l2/                       CFF baseline/stat/12 份 profile
  run/diagnostics/scheduling/    72 份补测
  run/diagnostics/quality/       5 份频率/长栈抽查
  run/diagnostics/annotate/      热点源行与汇编
  run/perf-data-ledger.json      全部 perf.data 绝对路径、大小和 SHA-256
  run/input-identity-post.json   结束时输入/cblog 哈希
  run/identity-post.json         结束时源码与二进制哈希
```

大 perf.data 保留在服务器，准确位置与哈希见 [ledger]({link}/perf-data-ledger.json)。本地保留 [原始小型记录]({link}/run-records.tar.gz)、[主表]({link}/report-tables.md)、[排他分类]({link}/attribution/attribution.csv)、[每份 inclusive/质量数据]({link}/attribution/profile-runs.csv)、[调度/RSS]({link}/scheduling-summary.csv)、[质量汇总]({link}/quality-summary.json)。

辅助图：[deep/S1 火焰图]({link}/deep-static-s1-flamegraph.svg)，按 period 权重生成。图中根栈可能不完整，不将宽度变化直接解释成绝对时间变化。生成器版本为 `javatype-flamegraph-1`，源码与校验脚本保留在 [scripts/]({link}/scripts/README.md)。

所有性能数据均来自同一冻结身份；最后未改动缓存算法，也未自动实现下一轮方案。''')
    args.output.write_text('\n'.join(out))
    print(args.output)


if __name__=='__main__':main()
