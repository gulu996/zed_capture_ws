"""C4.1 sidecar-only analysis. Raw event values retained; no bag scan."""
import csv,json,pathlib
def csvrows(p):
    if not p.exists():return []
    with p.open() as f:return list(csv.DictReader(f))
def analyze(session):
    session=pathlib.Path(session);events=csvrows(session/'jpeg_shadow_events.csv');trace=csvrows(session/'jpeg_shadow_worker_timing.csv')
    by_id={int(e['input_id']):e for e in events};ordered=sorted(trace,key=lambda e:int(e['input_id']));result=[];previous=None;errors=[]
    for row in ordered:
        if row['status']!='COMPLETED':continue
        e=by_id.get(int(row['input_id']));
        if e is None:errors.append('trace missing matching input event');continue
        n=lambda k:int(row[k]);submitted=int(e['submitted_ns'])
        if not(n('notify_before_ns')<=n('notify_after_ns')<=n('producer_unlock_observed_ns') and n('wait_before_ns')<=n('wait_return_ns')<=n('worker_start_ns')<=n('completed_ns')<=n('event_log_before_ns')<=n('event_log_after_ns')<=n('task_release_end_ns')):errors.append('nonmonotonic trace at '+row['pair_id'])
        r={'pair_id':int(row['pair_id']),'total_latency_ms':(n('completed_ns')-int(e['copied_ns']))/1e6,'queue_wait_ms':(n('worker_start_ns')-submitted)/1e6,'notify_to_wait_return_ms':(n('wait_return_ns')-n('notify_after_ns'))/1e6,'worker_lock_wait_ms':(n('worker_lock_acquired_ns')-n('worker_lock_before_ns'))/1e6,'worker_cpu_ms':(n('worker_cpu_end_ns')-n('worker_cpu_start_ns'))/1e6,'worker_wall_ms':(n('completed_ns')-n('worker_start_ns'))/1e6,'log_write_ms':(n('event_log_after_ns')-n('event_log_before_ns'))/1e6,'task_release_ms':(n('task_release_end_ns')-n('event_log_after_ns'))/1e6,'wait_was_empty':row['wait_was_empty']=='1','previous_tail_after_submission_ms':None if previous is None else (int(previous['task_release_end_ns'])-submitted)/1e6}
        result.append(r);previous=row
    wp=session/'jpeg_shadow_warmup.json';warmup=json.loads(wp.read_text()) if wp.exists() else {}
    warmup_before_first=bool(events and warmup and int(warmup['end_ns'])<min(int(e['copied_ns']) for e in events))
    if not warmup_before_first:errors.append('warmup completion before real frames not confirmed')
    complete=bool(events) and len(trace)==len(events) and {r['input_id'] for r in trace}=={r['input_id'] for r in events}
    if not complete:errors.append('timing evidence incomplete')
    return {'status':'SOFTWARE_EVIDENCE_COMPLETE' if not errors else 'INCOMPLETE','errors':errors,'warmup':warmup,'warmup_before_first_real_copy':warmup_before_first,'rows':result,'late_pair_ids':[r['pair_id'] for r in result if r['total_latency_ms']>33.333333],'semantics':'wait_return includes condition wake + mutex reacquire + scheduling; notify/unlock timestamps are sequential observations, not kernel-ready timestamps. Wall minus thread CPU is suggestive, not unique causality.'}
