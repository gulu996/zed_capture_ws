#!/usr/bin/env python3
"""Read-only audit of capture v1 low-level sidecars; no hardware/ROS required.

Callback arrivals are user-space observations, never USB hardware timestamps.
libusb completion outcomes are NOT counts of physical USB packets.
"""
import argparse
import csv
import errno
import json
from pathlib import Path


def rows(path):
    with path.open() as f:
        parsed=list(csv.DictReader(f))
    if any(None in r or any(v is None for v in r.values()) for r in parsed):
        raise ValueError('incomplete CSV row: '+path.name)
    return [{k:int(v) for k,v in r.items()} for r in parsed]


def audit(session):
    session=Path(session)
    summary=json.loads((session/'capture_summary.json').read_text())
    result={'status':'UNAVAILABLE_IN_LEGACY_SESSION','errors':[],
            'usb_physical_packet_loss':'UNKNOWN','firmware_internal_state':'UNKNOWN',
            'interpretation':'libusb arrival is callback entry; transfer statuses are completion outcomes, not physical packets'}
    if not summary.get('low_level_diagnostics_version'):
        return result
    errors=result['errors']
    try:
        if summary['low_level_diagnostics_version']!=1:
            raise ValueError('unsupported diagnostic version')
        v=rows(session/'video_io_events.csv');h=rows(session/'hid_io_events.csv')
        if not v or not h:errors.append('empty low-level event history')
        for data,key,count_key in [(v,'event_id','video_io_events_written'),(h,'read_id','hid_io_events_written')]:
            if [r[key] for r in data]!=list(range(1,len(data)+1)):errors.append(key+' missing/duplicate/reset')
            if summary.get(count_key)!=len(data):errors.append(count_key+' summary/sidecar mismatch')
        with (session/'video_timestamps.csv').open() as f:rawv=list(csv.DictReader(f))
        observed=[(r['pair_id'],r['sequence'],r['v4l2_sec']*10**9+r['v4l2_usec']*1000,r['flags']) for r in v if r['pair_id']]
        expected=[tuple(int(r[k]) for k in ['pair_id','sequence','raw_ns','flags']) for r in rawv]
        if observed!=expected:errors.append('video event/raw metadata mismatch')
        with (session/'zed_imu_raw.csv').open() as f:rawh=list(csv.DictReader(f))
        positives=[r for r in h if r['result']>0]
        if [(r['sample_id'],r['read_after_ns']) for r in positives]!=[(int(r['sample_id']),int(r['read_after_ns'])) for r in rawh]:
            errors.append('HID event/raw metadata mismatch')
        # Cross-check the actual bytes, not a presumed 64-byte report length.
        # ZED 2i in the reference session returns 62 bytes per report.
        for r,raw in zip(positives,rawh):
            payload=bytes.fromhex(raw['raw_hex'])
            if len(payload)!=r['result']:errors.append('HID report length mismatch')
            if r['tick_present'] and (len(payload)<10 or int.from_bytes(payload[2:10],'little')!=r['device_ticks']):errors.append('HID tick mismatch')
        for r in v:
            if r['select_after_ns']<r['select_before_ns'] or r['iteration_end_ns']<r['select_after_ns']:errors.append('video observation clock reversal')
            if r['select_result']<=0 and (r['dq_called'] or r['qbuf_called']):errors.append('invalid video syscall event order')
        for r in h:
            if r['read_after_ns']<r['read_before_ns']:errors.append('HID observation clock reversal')
            if r['completed_reports']!=r['consumed_reports']+r['queue_discards']+r['queue_depth']:errors.append('HID queue accounting mismatch')
            if r['result']>0 and not (0<r['libusb_arrival_monotonic_ns']<=r['dequeue_monotonic_ns']<=r['read_after_ns']):errors.append('HID callback/dequeue time invalid')
        def peak(data,key):return max((r[key] for r in data),default=0)
        def max_difference(data,end,start):return max((r[end]-r[start] for r in data if r[start] and r[end]),default=0)
        video={'events':len(v),'successful_frames':len(observed),
               'select_timeouts':sum(r['select_result']==0 for r in v),
               'select_eintr':sum(r['select_result']<0 and r['select_errno']==errno.EINTR for r in v),
               'select_fatal_errors':sum(r['select_result']<0 and r['select_errno']!=errno.EINTR for r in v),
               'dq_eagain':sum(r['dq_called'] and r['dq_result']<0 and r['dq_errno']==errno.EAGAIN for r in v),
               'dq_fatal_errors':sum(r['dq_called'] and r['dq_result']<0 and r['dq_errno'] not in (errno.EAGAIN,errno.EINTR) for r in v),
               'qbuf_errors':sum(r['qbuf_called'] and r['qbuf_result']!=0 for r in v),
               'max_select_ns':max_difference(v,'select_after_ns','select_before_ns'),
               'max_dq_lock_wait_ns':max_difference(v,'dq_ioctl_start_ns','dq_before_ns'),
               'max_dq_ioctl_ns':max_difference(v,'dq_after_ns','dq_ioctl_start_ns'),
               'max_qbuf_lock_wait_ns':max_difference(v,'qbuf_ioctl_start_ns','qbuf_before_ns'),
               'max_qbuf_ioctl_ns':max_difference(v,'qbuf_end_ns','qbuf_ioctl_start_ns'),
               'max_between_iterations_ns':max((b['select_before_ns']-a['iteration_end_ns'] for a,b in zip(v,v[1:])),default=0),
               'nonframe_events':[r for r in v if not r['pair_id']]}
        gaps=[];previous=None;between=[]
        for r in v:
            if not r['pair_id']:
                between.append(r);continue
            if previous:
                delta=(r['sequence']-previous['sequence'])&0xffffffff
                dt=(r['v4l2_sec']-previous['v4l2_sec'])*10**9+(r['v4l2_usec']-previous['v4l2_usec'])*1000
                if delta!=1 or dt>50000000 or dt<=0:
                    gaps.append({'pair_id':r['pair_id'],'raw_interval_ns':dt,'sequence_delta':delta,
                                 'classification':'duplicate' if delta==0 else ('reset_or_backward' if delta>=0x80000000 else 'forward_gap' if delta>1 else 'timestamp_interval'),
                                 'driver_ids_missing':delta-1 if 1<delta<0x80000000 else 0,
                                 'prior_qbuf_ns':previous['qbuf_end_ns'],'select_start_ns':r['select_before_ns'],
                                 'intervening_events':between,'successful_event':r})
            previous=r;between=[]
        video['gap_events']=gaps
        hid={k:peak(h,k) for k in ['completed_reports','consumed_reports','queue_discards','queue_peak','transfer_completed','transfer_error','transfer_timed_out','transfer_cancelled','transfer_stall','transfer_no_device','transfer_overflow','submit_errors','event_loop_errors','read_timeouts','read_errors']}
        hid.update(events=len(h),positive_reports=len(positives),last_observed_queue_depth=h[-1]['queue_depth'] if h else None,
                   max_read_ns=max_difference(h,'read_after_ns','read_before_ns'),
                   max_callback_to_dequeue_ns=max_difference(h,'dequeue_monotonic_ns','libusb_arrival_monotonic_ns'),
                   max_raw_callback_ns=max_difference(h,'raw_callback_end_ns','read_after_ns'),
                   timeouts_or_errors=[r for r in h if r['result']<=0],
                   tick_or_host_gap_events=[r for r in h if (r['had_previous_tick'] and r['tick_present'] and (r['tick_delta']<=0 or r['tick_delta']>96)) or r['host_interval_ns']>5000000])
        # Above tick threshold is the unchanged 1.5 x nominal 64-tick cadence;
        # it annotates evidence, not a replacement acceptance threshold.
        if any(video[k] for k in ['select_fatal_errors','dq_fatal_errors','qbuf_errors']):errors.append('observed fatal V4L2 I/O error')
        if hid['queue_discards']:errors.append('observed HIDAPI queue discard')
        if any(hid[k] for k in ['transfer_error','transfer_stall','transfer_no_device','transfer_overflow','submit_errors','event_loop_errors','read_errors']):errors.append('observed HID transfer/read error (not physical packet count)')
        result.update(video=video,hid=hid)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        errors.append(str(exc))
    result['errors']=sorted(set(errors));result['status']='FAIL' if errors else 'OBSERVED_COMPLETE'
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('session');ap.add_argument('--output');args=ap.parse_args()
    result=audit(args.session);text=json.dumps(result,indent=2)
    if args.output:
        with open(args.output,'x') as f:f.write(text+'\n')
    else:print(text)
    raise SystemExit(2 if result['status']=='FAIL' else 0)
