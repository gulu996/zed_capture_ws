from pathlib import Path
import subprocess,json
D=Path(__file__).resolve().parent
for mode in ['baseline_reader','enhanced_reader']:
 p=D/mode
 args=['c++','-std=c++14','-O2','-pthread','-I/home/jetson/zed_capture_ws/src/zed_capture/include','-I'+str(p),str(D/'reader_harness.cpp'),'-Wl,--wrap=clock_gettime,--wrap=clock_nanosleep,--wrap=stat,--wrap=__xstat,--wrap=open,--wrap=close,--wrap=pread','-o',str(p/'reader_test')]
 subprocess.run(args,check=True)
 with (p/'trace.txt').open('w') as f:subprocess.run([str(p/'reader_test'),str(p/'diagnostic.jsonl')],check=True,stdout=f)
a=(D/'baseline_reader/trace.txt').read_bytes();b=(D/'enhanced_reader/trace.txt').read_bytes();assert a==b,'production trace mismatch'
rows=[json.loads(x) for x in (D/'enhanced_reader/diagnostic.jsonl').read_text().splitlines()]
for r in rows:
 for k in ['a','b']:
  rc=r['pread_'+k+'_ret']
  assert (r[k]['full_snapshot'] is not None)==(rc==64)
  assert (r['pread_'+k+'_errno'] is not None)==(rc is not None and rc<0)
assert any(r['pread_a_errno']==9 and r['pread_b_ret']==64 for r in rows)
assert any(r['validity']=='UNKNOWN_CLOCK' and r['legacy_stable'] for r in rows)
assert any(r['validity']=='NOT_READY' and r['legacy_stable'] for r in rows)
assert any(not r['read_attempted'] for r in rows)
assert len((D/'baseline_reader/diagnostic.jsonl').read_bytes())==0
print(json.dumps({'actual_reader_body_comparison':'PASS','synthetic':True,'trace_bytes':len(a),'events':len(rows),'stable_anchor_skipped_old_poll_and_syscall_trace_equal':True},indent=2))
