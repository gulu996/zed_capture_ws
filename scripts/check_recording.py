#!/usr/bin/env python3
"""Read and deserialize every bag record; no roscore, hardware or map required."""
import argparse,collections,csv,json,math,pathlib,sys,time
import numpy as np
import rosbag
from analyze_real_session import read_video, assess_anchor_coverage, timing_evidence
from analyze_io_diagnostics import audit as audit_io
LEFT='/zed2i/left/image_raw';RIGHT='/zed2i/right/image_raw';ZI='/zed2i/imu/data_raw';LI='/livox/imu';LIDAR='/livox/lidar'
REQUIRED=[LEFT,RIGHT,ZI,LI,LIDAR,'/zed2i/video_stamp','/zed2i/imu_stamp','/zed2i/diagnostics']
def continuity(ts):
    if len(ts)<2:return {'count':len(ts),'fps':None,'backwards':0,'duplicates':0,'long_intervals':0}
    d=np.diff(np.array(ts,dtype=np.int64));positive=d[d>0];median=float(np.median(positive)) if len(positive) else 0
    return {'count':len(ts),'fps':(len(ts)-1)*1e9/(ts[-1]-ts[0]) if ts[-1]>ts[0] else None,'duration_s':(ts[-1]-ts[0])/1e9,'backwards':int(np.sum(d<0)),'duplicates':int(np.sum(d==0)),'median_interval_ms':median/1e6,'max_interval_ms':float(d.max())/1e6,'long_intervals':int(np.sum(d>median*1.5)) if median else 0}
