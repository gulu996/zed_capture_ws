"""C5-H FULL_STRICT implementation; same assertions, disk-backed joins."""
import argparse,collections,csv,json,math,pathlib,sys,time
import numpy as np
import rosbag
from check_recording import continuity,LEFT,RIGHT,ZI,LI,LIDAR,REQUIRED
from checker_store import Store,Index,Numbers,equal
from checker_streams import csv_rows,json_rows,resources,timing_evidence,assess_anchor_coverage
from checker_io import audit as audit_io
from checker_gnss import GnssAudit
from checker_bag import messages,index_budget
def check(session, store):
    session=pathlib.Path(session);errors=[];counts=collections.Counter();times=collections.defaultdict(Numbers);keys=collections.defaultdict(store.seq);valid_video=store.seq();anchor_bag=store.seq()
    mid_types=set();mid_switches=set();cloud_points=0;cloud_bad=0;cloud_empty=0;cloud_seq_gaps=0;previous_seq=None;invalid_buffers=0;bad_image=0;video_sequence_bad=0;video_previous=None;imu_decisions_bag=store.seq()
    meta=json.loads((session/'session.json').read_text()) if (session/'session.json').exists() else {}
    synthetic=bool(meta.get('synthetic_fixture'));cfg=meta.get('config',{});file_mode=cfg.get('storage_mode')=='jpeg_files';file_result=None;wanted=(1920,1080) if cfg.get('resolution','HD1080')=='HD1080' else (1280,720)
    if synthetic:wanted=tuple(meta['fixture_dimensions'])
    gnss=GnssAudit(session) if cfg.get('gnss_enable',False) else None
    bags=sorted(session.glob('*.bag'));bag_read_ok=False;start=time.monotonic();byte_count=0;index_records=0
    if not bags:errors.append('no finalized bag')
    if list(session.glob('*.active')):errors.append('unfinished .active file')
    try:
        for path in bags:
            byte_count+=path.stat().st_size
            with rosbag.Bag(str(path),'r',skip_index=True) as bag:
                index_records=index_budget(bag,index_records)
                for topic,msg,received in messages(bag):
                    counts[topic]+=1
                    if gnss is not None and path.name=='sensors.bag':gnss.consume(topic,msg)
                    if file_mode and msg._type in ['sensor_msgs/Image','sensor_msgs/CompressedImage']:errors.append('C5F bag contains image payload')
                    if topic in [LEFT,RIGHT,ZI,LI,LIDAR] and hasattr(msg,'header'):times[topic].append(msg.header.stamp.to_nsec())
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
        from checker_streams import file_audit
        file_result=file_audit(session,store);errors.extend('JPEG files: '+e for e in file_result['errors'])
        keys[LEFT]=file_result['keys']['left'];keys[RIGHT]=file_result['keys']['right']
        times[LEFT]=Numbers();times[RIGHT]=Numbers()
        for eye in [LEFT,RIGHT]:
            for x in keys[eye]:times[eye].append(x[1])
        if counts[LEFT] or counts[RIGHT]:errors.append('C5F bag unexpectedly contains image topics')
    for t in REQUIRED:
        if file_mode and t in [LEFT,RIGHT]:continue
        if not counts[t]:errors.append('missing required topic: '+t)
    if not keys[LEFT] or keys[LEFT]!=keys[RIGHT] or keys[LEFT]!=valid_video:errors.append('left/right/valid-video metadata sequence+stamp mismatch')
    unique=Index(store)
    for key in keys[LEFT]:unique.add(key)
    if len(unique)!=len(keys[LEFT]):errors.append('duplicate stereo capture keys')
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
    anchor_rows=store.seq()
    if (session/'anchors.jsonl').exists():anchor_rows=store.seq(json_rows(session/'anchors.jsonl'))
    sidekeys=((r['writer_epoch'],r['write_sequence'],r['raw_hex']) for r in anchor_rows)
    if not equal(anchor_bag,sidekeys):errors.append('bag/sidecar anchor history mismatch')
    if not anchor_rows:errors.append('no anchor state history recorded (even invalid state must be traceable)')
    if any(r.get('skipped_updates',0) for r in anchor_rows):errors.append('observed skipped anchor updates; saved history is incomplete')
    video_file=session/'video_timestamps.csv';imu_file=session/'zed_imu_raw.csv'
    if not video_file.exists() or not imu_file.exists():errors.append('raw timestamp sidecar missing')
    else:
        nv=sum(1 for r in csv_rows(video_file));nh=sum(1 for r in csv_rows(imu_file))
        if nv!=counts['/zed2i/video_stamp'] or nh!=counts['/zed2i/imu_stamp']:errors.append('raw sidecar/bag metadata count mismatch')
    summary=json.loads((session/'capture_summary.json').read_text()) if (session/'capture_summary.json').exists() else {}
    if not summary:errors.append('capture summary missing')
    if not summary.get('bag_finalized'):errors.append('bag not successfully finalized and synced')
    for key in ['failed','queue_overflows','invalid_video_buffers','video_sequence_gaps','video_timestamp_backwards','video_timestamp_duplicates','imu_timestamp_backwards','imu_timestamp_duplicates']:
        if summary.get(key):errors.append('capture summary: '+key)
    if summary.get('pairs_written')!=(len(keys[LEFT]) if file_mode else counts[LEFT]):errors.append('writer summary/image count mismatch')
    imu_classification={'status':'PENDING','reason':'legacy session: no explicit time segmentation'}
    if 'imu_time_valid_reports' in summary or (session/'zed_imu_time_validity.csv').exists():
        try:
            decisions=store.seq(csv_rows(session/'zed_imu_time_validity.csv'))
            def key(r):return (int(r['sample_id']),int(r['segment_id']),int(r['decision_sample_id']),r['time_validity'],r['reason'])
            ids=Index(store);rawids=Index(store);segments_set=Index(store);invalid=0
            for r in csv_rows(imu_file):rawids.add(int(r['sample_id']))
            for r in decisions:
                ids.add(int(r['sample_id']));segments_set.add(r['segment_id']);invalid+=r['time_validity']!='VALID_CONTIGUOUS'
            complete=len(ids)==len(decisions) and ids.same_keys(rawids)
            match=equal((key(r) for r in decisions),(key(r) for r in imu_decisions_bag))
            segments=len(segments_set)
            imu_classification={'status':'PASS' if complete and match and not invalid and segments==1 else 'FAIL','all_raw_reports_classified_once':complete,'bag_sidecar_equal':match,'not_valid_contiguous_reports':invalid,'segments':segments}
            if imu_classification['status']!='PASS':errors.append('ZED IMU time segmentation: invalid/unconfirmed reports, multiple segments or missing classification evidence')
        except (OSError,ValueError,KeyError) as e:
            imu_classification={'status':'FAIL','error':str(e)};errors.append('ZED IMU time classification evidence unavailable')
    io_diagnostics=audit_io(session,store) if summary else {'status':'FAIL','errors':['capture summary missing']}
    errors.extend('low-level diagnostics: '+e for e in io_diagnostics['errors'])
    timing=timing_evidence(session)
    if timing.get('qbuf_errors'):errors.append('V4L2 QBUF failure')
    if 'timing_rows' in timing and timing['timing_rows']!=counts['/zed2i/video_stamp']:errors.append('video timing / metadata count mismatch')
    mapping=assess_anchor_coverage(store.seq(csv_rows(video_file,True)),anchor_rows,store) if video_file.exists() else {'status':'PENDING','reason':'video raw timestamp sidecar missing'}
    history={'status':'FAIL' if not anchor_rows or any(r.get('skipped_updates',0) for r in anchor_rows) else 'NO_OBSERVED_GAPS','skipped_updates':sum(r.get('skipped_updates',0) for r in anchor_rows),'complete_history_guaranteed':False}
    result={'low_level_io_diagnostics':io_diagnostics,'zed_imu_time_classification':imu_classification,'acquisition_timing':timing,'anchor_history_acceptance':history,'image_mapping_acceptance':mapping,'capture_integrity':'PASS' if not errors else 'FAIL','synthetic_fixture':synthetic,'errors':sorted(set(errors)),'bag_readable_all_records':bag_read_ok,'ros_playback':'PENDING (offline deserialization is not a live ROS replay)','counts':dict(counts),'streams':streams,'cloud_points':cloud_points,'cloud_structure_errors':cloud_bad,'cloud_empty_messages':cloud_empty,'cloud_sequence_discontinuities':cloud_seq_gaps,'upstream_lidar_packet_completeness':'PENDING: CustomMsg has no original Ethernet packet sequence; observable ROS structure and continuity checked','stereo_sequence_and_stamps_equal':bool(keys[LEFT]) and keys[LEFT]==keys[RIGHT]==valid_video,'anchor_states':len(anchor_rows),'anchor_poll_skipped_states':sum(r.get('skipped_updates',0) for r in anchor_rows),'sync_status':'SYNC_PENDING','physical_sync_verified':False,'intrinsics':'PENDING','extrinsics':'PENDING','fast_livo_offline_ready':False,'resources':resources(session),'checked_bag_bytes':byte_count,'offline_read_seconds':time.monotonic()-start}
    if file_mode:
        from checker_application import application_status
        result['jpeg_files']=file_result
        result['mid_clock_types']=sorted(mid_types);result['mid_clock_switch_counts']=sorted(mid_switches)
        result['image_stream_statistics_source']='JPEG frames.csv and decoded files; counts remain actual bag message counts'
        if cfg.get('long_recording',False):result['duration_requested_s']=meta.get('duration_requested_s',300)
        result['SLAM_REQUIRED_DATA_STATUS']=application_status(result,cfg,store)
    if cfg.get('gnss_enable',False):
        result['gnss']=gnss.finish()
        if result['gnss']['errors']:
            result['errors'].extend('GNSS: '+e for e in result['gnss']['errors']);result['capture_integrity']='FAIL'
    return result
