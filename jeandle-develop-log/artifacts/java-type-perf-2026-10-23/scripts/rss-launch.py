"""Low-memory parent for a process-local wait4 measurement (not query timing)."""
import json,os,subprocess,sys,time
start=time.perf_counter_ns()
process=subprocess.Popen(sys.argv[1:])
_,status,usage=os.wait4(process.pid,0)
code=os.waitstatus_to_exitcode(status);process.returncode=code
print('[javatype-rusage] '+json.dumps(dict(wall_ns=time.perf_counter_ns()-start,
    user_s=usage.ru_utime,system_s=usage.ru_stime,max_rss_kb=usage.ru_maxrss,
    voluntary_context_switches=usage.ru_nvcsw,involuntary_context_switches=usage.ru_nivcsw)),file=sys.stderr)
raise SystemExit(code)
