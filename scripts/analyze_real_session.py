#!/usr/bin/env python3
"""Read-only analysis. Output MUST be outside the source session; no clock fit."""
import argparse,bisect,collections,csv,datetime,json,pathlib,struct
import numpy as np

def read_video(path):
    rows=[]
    with path.open() as source:
        for row in csv.DictReader(source):
            # Older ROS uint8 bool streamed as a byte; preserve historical files.
            rows.append({k:(int(v) if v not in ('\x00','\x01') else ord(v)) for k,v in row.items()})
    return rows

def stats(values):
    if not len(values):return None
    return {str(p):float(np.percentile(values,p)) for p in [0,50,95,99,100]}

def wall(ns):return datetime.datetime.fromtimestamp(ns/1e9,datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='microseconds')

def sequence_kind(before,after):
    delta=(after-before)&0xffffffff
    return ('normal' if delta==1 else 'duplicate' if delta==0 else 'gap' if delta<0x80000000 else 'reset_or_backward'),delta

def assess_anchor_coverage(v,a):
    good=[r for r in a if r.get('validity')=='HOST_ARRIVAL_ANCHOR'];host=[r['host_monotonic_ns'] for r in good];coverage=[];brackets=[]
    if any(y<=x for x,y in zip(host,host[1:])):
        return {'status':'PENDING','input_coverage_counts':{'ANCHOR_HOST_TIME_NOT_INCREASING':len(v)},'candidate_bracket_span_ms':None,'uncovered_frames':[{'pair_id':r['pair_id'],'raw_ns':r['raw_ns'],'assessment':'ANCHOR_HOST_TIME_NOT_INCREASING'} for r in v],'note':'Segment/reset handling belongs to L2-B; no bisect or mapping on unsorted host times.'}
    for row in v:
        j=bisect.bisect_right(host,row['raw_ns']);reason='CANDIDATE_BRACKET_ONLY'
        if row['timestamp_type']!=8192:reason='UNKNOWN_VIDEO_CLOCK'
        elif j==0:reason='BEFORE_FIRST_VALID_ANCHOR'
        elif j==len(host):reason='AFTER_LAST_VALID_ANCHOR'
        elif good[j]['writer_epoch']!=good[j-1]['writer_epoch'] or good[j]['clock_source']!=good[j-1]['clock_source']:reason='ANCHOR_DOMAIN_CHANGE'
        elif host[j]-host[j-1]>100000000:reason='ANCHOR_BRACKET_OVER_100MS'
        else:brackets.append(host[j]-host[j-1])
        coverage.append({'pair_id':row['pair_id'],'raw_ns':row['raw_ns'],'assessment':reason})
    return {'status':'PENDING','input_coverage_counts':dict(collections.Counter(r['assessment'] for r in coverage)),'candidate_bracket_span_ms':stats(np.array(brackets)/1e6),'uncovered_frames':[r for r in coverage if r['assessment']!='CANDIDATE_BRACKET_ONLY'],'note':'Bracketing is an input coverage test, not L2-B execution, physical sync, or validated interpolation error; 100ms uses current anchor freshness policy.'}

def timing_evidence(session):
    session=pathlib.Path(session);file=session/'video_timing.csv'
    if not file.exists():return {'status':'NOT_RECORDED_IN_ORIGINAL_SESSION'}
    rows=list(csv.DictReader(file.open()));v=read_video(session/'video_timestamps.csv')
    def durations(end,begin):return stats([(int(r[end])-int(r[begin]))/1e6 for r in rows])
    result={'status':'OBSERVED','timing_rows':len(rows),'qbuf_errors':sum(int(r['qbuf_result'])!=0 for r in rows),'select_wait_ms':durations('poll_after_ns','poll_before_ns'),'dq_to_callback_end_ms':durations('callback_end_ns','dq_after_ns'),'callback_cpu_ms':stats([int(r['callback_cpu_ns'])/1e6 for r in rows]),'callback_wall_minus_cpu_ms':stats([max(0,int(r['callback_end_ns'])-int(r['dq_after_ns'])-int(r['callback_cpu_ns']))/1e6 for r in rows]),'callback_end_to_qbuf_ms':durations('qbuf_end_ns','callback_end_ns'),'note':'wall-minus-thread-CPU includes blocking/preemption and instrumentation boundaries; select wait is not pure scheduler latency'}
    for name,end,begin in [('copy_ms','copied_ns','copy_begin_ns'),('writer_queue_wait_ms','writer_begin_ns','copied_ns'),('writer_video_job_ms','writer_end_ns','writer_begin_ns')]:
        result[name]=stats([(r[end]-r[begin])/1e6 for r in v]) if v and end in v[0] else None
    metrics=[json.loads(l) for l in (session/'capture_metrics.jsonl').read_text().splitlines()]
    if metrics:result['last_poll_statistics']={k:v for k,v in metrics[-1].items() if k.startswith('anchor_')}
    return result

