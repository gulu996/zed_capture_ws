#!/usr/bin/env python3
"""Manual FULL_STRICT_CHECK. New output directory; source session stays read-only."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from field_common import HERE,WS,ROOT,load,identity,manager_alive,process,boot_id,finalized_evidence,atomic
sys.path.insert(0,str(WS/'scripts'))

def eligibility(p):
    p=Path(p).resolve(strict=True);m=load(p/'session.json')
    if m.get('session_id')!=p.name:raise ValueError('manifest/session identity mismatch')
    if (p/'field_identity.json').exists():
        i=identity(p)
        if manager_alive(i):raise RuntimeError('Field manager still active; FULL_STRICT_CHECK refused')
        final=load(p/'capture_finalization.json')
        if any(final.get(k)!=i[k] for k in ('token','session_id','session_dir','boot_id')):
            raise ValueError('finalization identity mismatch')
        if final.get('manager_children_exited') is not True:raise ValueError('owned child exit not confirmed')
    # Legacy manager evidence is accepted only when its actual identity is not live.
    c=load(p/'control.json',{})
    if c and m.get('boot_id')==boot_id():
        try:
            current=process(c['manager_pid'])
            if current['state']!='Z' and current['start_ticks']==str(c['start_ticks']):
                raise RuntimeError('Session capture manager still active')
        except FileNotFoundError:pass
    mr=load(p/'manager_result.json')
    if 'returncode' not in mr:raise ValueError('manager completion missing')
    evidence=finalized_evidence(p,m['config'].get('gnss_enable',False))
    if evidence['FINALIZATION_STATUS']!='FINALIZED':raise RuntimeError('Unsafe/incomplete finalization: '+repr(evidence))
    if list(p.glob('*.active')):raise RuntimeError('active bag exists')
    return evidence

def command(p,out):
    checker=HERE/'check_segments_full.py' if (Path(p)/'bag_segments.jsonl').exists() else WS/'scripts/check_recording.py'
    return [sys.executable,'-B',str(checker),str(p),'--output-dir',str(out)]

def run(p):
    p=Path(p).resolve(strict=True);e=eligibility(p)
    root=HERE/'checks';root.mkdir(exist_ok=True)
    out=root/(p.name+'_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir()
    atomic(out/'invocation.json',dict(session_dir=str(p),check_mode='FULL_STRICT_CHECK',eligibility=e,
        argv=command(p,out),checker_sha256=hashlib.sha256((WS/'scripts/check_recording.py').read_bytes()).hexdigest()),True)
    from capture_environment import capture_environment
    env=capture_environment();env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
    print('CHECK_DIR='+str(out),flush=True)
    with (out/'checker_terminal.log').open('x') as log:
        result=subprocess.run(command(p,out),stdout=log,stderr=subprocess.STDOUT,env=env)
    clocks={'CLOCK_DIAGNOSTIC':'PENDING_NO_FIELD_CLOCK'}
    if (p/'clock/three_clock.csv').exists():
        sys.path.insert(0,'/home/jetson/clock_diag');from analyze import clock_analysis,adjustment_analysis
        try:clocks={'analysis':clock_analysis(p/'clock/three_clock.csv'),'adjustments':adjustment_analysis(p/'clock/clock_adjustments.csv')}
        except Exception as err:clocks={'CLOCK_DIAGNOSTIC':'INCONCLUSIVE','error':repr(err)}
    atomic(out/'clock_analysis.json',clocks,True)
    profile=load(out/'check_result.profile.json',{})
    # Stream/result remain produced by the unchanged C5-H runner, not by this wrapper.
    atomic(out/'check_exit.json',{'returncode':result.returncode,'full_strict_completed':profile.get('full_strict_completed',False),
        'capture_integrity':'PASS' if result.returncode==0 and profile.get('full_strict_completed') else 'FAIL',
        'CLOCK_DIAGNOSTIC':clocks.get('analysis',{}).get('status',clocks.get('CLOCK_DIAGNOSTIC','PENDING')),
        'L2B_MAPPING':'PENDING','PHYSICAL_SYNC':'PENDING',
        'source_session':str(p),'output_dir':str(out)},True)
    print('CHECK_RESULT='+str(out/'check_result.json'),flush=True)
    return result.returncode

def main():
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--session');g.add_argument('--session-dir');a=ap.parse_args()
    if a.session and (Path(a.session).name!=a.session or a.session in ('.','..')):ap.error('invalid session ID')
    return run(Path(a.session_dir) if a.session_dir else ROOT/a.session)
if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,ValueError,OSError,KeyError) as e:print('CHECK REFUSED/FAILED:',str(e),file=sys.stderr);sys.exit(2)
