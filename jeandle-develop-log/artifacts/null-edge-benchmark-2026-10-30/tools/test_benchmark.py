import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HARNESS = Path(__file__).with_name('benchmark.py')


class HarnessTest(unittest.TestCase):
    def exercise(self, behavior):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opt = root/'opt'
            opt.write_text('''#!/usr/bin/env python3
import sys
behavior = '''+repr(behavior)+'''
if behavior == 'failure':
    sys.exit(2)
if '-jeandle-java-type-stats' in sys.argv:
    if behavior != 'missing':
        print('  total query time (ns): 1000', file=sys.stderr)
if '-S' in sys.argv:
    print('different' if behavior == 'different' and '--candidate' in sys.argv else 'same')
''')
            opt.chmod(0o755)
            (root/'input.ll').write_text('; test')
            (root/'log').write_text('test')
            cases = root/'cases.json'
            cases.write_text(json.dumps([dict(name='test',input=str(root/'input.ll'),callback=str(root/'log'),passes='function(cha-devirtualization)')]))
            command=[sys.executable,str(HARNESS),'--cases',str(cases),'--a',str(opt),'--b',str(opt),'--cpu',str(min(os.sched_getaffinity(0))),'--out',str(root/'results'),'--repeats','5','--warmups','0','--min-cpu-ms','1000']
            if behavior == 'different':
                command += ['--b-flag=--candidate']
            proc=subprocess.run(command,capture_output=True,text=True)
            if behavior != 'ok':
                self.assertNotEqual(proc.returncode,0)
                self.assertFalse((root/'results/SUCCESS').exists())
                self.assertIn({'failure':'opt exited 2', 'missing':'missing JavaType summary', 'different':'optimized IR differs'}[behavior], proc.stderr)
                return
            self.assertEqual(proc.returncode,0,proc.stderr)
            summary=json.loads((root/'results/summary.json').read_text())['test']
            self.assertFalse(summary['sample_duration_ok'])
            self.assertEqual(summary['cpu_ns']['verdict'],'inconclusive')
            rows=[json.loads(s) for s in (root/'results/samples.jsonl').read_text().splitlines()]
            timed=[r for r in rows if r['phase']=='timed']
            self.assertEqual(len(timed),10)
            for r in timed:
                self.assertIn('-disable-output',r['command'])
                self.assertNotIn('-jeandle-java-type-stats',r['command'])
                self.assertNotIn('-verify-each',r['command'])
            for i in range(5):
                self.assertEqual({r['mode'] for r in timed if r['round']==i},{'a','b'})

    def test_short_samples_are_inconclusive(self): self.exercise('ok')
    def test_process_failure_is_fatal(self): self.exercise('failure')
    def test_missing_counters_are_fatal(self): self.exercise('missing')
    def test_ir_difference_is_fatal(self): self.exercise('different')


if __name__=='__main__': unittest.main()