def resources(session):
    p=session/'resources.jsonl'
    if not p.exists():return {'status':'PENDING'}
    rows=[json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    if len(rows)<2:return {'status':'PENDING'}
    peak_cpu=0.;peak_rss=0;peak_write=0.;peak_dirty=0;system_cpu=[]
    previous={}
    for row in rows:
        cpu=0;rss=0;write=0
        for pid,v in row['pids'].items():
            rss+=v['rss_bytes']
            if pid in previous:
                old,t=previous[pid];dt=(row['monotonic_ns']-t)/1e9
                if dt>0:cpu+=(v['cpu_ticks']-old['cpu_ticks'])/row['clock_ticks_per_second']/dt*100;write+=(v['write_bytes']-old['write_bytes'])/dt/1e6
            previous[pid]=(v,row['monotonic_ns'])
        peak_cpu=max(peak_cpu,cpu);peak_rss=max(peak_rss,rss);peak_write=max(peak_write,write);peak_dirty=max(peak_dirty,row.get('meminfo_kb',{}).get('Dirty',0))
    for old,new in zip(rows,rows[1:]):
        if 'system_cpu_ticks' in old and 'system_cpu_ticks' in new:
            d=[b-a for a,b in zip(old['system_cpu_ticks'],new['system_cpu_ticks'])]
            if sum(d)>0:system_cpu.append(100*(1-(d[3]+d[4])/sum(d)))
    dt=(rows[-1]['monotonic_ns']-rows[0]['monotonic_ns'])/1e9
    gpu=[r['gpu_load_raw_0_to_1000']/10 for r in rows if 'gpu_load_raw_0_to_1000' in r]
    return {'status':'OBSERVED','children_peak_cpu_percent_one_core_100':peak_cpu,'children_peak_rss_mb':peak_rss/1e6,'system_peak_cpu_percent':max(system_cpu) if system_cpu else None,'gpu_peak_load_percent':max(gpu) if gpu else None,'peak_block_write_MBps':peak_write,'bag_growth_MBps':(rows[-1]['bag_bytes']-rows[0]['bag_bytes'])/1e6/dt,'peak_dirty_mb':peak_dirty/1024,'note':'block writes may lag due to page cache; capture node fsyncs the closed bag; reused Livox process is not included in owned-child CPU figures'}
def check(session):
    session=pathlib.Path(session);errors=[];counts=collections.Counter();times=collections.defaultdict(list);keys=collections.defaultdict(list);valid_video=[];anchor_bag=[]
    mid_types=set();mid_switches=set();cloud_points=0;cloud_bad=0;cloud_empty=0;cloud_seq_gaps=0;previous_seq=None;invalid_buffers=0;bad_image=0;video_sequence_bad=0;video_previous=None;imu_decisions_bag=[]
    meta=json.loads((session/'session.json').read_text()) if (session/'session.json').exists() else {}
    synthetic=bool(meta.get('synthetic_fixture'));cfg=meta.get('config',{});file_mode=cfg.get('storage_mode')=='jpeg_files';file_result=None;wanted=(1920,1080) if cfg.get('resolution','HD1080')=='HD1080' else (1280,720)
    if synthetic:wanted=tuple(meta['fixture_dimensions'])
    bags=sorted(session.glob('*.bag'));bag_read_ok=False;start=time.monotonic();byte_count=0
    if not bags:errors.append('no finalized bag')
    if list(session.glob('*.active')):errors.append('unfinished .active file')
    try:
        for path in bags:
            byte_count+=path.stat().st_size
            with rosbag.Bag(str(path),'r') as bag:
                for topic,msg,received in bag.read_messages():
                    counts[topic]+=1
                    if file_mode and msg._type in ['sensor_msgs/Image','sensor_msgs/CompressedImage']:errors.append('C5F bag contains image payload')
                    if hasattr(msg,'header'):times[topic].append(msg.header.stamp.to_nsec())
                    if topic in [LEFT,RIGHT]:
                        keys[topic].append((msg.header.seq,msg.header.stamp.to_nsec()))
                        if (msg.width,msg.height)!=wanted or msg.encoding!='8UC2' or msg.step!=msg.width*2 or len(msg.data)!=msg.step*msg.height:bad_image+=1
                    elif topic=='/zed2i/video_stamp':
                        if video_previous is not None and (msg.v4l2_sequence-video_previous)&0xffffffff!=1:video_sequence_bad+=1
                        video_previous=msg.v4l2_sequence
                        if msg.payload_valid:valid_video.append((msg.v4l2_sequence,msg.header.stamp.to_nsec()))
                        else:invalid_buffers+=1
                        if msg.header.stamp.to_nsec()!=msg.v4l2_sec*1000000000+msg.v4l2_usec*1000:errors.append('video raw timestamp/header mismatch')
                    elif topic=='/livox_lidar_publisher2/timestamp_diagnostics':
                        for status in msg.status:
                            vals={v.key:v.value for v in status.values};mid_types.add(vals.get('time_type','UNKNOWN'));mid_switches.add(vals.get('clock_source_switch_count','UNKNOWN'))
                    elif topic=='/zed2i/time_anchor':anchor_bag.append((msg.writer_epoch,msg.write_sequence,bytes(msg.raw_state).hex()))
                    elif topic=='/zed2i/imu/time_validity':imu_decisions_bag.append(json.loads(msg.data))
                    elif topic==LIDAR:
                        if msg._type!='livox_ros_driver2/CustomMsg':errors.append('wrong Livox type');continue
                        cloud_points+=len(msg.points)
                        if msg.point_num!=len(msg.points) or msg.header.stamp.to_nsec()!=msg.timebase:cloud_bad+=1
                        if not msg.points:cloud_empty+=1
                        if previous_seq is not None:
                            delta=(msg.header.seq-previous_seq)&0xffffffff
                            if delta!=1:cloud_seq_gaps+=1
                        previous_seq=msg.header.seq
        bag_read_ok=bool(bags)
    except Exception as e:errors.append('bag read/deserialization failed: '+str(e))
    if file_mode:
        from jpeg_file_check import file_audit
        file_result=file_audit(session);errors.extend('JPEG files: '+e for e in file_result['errors'])
        keys[LEFT]=file_result['keys']['left'];keys[RIGHT]=file_result['keys']['right']
        times[LEFT]=[x[1] for x in keys[LEFT]];times[RIGHT]=[x[1] for x in keys[RIGHT]]
        if counts[LEFT] or counts[RIGHT]:errors.append('C5F bag unexpectedly contains image topics')
    for t in REQUIRED:
        if file_mode and t in [LEFT,RIGHT]:continue
        if not counts[t]:errors.append('missing required topic: '+t)
    if not keys[LEFT] or keys[LEFT]!=keys[RIGHT] or keys[LEFT]!=valid_video:errors.append('left/right/valid-video metadata sequence+stamp mismatch')
    if len(set(keys[LEFT]))!=len(keys[LEFT]):errors.append('duplicate stereo capture keys')
    if bad_image:errors.append('image payload/shape/encoding failures: '+str(bad_image))
    if invalid_buffers:errors.append('invalid V4L2 buffers: '+str(invalid_buffers))
    if video_sequence_bad:errors.append('V4L2 sequence gap/duplicate/reset: '+str(video_sequence_bad))
    if cloud_bad or cloud_empty or cloud_seq_gaps:errors.append('CustomMsg structural/empty/sequence continuity failure')
    streams={topic:continuity(times[topic]) for topic in [LEFT,RIGHT,ZI,LI,LIDAR]}
    for topic,stats in streams.items():
        if stats['backwards'] or stats['duplicates']:errors.append(topic+': timestamp backward/duplicate')
        if stats['long_intervals']:errors.append(topic+': observed long intervals')
    if not synthetic:
        for topic in [LEFT,RIGHT]:
            if (streams[topic]['fps'] or 0)<28.5:errors.append(topic+': target 30 FPS not sustained')
        if streams[LEFT].get('duration_s',0)<meta.get('duration_requested_s',30)*.9:errors.append('recording shorter than requested test duration')
        if (streams[ZI]['fps'] or 0)<100:errors.append('ZED IMU observed rate below 100 Hz')
        if (streams[LI]['fps'] or 0)<100:errors.append('MID-360 IMU observed rate below 100 Hz')
        if (streams[LIDAR]['fps'] or 0)<8:errors.append('Livox observed cloud publish rate below 8 Hz')
    anchor_rows=[]
    if (session/'anchors.jsonl').exists():anchor_rows=[json.loads(l) for l in (session/'anchors.jsonl').read_text().splitlines() if l.strip()]
    sidekeys=[(r['writer_epoch'],r['write_sequence'],r['raw_hex']) for r in anchor_rows]
    if anchor_bag!=sidekeys:errors.append('bag/sidecar anchor history mismatch')
    if not anchor_rows:errors.append('no anchor state history recorded (even invalid state must be traceable)')
    if any(r.get('skipped_updates',0) for r in anchor_rows):errors.append('observed skipped anchor updates; saved history is incomplete')
    video_file=session/'video_timestamps.csv';imu_file=session/'zed_imu_raw.csv'
    if not video_file.exists() or not imu_file.exists():errors.append('raw timestamp sidecar missing')
    else:
        rows=list(csv.DictReader(video_file.open()));hrows=list(csv.DictReader(imu_file.open()))
        if len(rows)!=counts['/zed2i/video_stamp'] or len(hrows)!=counts['/zed2i/imu_stamp']:errors.append('raw sidecar/bag metadata count mismatch')
    summary=json.loads((session/'capture_summary.json').read_text()) if (session/'capture_summary.json').exists() else {}
    if not summary:errors.append('capture summary missing')
    if not summary.get('bag_finalized'):errors.append('bag not successfully finalized and synced')
    for key in ['failed','queue_overflows','invalid_video_buffers','video_sequence_gaps','video_timestamp_backwards','video_timestamp_duplicates','imu_timestamp_backwards','imu_timestamp_duplicates']:
        if summary.get(key):errors.append('capture summary: '+key)
    if summary.get('pairs_written')!=(len(keys[LEFT]) if file_mode else counts[LEFT]):errors.append('writer summary/image count mismatch')
    imu_classification={'status':'PENDING','reason':'legacy session: no explicit time segmentation'}
    if 'imu_time_valid_reports' in summary or (session/'zed_imu_time_validity.csv').exists():
        try:
            with (session/'zed_imu_time_validity.csv').open() as f:decisions=list(csv.DictReader(f))
            with imu_file.open() as f:raw_ids=[int(r['sample_id']) for r in csv.DictReader(f)]
            def key(r):return (int(r['sample_id']),int(r['segment_id']),int(r['decision_sample_id']),r['time_validity'],r['reason'])
            ids=[int(r['sample_id']) for r in decisions]
            complete=len(ids)==len(set(ids)) and set(ids)==set(raw_ids)
            match=[key(r) for r in decisions]==[key(r) for r in imu_decisions_bag]
            invalid=sum(r['time_validity']!='VALID_CONTIGUOUS' for r in decisions)
            segments=len({r['segment_id'] for r in decisions})
            imu_classification={'status':'PASS' if complete and match and not invalid and segments==1 else 'FAIL','all_raw_reports_classified_once':complete,'bag_sidecar_equal':match,'not_valid_contiguous_reports':invalid,'segments':segments}
            if imu_classification['status']!='PASS':errors.append('ZED IMU time segmentation: invalid/unconfirmed reports, multiple segments or missing classification evidence')
        except (OSError,ValueError,KeyError) as e:
            imu_classification={'status':'FAIL','error':str(e)};errors.append('ZED IMU time classification evidence unavailable')
    io_diagnostics=audit_io(session) if summary else {'status':'FAIL','errors':['capture summary missing']}
    errors.extend('low-level diagnostics: '+e for e in io_diagnostics['errors'])
    timing=timing_evidence(session)
    if timing.get('qbuf_errors'):errors.append('V4L2 QBUF failure')
    if 'timing_rows' in timing and timing['timing_rows']!=counts['/zed2i/video_stamp']:errors.append('video timing / metadata count mismatch')
    mapping=assess_anchor_coverage(read_video(video_file),anchor_rows) if video_file.exists() else {'status':'PENDING','reason':'video raw timestamp sidecar missing'}
    history={'status':'FAIL' if not anchor_rows or any(r.get('skipped_updates',0) for r in anchor_rows) else 'NO_OBSERVED_GAPS','skipped_updates':sum(r.get('skipped_updates',0) for r in anchor_rows),'complete_history_guaranteed':False}
    result={'low_level_io_diagnostics':io_diagnostics,'zed_imu_time_classification':imu_classification,'acquisition_timing':timing,'anchor_history_acceptance':history,'image_mapping_acceptance':mapping,'capture_integrity':'PASS' if not errors else 'FAIL','synthetic_fixture':synthetic,'errors':sorted(set(errors)),'bag_readable_all_records':bag_read_ok,'ros_playback':'PENDING (offline deserialization is not a live ROS replay)','counts':dict(counts),'streams':streams,'cloud_points':cloud_points,'cloud_structure_errors':cloud_bad,'cloud_empty_messages':cloud_empty,'cloud_sequence_discontinuities':cloud_seq_gaps,'upstream_lidar_packet_completeness':'PENDING: CustomMsg has no original Ethernet packet sequence; observable ROS structure and continuity checked','stereo_sequence_and_stamps_equal':bool(keys[LEFT]) and keys[LEFT]==keys[RIGHT]==valid_video,'anchor_states':len(anchor_rows),'anchor_poll_skipped_states':sum(r.get('skipped_updates',0) for r in anchor_rows),'sync_status':'SYNC_PENDING','physical_sync_verified':False,'intrinsics':'PENDING','extrinsics':'PENDING','fast_livo_offline_ready':False,'resources':resources(session),'checked_bag_bytes':byte_count,'offline_read_seconds':time.monotonic()-start}
    if file_mode:
        from jpeg_file_check import application_status
        result['jpeg_files']=file_result
        result['mid_clock_types']=sorted(mid_types);result['mid_clock_switch_counts']=sorted(mid_switches)
        result['image_stream_statistics_source']='JPEG frames.csv and decoded files; counts remain actual bag message counts'
        if cfg.get('long_recording',False):result['duration_requested_s']=meta.get('duration_requested_s',300)
        result['SLAM_REQUIRED_DATA_STATUS']=application_status(result,cfg)
    if cfg.get('gnss_enable',False):
        from gnss_recording_check import check_gnss
        result['gnss']=check_gnss(session)
        if result['gnss']['errors']:
            result['errors'].extend('GNSS: '+e for e in result['gnss']['errors']);result['capture_integrity']='FAIL'
    return result
def main():
    ap=argparse.ArgumentParser();ap.add_argument('session');ap.add_argument('--output-dir',help='write new FULL_STRICT result/profile outside the read-only source session');args=ap.parse_args()
    session=pathlib.Path(args.session).resolve();out=pathlib.Path(args.output_dir).resolve() if args.output_dir else session
    if args.output_dir and (out==session or session in out.parents):ap.error('explicit output-dir must be outside the source session')
    from checker_run import run
    result=run(session,out)
    print(json.dumps(result,indent=2));return 0 if result['capture_integrity']=='PASS' else 2
if __name__=='__main__':sys.exit(main())