def analyze(session,bag_data):
    session=pathlib.Path(session);v=read_video(session/'video_timestamps.csv');a=[json.loads(l) for l in (session/'anchors.jsonl').read_text().splitlines()]
    resource=[json.loads(l) for l in (session/'resources.jsonl').read_text().splitlines()];metrics=[json.loads(l) for l in (session/'capture_metrics.jsonl').read_text().splitlines()]
    origin=v[0]['raw_ns'];deltas=np.diff([x['raw_ns'] for x in v]);period=float(np.median(deltas[deltas>0]));events=[];seqcounts=collections.Counter()
    resource_times=[r['monotonic_ns'] for r in resource]
    for idx,(old,row) in enumerate(zip(v,v[1:]),start=2):
        kind,delta=sequence_kind(old['sequence'],row['sequence']);seqcounts[kind]+=1;dt=row['raw_ns']-old['raw_ns']
        if kind!='normal' or dt>1.5*period:
            k=min(max(bisect.bisect_right(resource_times,row['dq_after_ns']),1),len(resource)-1);r0,r1=resource[k-1:k+1];seconds=(r1['monotonic_ns']-r0['monotonic_ns'])/1e9
            cpu=np.subtract(r1['system_cpu_ticks'],r0['system_cpu_ticks']);dirty=r1['meminfo_kb']['Dirty']/1024
            events.append({'row':idx,'pair_id':row['pair_id'],'previous_sequence':old['sequence'],'sequence':row['sequence'],'classification':kind,'sequence_delta':delta,'missing_sequence_ids':delta-1 if kind=='gap' else 0,'gap_raw_start_ns':old['raw_ns'],'gap_raw_end_ns':row['raw_ns'],'relative_s':(row['raw_ns']-origin)/1e9,'observed_wall':wall(row['realtime_ns']),'raw_interval_ms':dt/1e6,'cadence_missing_periods_estimate':max(0,round(dt/period)-1),'dequeue_minus_raw_ms':(row['dq_after_ns']-row['raw_ns'])/1e6,'dq_call_ms':(row['dq_after_ns']-row['dq_before_ns'])/1e6,'resource_interval_s':seconds,'resource_bag_growth_MBps':(r1['bag_bytes']-r0['bag_bytes'])/seconds/1e6,'resource_system_cpu_percent':100*(1-(cpu[3]+cpu[4])/sum(cpu)),'resource_dirty_MiB':dirty,'resource_writeback_MiB':r1['meminfo_kb']['Writeback']/1024})
    gaps=[];invalid=[];identities=collections.Counter();protocol_errors=0;backwards=0;dup_host=0;dup_device=0;switches=0;epochs=0
    for idx,row in enumerate(a):
        identities[(row['writer_epoch'],row['write_sequence'])]+=1
        fields=struct.unpack('<IIQQQQQIIQ',bytes.fromhex(row['raw_hex']))
        decoded=(fields[2],fields[3],fields[4],fields[5],fields[6],fields[7],bool(fields[8]),fields[9]);claimed=tuple(row[k] for k in ['writer_epoch','write_sequence','imu_stamp_ns','host_monotonic_ns','update_monotonic_ns','clock_source','ready','uncertainty_ns'])
        protocol_errors+=int(fields[0]!=0x31414d49 or fields[1]!=1 or fields[3]&1 or decoded!=claimed)
        if row['validity']!='HOST_ARRIVAL_ANCHOR':invalid.append({'index':idx,'sequence':row['write_sequence'],'validity':row['validity'],'update_after_reader_ns':row['update_monotonic_ns']-row['reader_monotonic_ns'],'host_after_reader_ns':row['host_monotonic_ns']-row['reader_monotonic_ns']})
        if not idx:continue
        old=a[idx-1]
        if old['ready'] and row['ready']:
            epochs+=int(old['writer_epoch']!=row['writer_epoch']);switches+=int(old['clock_source']!=row['clock_source']);backwards+=int(row['host_monotonic_ns']<old['host_monotonic_ns'] or row['imu_stamp_ns']<old['imu_stamp_ns']);dup_host+=int(row['host_monotonic_ns']==old['host_monotonic_ns']);dup_device+=int(row['imu_stamp_ns']==old['imu_stamp_ns'])
        if row['skipped_updates']:
            nearest=min(events,key=lambda e:abs(e['gap_raw_end_ns']-row['reader_monotonic_ns']))
            gaps.append({'index':idx,'sequence_before':old['write_sequence'],'sequence_after':row['write_sequence'],'skipped_updates':row['skipped_updates'],'wall':wall(row['reader_realtime_ns']),'relative_s':(row['reader_monotonic_ns']-origin)/1e9,'reader_gap_ms':(row['reader_monotonic_ns']-old['reader_monotonic_ns'])/1e6,'host_span_ms':(row['host_monotonic_ns']-old['host_monotonic_ns'])/1e6,'device_span_ms':(row['imu_stamp_ns']-old['imu_stamp_ns'])/1e6,'publication_span_ms':(row['update_monotonic_ns']-old['update_monotonic_ns'])/1e6,'previous_ready':old['ready'],'nearest_video_event_pair_id':nearest['pair_id'],'from_nearest_video_gap_end_ms':(row['reader_monotonic_ns']-nearest['gap_raw_end_ns'])/1e6,'within_50ms_of_video_gap_end':abs(row['reader_monotonic_ns']-nearest['gap_raw_end_ns'])<=50000000})
    mapping=assess_anchor_coverage(v,a)
    streams={}
    for topic,rows in bag_data['streams'].items():
        t=[r['stamp_ns'] for r in rows];d=np.diff(t);seqd=[sequence_kind(x['seq'],y['seq'])[0] for x,y in zip(rows,rows[1:])]
        streams[topic]={'count':len(rows),'first_device_ns':t[0],'last_device_ns':t[-1],'first_bag_wall':wall(rows[0]['bag_ns']),'last_bag_wall':wall(rows[-1]['bag_ns']),'fps':(len(t)-1)*1e9/(t[-1]-t[0]),'interval_ms':stats(d/1e6),'backwards':int(sum(d<0)),'duplicates':int(sum(d==0)),'sequence_events':dict(collections.Counter(seqd))}
    diagnostics=collections.defaultdict(list)
    for row in bag_data['diagnostics']:diagnostics[row['values']['stream']].append(row)
    diag_summary={}
    for stream,rows in diagnostics.items():
        diag_summary[stream]={'count':len(rows),'time_types':dict(collections.Counter(r['values']['time_type'] for r in rows)),'clock_sources':dict(collections.Counter(r['values']['clock_source'] for r in rows)),'source_switch_counter_max':max(int(r['values']['clock_source_switch_count']) for r in rows),'queue_depths':dict(collections.Counter(int(r['values']['queue_depth']) for r in rows)),'startup_drain_counts':sorted(set(int(r['values']['startup_drain_count']) for r in rows)),'base_time_backwards':sum(int(b['values']['base_time'])<int(a['values']['base_time']) for a,b in zip(rows,rows[1:]))}
    ready=[r for r in a if r['ready']]
    return {'new_timing_evidence':timing_evidence(session),'source_session':str(session),'video':{'pairs':len(v),'sequence_events':dict(seqcounts),'missing_sequence_ids':sum(e['missing_sequence_ids'] for e in events),'cadence_missing_periods_estimate':sum(e['cadence_missing_periods_estimate'] for e in events),'physical_frame_count_from_sequence':'NOT_PROVEN; sequence skips and cadence estimates are different observations','events':events,'dq_minus_raw_ms':stats([(r['dq_after_ns']-r['raw_ns'])/1e6 for r in v]),'dq_call_ms':stats([(r['dq_after_ns']-r['dq_before_ns'])/1e6 for r in v]),'flags':dict(collections.Counter(r['flags'] for r in v))},'anchors':{'states':len(a),'skipped_updates':sum(g['skipped_updates'] for g in gaps),'gap_events':gaps,'max_consecutive_missing_updates':max(g['skipped_updates'] for g in gaps) if gaps else 0,'steady_state_missing_updates':sum(g['skipped_updates'] for g in gaps if g['previous_ready']),'duplicate_states':sum(n-1 for n in identities.values()),'protocol_errors':protocol_errors,'validity_counts':dict(collections.Counter(r['validity'] for r in a)),'invalid_states':invalid,'ready_epoch_changes':epochs,'ready_source_changes':switches,'ready_clock_backwards':backwards,'ready_host_duplicates':dup_host,'ready_device_duplicates':dup_device,'ready_host_gap_ms':stats(np.diff([r['host_monotonic_ns'] for r in ready])/1e6),'publication_delay_ms':stats([(r['update_monotonic_ns']-r['host_monotonic_ns'])/1e6 for r in ready]),'reader_minus_publication_ms':stats([(r['reader_monotonic_ns']-r['update_monotonic_ns'])/1e6 for r in ready])},'acceptance_A_anchor_history':{'status':'FAIL' if gaps else 'NO_OBSERVED_GAPS','entire_history_guaranteed':False},'acceptance_B_image_mapping':mapping,'streams':streams,'livox_diagnostics':diag_summary,'queue_peak_bytes':max(r['queue_peak_bytes'] for r in metrics),'physical_sync_verified':False,'raw_gprmc_recorded':False}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('session');ap.add_argument('--bag-evidence',required=True);ap.add_argument('--output',required=True);args=ap.parse_args();session=pathlib.Path(args.session).resolve();out=pathlib.Path(args.output).resolve()
    if out==session or session in out.parents:ap.error('output must be outside the original session')
    out.mkdir(parents=True,exist_ok=False)
    r=analyze(session,json.loads(pathlib.Path(args.bag_evidence).read_text()));(out/'analysis.json').write_text(json.dumps(r,indent=2))
    for name,rows in [('video_events',r['video']['events']),('anchor_gap_events',r['anchors']['gap_events'])]:
        with (out/(name+'.csv')).open('x') as f:
            wr=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['none']);wr.writeheader();wr.writerows(rows)
    print(json.dumps({k:r[k] for k in ['acceptance_A_anchor_history','acceptance_B_image_mapping','streams','livox_diagnostics','queue_peak_bytes']},indent=2))
if __name__=='__main__':main()
