"""Strict low-level audit, streaming joins; thresholds unchanged."""
import errno,json,pathlib
from checker_streams import csv_rows

def audit(session,store):
 s=pathlib.Path(session);summary=json.loads((s/'capture_summary.json').read_text());result={'status':'UNAVAILABLE_IN_LEGACY_SESSION','errors':[],'usb_physical_packet_loss':'UNKNOWN','firmware_internal_state':'UNKNOWN','interpretation':'libusb arrival is callback entry; transfer statuses are completion outcomes, not physical packets'}
 if not summary.get('low_level_diagnostics_version'):return result
 errors=set()
 try:
  if summary['low_level_diagnostics_version']!=1:raise ValueError('unsupported diagnostic version')
  v={k:0 for k in ['events','successful_frames','select_timeouts','select_eintr','select_fatal_errors','dq_eagain','dq_fatal_errors','qbuf_errors','max_select_ns','max_dq_lock_wait_ns','max_dq_ioctl_ns','max_qbuf_lock_wait_ns','max_qbuf_ioctl_ns','max_between_iterations_ns']};v['nonframe_events']=store.seq();v['gap_events']=store.seq()
  raw=iter(csv_rows(s/'video_timestamps.csv'));previous=None;lastiteration=None;between=store.seq()
  for r in csv_rows(s/'video_io_events.csv',True):
   v['events']+=1
   if r['event_id']!=v['events']:errors.add('event_id missing/duplicate/reset')
   if r['select_after_ns']<r['select_before_ns'] or r['iteration_end_ns']<r['select_after_ns']:errors.add('video observation clock reversal')
   if r['select_result']<=0 and (r['dq_called'] or r['qbuf_called']):errors.add('invalid video syscall event order')
   for k,flag in [('select_timeouts',r['select_result']==0),('select_eintr',r['select_result']<0 and r['select_errno']==errno.EINTR),('select_fatal_errors',r['select_result']<0 and r['select_errno']!=errno.EINTR),('dq_eagain',r['dq_called'] and r['dq_result']<0 and r['dq_errno']==errno.EAGAIN),('dq_fatal_errors',r['dq_called'] and r['dq_result']<0 and r['dq_errno'] not in (errno.EAGAIN,errno.EINTR)),('qbuf_errors',r['qbuf_called'] and r['qbuf_result']!=0)]:v[k]+=int(bool(flag))
   for key,end,start in [('max_select_ns','select_after_ns','select_before_ns'),('max_dq_lock_wait_ns','dq_ioctl_start_ns','dq_before_ns'),('max_dq_ioctl_ns','dq_after_ns','dq_ioctl_start_ns'),('max_qbuf_lock_wait_ns','qbuf_ioctl_start_ns','qbuf_before_ns'),('max_qbuf_ioctl_ns','qbuf_end_ns','qbuf_ioctl_start_ns')]:
    if r[start] and r[end]:v[key]=max(v[key],r[end]-r[start])
   if lastiteration is not None:v['max_between_iterations_ns']=max(v['max_between_iterations_ns'],r['select_before_ns']-lastiteration)
   lastiteration=r['iteration_end_ns']
   if not r['pair_id']:
    v['nonframe_events'].append(r);between.append(r)
    if len(between)>512:raise ValueError('FULL_STRICT nonframe burst budget exceeded; raw history retained')
    continue
   v['successful_frames']+=1;rawrow=next(raw,None)
   if rawrow is None or (r['pair_id'],r['sequence'],r['v4l2_sec']*10**9+r['v4l2_usec']*1000,r['flags'])!=tuple(int(rawrow[k]) for k in ['pair_id','sequence','raw_ns','flags']):errors.add('video event/raw metadata mismatch')
   if previous:
    delta=(r['sequence']-previous['sequence'])&0xffffffff;dt=(r['v4l2_sec']-previous['v4l2_sec'])*10**9+(r['v4l2_usec']-previous['v4l2_usec'])*1000
    if delta!=1 or dt>50000000 or dt<=0:
     # Nonframe bursts are disk-backed too; no arbitrary diagnostic truncation.
     v['gap_events'].append({'pair_id':r['pair_id'],'raw_interval_ns':dt,'sequence_delta':delta,'classification':'duplicate' if delta==0 else ('reset_or_backward' if delta>=0x80000000 else 'forward_gap' if delta>1 else 'timestamp_interval'),'driver_ids_missing':delta-1 if 1<delta<0x80000000 else 0,'prior_qbuf_ns':previous['qbuf_end_ns'],'select_start_ns':r['select_before_ns'],'intervening_events':list(between),'successful_event':r})
   previous=r
   # Reuse one temporary table instead of allocating one table per frame.
   store.db.execute('DELETE FROM '+between.name);between.n=0
  if next(raw,None) is not None:errors.add('video event/raw metadata mismatch')
  raw.close()
  if summary.get('video_io_events_written')!=v['events']:errors.add('video_io_events_written summary/sidecar mismatch')
  h={k:0 for k in ['completed_reports','consumed_reports','queue_discards','queue_peak','transfer_completed','transfer_error','transfer_timed_out','transfer_cancelled','transfer_stall','transfer_no_device','transfer_overflow','submit_errors','event_loop_errors','read_timeouts','read_errors']};peaks=list(h)
  h.update(events=0,positive_reports=0,last_observed_queue_depth=None,max_read_ns=0,max_callback_to_dequeue_ns=0,max_raw_callback_ns=0,timeouts_or_errors=store.seq(),tick_or_host_gap_events=store.seq());raw=iter(csv_rows(s/'zed_imu_raw.csv'))
  for r in csv_rows(s/'hid_io_events.csv',True):
   h['events']+=1
   if r['read_id']!=h['events']:errors.add('read_id missing/duplicate/reset')
   for k in peaks:h[k]=max(h[k],r[k])
   h['last_observed_queue_depth']=r['queue_depth']
   for k,end,start in [('max_read_ns','read_after_ns','read_before_ns'),('max_callback_to_dequeue_ns','dequeue_monotonic_ns','libusb_arrival_monotonic_ns'),('max_raw_callback_ns','raw_callback_end_ns','read_after_ns')]:
    if r[start] and r[end]:h[k]=max(h[k],r[end]-r[start])
   if r['read_after_ns']<r['read_before_ns']:errors.add('HID observation clock reversal')
   if r['completed_reports']!=r['consumed_reports']+r['queue_discards']+r['queue_depth']:errors.add('HID queue accounting mismatch')
   if r['result']>0:
    h['positive_reports']+=1;rr=next(raw,None)
    if rr is None or (r['sample_id'],r['read_after_ns'])!=(int(rr['sample_id']),int(rr['read_after_ns'])):errors.add('HID event/raw metadata mismatch')
    if rr is not None:
     payload=bytes.fromhex(rr['raw_hex'])
     if len(payload)!=r['result']:errors.add('HID report length mismatch')
     if r['tick_present'] and (len(payload)<10 or int.from_bytes(payload[2:10],'little')!=r['device_ticks']):errors.add('HID tick mismatch')
    if not (0<r['libusb_arrival_monotonic_ns']<=r['dequeue_monotonic_ns']<=r['read_after_ns']):errors.add('HID callback/dequeue time invalid')
   else:h['timeouts_or_errors'].append(r)
   if (r['had_previous_tick'] and r['tick_present'] and (r['tick_delta']<=0 or r['tick_delta']>96)) or r['host_interval_ns']>5000000:h['tick_or_host_gap_events'].append(r)
  if next(raw,None) is not None:errors.add('HID event/raw metadata mismatch')
  raw.close()
  if summary.get('hid_io_events_written')!=h['events']:errors.add('hid_io_events_written summary/sidecar mismatch')
  if not v['events'] or not h['events']:errors.add('empty low-level event history')
  if any(v[k] for k in ['select_fatal_errors','dq_fatal_errors','qbuf_errors']):errors.add('observed fatal V4L2 I/O error')
  if h['queue_discards']:errors.add('observed HIDAPI queue discard')
  if any(h[k] for k in ['transfer_error','transfer_stall','transfer_no_device','transfer_overflow','submit_errors','event_loop_errors','read_errors']):errors.add('observed HID transfer/read error (not physical packet count)')
  result.update(video=v,hid=h)
 except (OSError,ValueError,KeyError,TypeError) as exc:errors.add(str(exc))
 result['errors']=sorted(errors);result['status']='FAIL' if errors else 'OBSERVED_COMPLETE';return result
