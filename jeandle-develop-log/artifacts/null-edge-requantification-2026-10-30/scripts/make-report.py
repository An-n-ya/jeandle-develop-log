import json
from pathlib import Path
base=Path('jeandle-develop-log/artifacts/null-edge-requantification-2026-10-30')
intro=Path(__file__).with_name('report-intro.md').read_text()
lines=[intro,'\n## 无统计插桩的端到端结果\n']
label={'improvement':'确认改善','regression':'确认回退','inconclusive':'无法确认差异'}
for group,title in [('synthetic','五种合成输入'),('corpus','八个 null-edge 用例的放大版本')]:
 s=json.loads((base/(group+'-ab/summary.json')).read_text())
 lines += ['\n### '+title+'\n','| 输入 | 基线 CPU ms | 优化 CPU ms | 配对 CPU 变化 | 95% 区间 | A/A 门槛 | 结论 |','|---|---:|---:|---:|---|---:|---|']
 for name,v in s.items():
  c=v['cpu_ns'];ci=c['bootstrap_95pct']
  lines.append(f"| {name} | {c['a_median']/1e6:.1f} | {c['b_median']/1e6:.1f} | {c['paired_change_pct']:+.2f}% | [{ci[0]:+.2f}%, {ci[1]:+.2f}%] | {c['noise_floor_pct']:.2f}% | {label[c['verdict']]} |")
 lines.append('\n墙钟变化：'+ '；'.join(f"{n} {v['wall_ns']['paired_change_pct']:+.2f}%（{label[v['wall_ns']['verdict']]}）" for n,v in s.items())+'。\n')
 assert all(v['sample_duration_ok'] for v in s.values())
lines+=['\n## 查询内部成本：单独诊断\n','这部分开启统计，以 15 轮交错重复测量。计时器为查询内部 steady_clock；没有混入 reference 重算。基线没有 oracle 细粒度计时，优化侧在诊断时有，因此这组结果用于解释路径成本，不能替代上面的无统计插桩进程 CPU 收益。下表为每个完整模块内所有顶层查询的累计时间。\n','| 输入 | 基线查询 ms | 优化查询 ms | 配对查询时间变化 | 95% 区间 | 优化侧 oracle calls |','|---|---:|---:|---:|---|---:|']
for group in ['synthetic','corpus']:
 q=json.loads((base/(group+'-queries/summary.json')).read_text())
 for n,v in q.items():
  ci=v['bootstrap_95pct'];bc=v['b_counters']
  lines.append(f"| {n} | {v['a_query_median_ns']/1e6:.2f} | {v['b_query_median_ns']/1e6:.2f} | {v['paired_change_pct']:+.2f}% | [{ci[0]:+.2f}%, {ci[1]:+.2f}%] | {bc.get('null-edge oracle calls',0):g} |")
  assert bc['null-edge oracle budget exhausted queries']==0
lines += ['\n所有诊断中优化侧的 oracle 预算耗尽计数均为 0。五种合成输入的优化侧 oracle 调用均为 0；基线为避免增加生产路径开销，未添加 oracle 计数，当前对照不提供基线 oracle 调用次数。\n','\n## 覆盖、排除与输入验证\n','11 个原始 oracle 用例先做原始规模的输出及 cached/reference 检查：\n','| 用例 | 输出一致 | 基线差分验证 | 优化侧差分验证 | 处理 |','|---|---|---|---|---|']
audit=json.loads((base/'corpus-audit.json').read_text())
for v in audit:
 valid=v['same_ir'] and v['a_verification_exit']==0 and v['b_verification_exit']==0
 lines.append(f"| {v['name']} | {'是' if v['same_ir'] else '否'} | {'通过' if v['a_verification_exit']==0 else '失败'} | {'通过' if v['b_verification_exit']==0 else '失败'} | {str(v.get('replicas',''))+' 份独立函数' if valid else '排除性能对照，保留行为记录'} |")
lines += ['\n`null-guard-forms` 的精度一致性修复仍然存在；它的输出变化是行为收益，未混入等价输出的性能表。`null-arm-type`、`condition-value-domain` 两侧都有既有差分失败，未把它们当作正确性已验证的性能样本。\n','\n放大输入保留原函数体、模块常量、属性和 metadata，新增不同名称的函数定义；每个函数有独立的 JavaType/LVI 分析生命周期。另检查优化侧原始输入的 queries、oracle calls、structural hits、true answers、prefilter hits、预算耗尽数，必须乘以复制倍数后与放大输入计数一致，见 amplification-checks.json。\n','\n基线单测为 46/47，仍只有 CachedEntryNormalizesFreeze 失败；优化版本先前验证为 47/48，新增预算测试通过。本次两侧测量输入均通过 IR 验证及 cached/reference 检查，优化前后输出逐字一致。\n','\n## 可复现产物与限制\n','产物位于 `artifacts/null-edge-requantification-2026-10-30/`：versions.json 绑定版本、编译配置与二进制 SHA256；各 aa/ab 目录含 manifest、逐轮 samples.jsonl、summary 和日志；*-queries 含诊断原始计数；baseline-controls.patch 记录基线控制改动；scripts/ 保存生成、审计、测试和收集脚本。SUCCESS 只表示流程完成，不代表每项均有显著收益。\n','\n测试机完整 IR 和诊断日志保存在 `/tmp/null-edge-requant-results`，输入在 `/tmp/null-edge-workloads-20261030` 与 `/tmp/null-edge-requant-inputs`。使用现有 benchmark.py，通过 --a/--b 指向两侧 opt、--calibration 指向本组 calibration.json 即可重跑；完整命令已逐轮写入 manifest/samples 和 run-suite.py。原始11个用例在准备脚本中显式列出。\n','\n这些结果量化的是五种合成结构与八种单元测试形状上的编译成本。没有提供真实 JVM 编译录制输入，本次不据此给出生产整体提速率或 Java 程序执行速度。也没有将整体改动的收益进一步分摊到 S1/S2/S3/S4/S5。共享机器仍有尾部波动，接近门槛的结果应在独占机器上复核。\n']
Path('jeandle-develop-log/JavaType-NullEdge-Requantification-2026-10-30.md').write_text('\n'.join(lines))
