#!/usr/bin/env python3
"""Raw clock audit and L2-B input summary. Deliberately does not implement L2-B."""
import argparse,collections,csv,json,pathlib,struct,time
import numpy as np
from analyze_real_session import read_video
FMT='<IIQQQQQIIQ'
def analyze(session):
    p=pathlib.Path(session);video=read_video(p/'video_timestamps.csv')
    anchors=[json.loads(l) for l in (p/'anchors.jsonl').read_text().splitlines() if l.strip()]
    epochs=collections.Counter();sources=collections.Counter();bad=0;changes=0;backwards=0;duplicates=0;jumps=0;stale=0;previous=None
    for a in anchors:
        raw=bytes.fromhex(a['raw_hex'])
        if len(raw)!=64:bad+=1;continue
        magic,version,epoch,seq,device,host,updated,source,ready,uncertainty=struct.unpack(FMT,raw)
        if magic!=0x31414d49 or version!=1 or seq&1:bad+=1
        if (epoch,seq,device,host,updated,source,bool(ready),uncertainty)!=(a['writer_epoch'],a['write_sequence'],a['imu_stamp_ns'],a['host_monotonic_ns'],a['update_monotonic_ns'],a['clock_source'],a['ready'],a['uncertainty_ns']):bad+=1
        epochs[epoch]+=1;sources[source]+=1
        if not ready or not host or a['reader_monotonic_ns']<host or a['reader_monotonic_ns']-host>100000000:stale+=1
        if previous and ready and previous['ready']:
            if epoch!=previous['writer_epoch'] or source!=previous['clock_source']:changes+=1
            else:
                dd=device-previous['imu_stamp_ns'];dh=host-previous['host_monotonic_ns']
                backwards+=int(dd<0 or dh<=0);duplicates+=int(dd==0)
                jumps+=int(abs(dd-dh)>max(20000000,uncertainty+previous['uncertainty_ns']))
        previous=a
    latency=[r['dq_after_ns']-r['raw_ns'] for r in video if r['timestamp_type']==0x2000]
    walloffset=[r['realtime_ns']-r['dq_after_ns'] for r in video]
    raw=[r['raw_ns'] for r in video];delta=np.diff(np.array(raw,dtype=np.int64))
    return {'sync_status':'SYNC_PENDING','mapping_implemented':False,'latest_anchor_age_at_last_video_ns':(video[-1]['dq_after_ns']-anchors[-1]['host_monotonic_ns']) if video and anchors else None,'anchor_stale_at_last_video':(not anchors or not anchors[-1]['ready'] or not anchors[-1]['host_monotonic_ns'] or (video and video[-1]['dq_after_ns']-anchors[-1]['host_monotonic_ns']>100000000)),'next_mapping_module':'Reuse SDK-independent laptop L2-B once available; adapt inputs below','video_timestamp_types':dict(collections.Counter(r['timestamp_type'] for r in video)),'video_timestamp_sources':dict(collections.Counter(r['timestamp_source'] for r in video)),'video_backwards':int(np.sum(delta<0)),'video_duplicates':int(np.sum(delta==0)),'v4l2_to_dequeue_ms':{'median':float(np.median(latency))/1e6,'max':max(latency)/1e6,'min':min(latency)/1e6} if latency else None,'wall_minus_monotonic_jump_over_20ms':int(np.sum(np.abs(np.diff(np.array(walloffset,dtype=np.int64)))>20000000)),'anchor_protocol_or_sidecar_errors':bad,'anchor_epochs':dict(epochs),'anchor_clock_sources':dict(sources),'anchor_epoch_or_source_changes':changes,'anchor_backwards':backwards,'anchor_duplicates':duplicates,'anchor_offset_jumps_over_uncertainty':jumps,'anchor_unready_or_stale_states':stale,'anchor_poll_skipped_states':sum(r.get('skipped_updates',0) for r in anchors),'contract':{'video_native_ns':'raw_ns; V4L2_TIMESTAMP_MONOTONIC (0x2000) permits same-clock identity to CLOCK_MONOTONIC, subject to driver semantics','video_event':'timestamp_source is EOF=0 or SOE=0x10000; never assume exposure center','host_pairs':'dq_before_ns/dq_after_ns/realtime_ns; wall sample is taken after DQBUF','anchors':'IMA1: device imu_stamp_ns paired with host_monotonic_ns at Livox SDK callback; transport latency remains; uncertainty is configured, not measured','zed_imu':'raw 64-byte HID and device_ticks; scale 39062.5 ns/tick; raw read before/after host clocks; do not reuse SDK timestamps','calibration':'UNKNOWN; no TF or identity extrinsics','physical_precision':'PENDING; IMU correlation does not validate image exposure synchronization'}}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('session');a=ap.parse_args();r=analyze(a.session);p=pathlib.Path(a.session)/('timestamp_audit_%d.json'%time.time_ns());p.write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
if __name__=='__main__':main()
