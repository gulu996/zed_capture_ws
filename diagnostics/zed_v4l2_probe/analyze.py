#!/usr/bin/env python3
"""Read-only metadata analysis for historical A and metadata-only B. No bag reads."""
import csv,json,math,pathlib,statistics,sys
ROOT=pathlib.Path(__file__).resolve().parent
BASE=pathlib.Path('/home/jetson/zed_capture_data/20261017_144432_c0112f6c')
MODES={'HD1080':(3840,1080),'HD720':(2560,720)}

def native_mode_evidence(run,mode):
    """Fail closed on missing/mismatched enumeration or negotiated readback."""
    width,height=MODES[mode];fourcc=int.from_bytes(b'YUYV','little')
    try:
        enum=json.loads((run/'v4l2_enumeration.json').read_text())
        fmt=json.loads((run/'v4l2_negotiated.json').read_text())
        enumerated=(enum['requested']==mode and enum['width']==width and enum['height']==height
            and enum['pixel_format']=='YUYV' and enum['enumeration_complete'] and enum['requested_mode_enumerated']
            and any(x['result']==0 and x['fourcc']==fourcc for x in enum['VIDIOC_ENUM_FMT'])
            and any(x['result']==0 and x['type']==1 and x.get('width')==width and x.get('height')==height for x in enum['VIDIOC_ENUM_FRAMESIZES'])
            and any(x['result']==0 and x['type']==1 and x.get('denominator',0)>0 and x.get('numerator',0)>0
                and abs(x['numerator']*1e9/x['denominator']-1e9/30)<=100 for x in enum['VIDIOC_ENUM_FRAMEINTERVALS']))
        negotiated=(fmt['format_result']==fmt['parm_result']==0 and fmt['width']==width and fmt['height']==height
            and fmt['fourcc']==fourcc and fmt['stride']==width*2 and fmt['sizeimage']==width*height*2
            and fmt['interval_numerator']>0 and fmt['interval_denominator']==30*fmt['interval_numerator'])
        return {'enumerated':enumerated,'negotiated':negotiated,'verified':enumerated and negotiated}
    except (OSError,ValueError,KeyError,TypeError) as e:
        return {'verified':False,'error':str(e)}
def read(p):
    with pathlib.Path(p).open() as f:return [{k:int(v) for k,v in r.items()} for r in csv.DictReader(f)]
def pct(values,p):
    if not values:return None
    a=sorted(values);x=(len(a)-1)*p/100;i=int(x);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(x-i)
def describe(v):return {'min':min(v),'median':pct(v,50),'p95':pct(v,95),'p99':pct(v,99),'max':max(v)} if v else None
def metrics(rows):
    frames=[r for r in rows if r['pair_id']];dt=[];gaps=[];missing=duplicate=reset=0
    for a,b in zip(frames,frames[1:]):
        ns=(b['v4l2_sec']-a['v4l2_sec'])*10**9+(b['v4l2_usec']-a['v4l2_usec'])*1000;dt.append(ns)
        d=(b['sequence']-a['sequence'])&0xffffffff
        if 1<d<0x80000000:missing+=d-1
        elif d==0:duplicate+=1
        elif d>=0x80000000:reset+=1
        if d!=1 or ns>50000000 or ns<=0:gaps.append({'pair_id':b['pair_id'],'previous_sequence':a['sequence'],'sequence':b['sequence'],'delta':d,'interval_ns':ns})
    total=sum(dt);wall=rows[-1]['iteration_end_ns']-rows[0]['select_before_ns'] if rows else 0
    result={'events':len(rows),'frames':len(frames),'video_span_s':total/1e9,'fps':(len(frames)-1)*1e9/total if total>0 else None,
       'interval_ms':describe([d/1e6 for d in dt]),'long_intervals':sum(d>50000000 for d in dt),'timestamp_backwards':sum(d<0 for d in dt),'timestamp_duplicates':sum(d==0 for d in dt),
       'driver_sequence_missing':missing,'sequence_duplicate':duplicate,'sequence_reset_or_backward':reset,'gaps':gaps,'select_timeouts':sum(r['select_result']==0 for r in rows),
       'startup_select_timeouts':sum(r['select_result']==0 and r['event_id']<(frames[0]['event_id'] if frames else math.inf) for r in rows),
       'select_errors':sum(r['select_result']<0 for r in rows),'dq_eagain':sum(r['dq_called'] and r['dq_result']<0 and r['dq_errno']==11 for r in rows),
       'dq_other_errors':sum(r['dq_called'] and r['dq_result']<0 and r['dq_errno']!=11 for r in rows),
       'qbuf_errors':sum(r['qbuf_called'] and r['qbuf_result']!=0 for r in rows),
       'event_ids_contiguous':[r['event_id'] for r in rows]==list(range(1,len(rows)+1)),
       'loop_cpu_percent_one_core_100':sum(r['iteration_cpu_ns'] for r in rows)*100/wall if wall>0 else None,
       'physical_exposures_missing':'UNKNOWN','select_wait_is_scheduler_latency':False}
    return result
