#!/usr/bin/env python3
"""Pinned, paired JavaType benchmark. See README.md for the JSON schema."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import resource
import statistics as st
import subprocess
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def counters(text):
    data = {k: int(v) for k, v in re.findall(r'^  ([^:\n]+): (\d+)$', text, re.M)}
    if 'total query time (ns)' not in data:
        raise RuntimeError('missing JavaType summary (never interpret missing as zero)')
    return data


def interval(values, seed):
    rng = random.Random(seed)
    estimates = sorted(st.median(rng.choices(values, k=len(values))) for _ in range(4000))
    return [estimates[100], estimates[3899]]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases', type=Path, required=True)
    p.add_argument('--a', type=Path, required=True)
    p.add_argument('--b', type=Path, required=True)
    p.add_argument('--a-flag', action='append', default=[])
    p.add_argument('--b-flag', action='append', default=[])
    p.add_argument('--cpu', type=int, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--repeats', type=int, default=31)
    p.add_argument('--warmups', type=int, default=3)
    p.add_argument('--seed', type=int, default=20261030)
    p.add_argument('--min-cpu-ms', type=float, default=200)
    p.add_argument('--calibration', type=Path, help='A/A summary.json from the same environment and workloads')
    p.add_argument('--timeout', type=float, default=120)
    p.add_argument('--noise-floor-pct', type=float, default=0,
                   help='measured A/A noise envelope, in percent')
    args = p.parse_args()
    for flag in args.a_flag + args.b_flag:
        if any(token in flag for token in ('stats', 'verify', 'print<', 'debug', 'time-passes')):
            p.error('observer/verification flags are not allowed in timed modes')
    if args.repeats < 5 or args.warmups < 0 or args.min_cpu_ms <= 0:
        p.error('require repeats >= 5, warmups >= 0 and positive sample duration')
    if args.cpu not in os.sched_getaffinity(0):
        p.error('requested CPU is outside allowed affinity')
    os.sched_setaffinity(0, {args.cpu})
    args.out.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.cases.read_text())
    if not cases or len({c['name'] for c in cases}) != len(cases):
        p.error('cases must be nonempty and names must be unique')
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]+', c['name']) or c['name'] in ('.', '..') for c in cases):
        p.error('case names must be plain file-name components')
    modes = {'a': (str(args.a.resolve()), args.a_flag), 'b': (str(args.b.resolve()), args.b_flag)}
    env = dict(os.environ)
    env.pop('LD_LIBRARY_PATH', None)
    hashes = {b: sha(b) for b, _ in modes.values()}
    source_head = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    source_diff = subprocess.run(['git', 'diff', 'HEAD'], capture_output=True).stdout
    inputs = {str(Path(c[k]).resolve()): sha(c[k]) for c in cases for k in ('input', 'callback')}
    manifest = dict(arguments=vars(args) | {'cases': str(args.cases), 'a': str(args.a), 'b': str(args.b), 'out': str(args.out), 'calibration': str(args.calibration) if args.calibration else None},
                    modes=modes, binary_sha256=hashes, input_sha256=inputs,
                    affinity=sorted(os.sched_getaffinity(0)), platform=dict(zip(("sysname", "nodename", "release", "version", "machine"), os.uname())),
                    cases=cases, seed=args.seed, source_head=source_head,
                    source_diff_sha256=hashlib.sha256(source_diff).hexdigest(), harness_sha256=sha(__file__))
    for name in ('topology/thread_siblings_list', 'cpufreq/scaling_governor'):
        f = Path(f'/sys/devices/system/cpu/cpu{args.cpu}') / name
        manifest[name] = f.read_text().strip() if f.exists() else None
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    calibration = json.loads(args.calibration.read_text()) if args.calibration else {}
    if args.calibration:
        for case in cases:
            entry = calibration.get(case['name'], {})
            if not entry.get('sample_duration_ok') or any(metric not in entry for metric in ('wall_ns', 'cpu_ns')):
                p.error('calibration is missing a case or contains short samples')
    same_configuration = hashes[modes['a'][0]] == hashes[modes['b'][0]] and args.a_flag == args.b_flag
    rng = random.Random(args.seed)
    raw = (args.out / 'samples.jsonl').open('w', buffering=1)

    def run(case, mode, diagnostic=False, verification=False):
        binary, flags = modes[mode]
        pipeline = case['passes']
        cmd = [binary, '-S' if diagnostic or verification else '-disable-output',
               '-passes=' + pipeline + (',print<java-type-analysis-summary>' if diagnostic else ''),
               '-jeandle-vm-callback-log=' + str(Path(case['callback']).resolve()), str(Path(case['input']).resolve()), *flags]
        if diagnostic:
            cmd += ['-verify-each', '-jeandle-java-type-stats']
        if verification:
            cmd += ['-verify-each', '-jeandle-verify-java-type-cache']
        start_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter_ns()
        try:
            result = subprocess.run(cmd, capture_output=True, env=env, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            raw.write(json.dumps(dict(case=case['name'], mode=mode, command=cmd, error='timeout'))+'\n')
            raise
        wall = time.perf_counter_ns() - start
        end_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = int(((end_cpu.ru_utime-start_cpu.ru_utime)+(end_cpu.ru_stime-start_cpu.ru_stime))*1e9)
        row = dict(case=case['name'], mode=mode, command=cmd, wall_ns=wall, cpu_ns=cpu,
                   returncode=result.returncode,
                   voluntary_switches=end_cpu.ru_nvcsw-start_cpu.ru_nvcsw,
                   involuntary_switches=end_cpu.ru_nivcsw-start_cpu.ru_nivcsw)
        if result.returncode:
            raw.write(json.dumps(row | {'stderr': result.stderr.decode(errors='replace')})+'\n')
            raise RuntimeError(f"opt exited {result.returncode}: {cmd}")
        return row, result

    summary = {}
    for case in cases:
        outputs = []
        for mode in modes:
            check_row, checked = run(case, mode, verification=True)
            raw.write(json.dumps(check_row | {'phase': 'correctness'})+'\n')
            (args.out / f"{case['name']}-{mode}-verification.stderr").write_bytes(checked.stderr)
            row, result = run(case, mode, True)
            if checked.stdout != result.stdout:
                raise RuntimeError('verification changed optimized IR')
            outputs.append(result.stdout)
            (args.out / f"{case['name']}-{mode}.ll").write_bytes(result.stdout)
            (args.out / f"{case['name']}-{mode}.stderr").write_bytes(result.stderr)
            raw.write(json.dumps(row | {'phase':'diagnostic', 'counters':counters(result.stderr.decode())})+'\n')
        if outputs[0] != outputs[1]:
            raise RuntimeError('optimized IR differs; inspect diagnostic outputs before timing')
        pairs = []
        for index in range(-args.warmups, args.repeats):
            order = list(modes)
            rng.shuffle(order)
            pair = {}
            for position, mode in enumerate(order):
                row, result = run(case, mode)
                if result.stdout or result.stderr:
                    raise RuntimeError('timed run emitted output; inspect flags')
                row |= {'phase': 'warmup' if index < 0 else 'timed', 'round':index, 'position':position}
                raw.write(json.dumps(row)+'\n')
                pair[mode] = row
            if index >= 0:
                pairs.append(pair)
        entry = {}
        sufficiently_long = all(x[m]['cpu_ns'] >= args.min_cpu_ms*1e6 for x in pairs for m in modes)
        for metric in ('wall_ns', 'cpu_ns'):
            changes = [100*(x['b'][metric]/x['a'][metric]-1) for x in pairs]
            ci = interval(changes, args.seed)
            envelope = max(args.noise_floor_pct, calibration.get(case['name'], {}).get(metric, {}).get('absolute_pair_change_p95', 0))
            calibrated = args.calibration is not None or args.noise_floor_pct > 0
            status = 'inconclusive'
            if sufficiently_long and calibrated and not same_configuration and ci[1] < -envelope:
                status = 'improvement'
            elif sufficiently_long and calibrated and not same_configuration and ci[0] > envelope:
                status = 'regression'
            entry[metric] = dict(a_median=st.median(x['a'][metric] for x in pairs),
                                 b_median=st.median(x['b'][metric] for x in pairs),
                                 paired_change_pct=st.median(changes), bootstrap_95pct=ci,
                                 absolute_pair_change_p95=sorted(abs(v) for v in changes)[math.ceil(.95*len(changes))-1],
                                 noise_floor_pct=envelope, verdict=status)
        entry['sample_duration_ok'] = sufficiently_long
        summary[case['name']] = entry
        (args.out/'summary.json').write_text(json.dumps(summary, indent=2))
        print(case['name'], json.dumps(entry), flush=True)
    if sha(__file__) != manifest['harness_sha256']:
        raise RuntimeError('harness changed during run')
    for path, expected in (hashes | inputs).items():
        if sha(path) != expected:
            raise RuntimeError('binary or input changed during run: '+path)
    (args.out/'SUCCESS').write_text('completed; see sample_duration_ok and A/A noise floor before interpreting results\n')


if __name__ == '__main__':
    main()