def historical():
    rows=read(BASE/'video_io_events.csv');v=read(BASE/'video_timestamps.csv');vmap={r['pair_id']:r for r in v};byid={r['pair_id']:r for r in rows if r['pair_id']}
    resources=[json.loads(s) for s in (BASE/'resources.jsonl').read_text().splitlines()];events=[]
    pairs=[g['pair_id'] for g in metrics(rows)['gaps']]
    for pid in pairs:
        a,b=byid[pid-1],byid[pid];f=vmap[pid]
        # Return all boundaries, including the prior frame processing interval.
        ms=lambda x:x/1e6
        event={'pair_id':pid,'previous_event':a,'current_event':b,'previous_video':vmap[pid-1],'current_video':f,
          'qbuf_to_select_ms':ms(b['select_before_ns']-a['qbuf_end_ns']),
          'iteration_gap_ms':ms(b['select_before_ns']-a['iteration_end_ns']),
          'select_wait_ms':ms(b['select_after_ns']-b['select_before_ns']),
          'select_to_dq_ms':ms(b['dq_before_ns']-b['select_after_ns']),
          'dq_lock_wait_ms':ms(b['dq_ioctl_start_ns']-b['dq_before_ns']),
          'dq_ioctl_ms':ms(b['dq_after_ns']-b['dq_ioctl_start_ns']),
          'callback_wall_ms':ms(b['callback_end_ns']-b['dq_after_ns']),
          'callback_cpu_ms':ms(b['callback_cpu_ns']),
          'previous_callback_wall_ms':ms(a['callback_end_ns']-a['dq_after_ns']),
          'previous_callback_cpu_ms':ms(a['callback_cpu_ns']),
          'qbuf_ioctl_ms':ms(b['qbuf_end_ns']-b['qbuf_ioctl_start_ns']),
          'writer_queue_ms':ms(f['writer_begin_ns']-f['copied_ns']),
          'writer_ms':ms(f['writer_end_ns']-f['writer_begin_ns']),
          'intervening_nonframe_events':[r for r in rows if a['event_id']<r['event_id']<b['event_id']]}
        lo=a['dq_after_ns'];hi=b['dq_after_ns']
        event['overlapping_writer_jobs']=[{'pair_id':r['pair_id'],'start_ns':r['writer_begin_ns'],'end_ns':r['writer_end_ns'],'duration_ms':ms(r['writer_end_ns']-r['writer_begin_ns'])} for r in v if r['writer_begin_ns']<=hi and r['writer_end_ns']>=lo]
        for old,new in zip(resources,resources[1:]):
            if old['monotonic_ns']<=hi<=new['monotonic_ns']:
                d=[y-x for x,y in zip(old['system_cpu_ticks'],new['system_cpu_ticks'])]
                event['resource_window']={'start_ns':old['monotonic_ns'],'end_ns':new['monotonic_ns'],'duration_s':(new['monotonic_ns']-old['monotonic_ns'])/1e9,
                    'cpu_percent':100*(1-(d[3]+d[4])/sum(d)),'meminfo_kb':new['meminfo_kb'],'bag_growth_MBps':(new['bag_bytes']-old['bag_bytes'])*1000/(new['monotonic_ns']-old['monotonic_ns'])};break
        events.append(event)
    check=json.loads((BASE/'check_result.json').read_text());summary=json.loads((BASE/'capture_summary.json').read_text())
    return {'source':str(BASE),'metrics':metrics(rows),'events':events,'summary':summary,'resource_summary':check.get('resources'),
      'max_writer_ms':max(r['writer_end_ns']-r['writer_begin_ns'] for r in v)/1e6,
      'max_queue_wait_ms':max(r['writer_begin_ns']-r['copied_ns'] for r in v)/1e6,
      'flags':sorted({r['flags'] for r in rows if r['pair_id']}),'bytesused':sorted({r['bytesused'] for r in v}),
      'bag_bytes':(BASE/'data.bag').stat().st_size}
def comparison(run):
    run=pathlib.Path(run);a=json.loads((ROOT/'evidence/baseline_A.json').read_text())['metrics'];b=metrics(read(run/'video_io_events.csv'))
    session=json.loads((run/'session.json').read_text()) if (run/'session.json').exists() else {}
    mode=session.get('resolution_mode','HD1080');width,height=MODES[mode]
    end=json.loads((run/'probe_end.json').read_text());good=end['returncode']==0 and end['buffers']==4 and end['completed_duration'] and not end['overflow'] and not end['fatal_io'] and b['event_ids_contiguous'] and b['video_span_s']>=29
    b['invalid_payload_metadata']=sum(not r.get('payload_valid') or r.get('bytesused')!=width*height*2 or r.get('width')!=width or r.get('height')!=height or r.get('stride')!=width*2 or (r.get('flags',0)&64)!=0 for r in read(run/'video_io_events.csv') if r['pair_id'])
    native=native_mode_evidence(run,mode)
    if mode=='HD720':
        good=good and native['verified'] and end.get('resolution_mode')==mode and end.get('negotiated_verified',False) and end.get('after_settings_verified',False) and session.get('resolution')==[width,height]
    b['pixel_content_inspected']=False
    result={'A':a,'B':b,'probe_run':end,'low_load_runtime':'PASS' if good else 'FAIL',
            'observed_continuity':'PASS' if good and not any(b[k] for k in ['long_intervals','driver_sequence_missing','sequence_duplicate','sequence_reset_or_backward','timestamp_backwards','timestamp_duplicates','invalid_payload_metadata']) else 'FAIL',
            'interpretation':'A/B changes total system load and callback path together; cannot isolate disk as sole cause.',
            'physical_sync':'PENDING','images_saved':False}
    result.update(resolution_mode=mode,resolution=[width,height],native_mode_evidence=native)
    if mode=='HD720':
        result.update(NATIVE_720P_SUPPORTED='VERIFIED' if native['verified'] else 'UNVERIFIED',
            LOW_LOAD_720P_RUNTIME=result['low_load_runtime'],LOW_LOAD_720P_CONTINUITY=result['observed_continuity'],JPEG_REALTIME_PENDING=True)
        result['interpretation']='720P native metadata-only experiment; historical A is 1080P with joint recording, not a controlled same-resolution load comparison.'
    if good and any(60000000<=g['interval_ns']<=75000000 for g in b['gaps']):result['inference']='66.9ms-like gaps persist without this process writing YUYV/rosbag; high-throughput rosbag is not necessary if ambient-load log confirms no concurrent recorder. Cause still unresolved.'
    elif good:result['inference']='No 60-75ms gap observed in this 30s run; does not prove permanent fix or disk-only causality.'
    with (run/'comparison.json').open('x') as f:json.dump(result,f,indent=2)
    return result
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--historical':
        r=historical()
        with (ROOT/'evidence/baseline_A.json').open('x') as f:json.dump(r,f,indent=2)
        with (ROOT/'evidence/eight_event_timing.csv').open('x') as f:
            fields=['pair_id','qbuf_to_select_ms','iteration_gap_ms','select_wait_ms','select_to_dq_ms','dq_lock_wait_ms','dq_ioctl_ms','previous_callback_wall_ms','previous_callback_cpu_ms','callback_wall_ms','callback_cpu_ms','qbuf_ioctl_ms','writer_queue_ms','writer_ms'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:e[k] for k in fields} for e in r['events'])
        print(json.dumps(r['metrics'],indent=2))
    else:print(json.dumps(comparison(sys.argv[1]),indent=2))
