#!/usr/bin/env python3
"""Read new-session evidence only. Never changes the original integrity result."""
import collections,csv,json,pathlib
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent
BASE=pathlib.Path('/home/jetson/zed_capture_data/20261017_162911_883e3a79')
def read(p):return json.loads(p.read_text()) if p.exists() else {}
def rows(p):
    if not p.exists():return []
    with p.open() as f:return list(csv.DictReader(f))
def stats(v):return {k:float(np.percentile(v,n)) for k,n in [('p50',50),('p95',95),('p99',99),('max',100)]} if v else {}
def state(ok):return 'PASS' if ok else 'FAIL'
def analyze(test_dir,out,publish_report=False):
    joint=read(test_dir/'test_result.json');session=pathlib.Path(joint['session_path']) if joint.get('session_path') else None
    result={'test_dir':str(test_dir),'session':str(session) if session else None,'CAPTURE_RUNTIME':'PENDING_HARDWARE','VIDEO_CONTINUITY':'PENDING_HARDWARE','JPEG_SHADOW_COMPLETION':'PENDING_HARDWARE','JPEG_SHADOW_QUEUE':'PENDING_HARDWARE','JPEG_SHADOW_LATENCY':'PENDING_HARDWARE','MID360_CONTINUITY':'PENDING_HARDWARE','CLOCK_DIAGNOSTIC':joint.get('clock_diagnostic','PENDING'),'DATA_INTEGRITY':joint.get('data_integrity','PENDING'),'L2B_MAPPING':'PENDING','PHYSICAL_SYNC':'PENDING','SLAM_REQUIRED_DATA_STATUS':'PENDING_OFFLINE_INTEGRATION','errors':[]}
    if not session:
        result['errors'].append('No capture session; inspect joint preflight/errors; no retry')
        return result
    check=read(session/'check_result.json');summary=read(session/'capture_summary.json');js=read(session/'jpeg_shadow_summary.json');events=rows(session/'jpeg_shadow_events.csv');video=rows(session/'video_timestamps.csv');vm={int(r['pair_id']):r for r in video};done=[e for e in events if e['status']=='COMPLETED']
    result.update(CAPTURE_RUNTIME=joint.get('capture_runtime','FAIL'),DATA_INTEGRITY=check.get('capture_integrity','PENDING'),shadow_summary=js,bag_bytes=(session/'data.bag').stat().st_size if (session/'data.bag').exists() else None,source_check_errors=check.get('errors',[]))
    ids=[int(e['pair_id']) for e in events];headers_ok=len(ids)==len(set(ids)) and set(ids)==set(vm)
    for e in events:
        v=vm.get(int(e['pair_id']),{})
        headers_ok &= e['sequence']==v.get('sequence') and e['raw_ns']==v.get('raw_ns') and e['timestamp_type']==v.get('timestamp_type') and e['timestamp_source']==v.get('timestamp_source')
        headers_ok &= int(e['left_sec'])*10**9+int(e['left_nsec'])==int(e['raw_ns']) and e['left_sec']==e['right_sec'] and e['left_nsec']==e['right_nsec'] and e['left_seq']==e['right_seq']==e['sequence']
        headers_ok &= e['left_frame_id']=='zed2i_left_raw' and e['right_frame_id']=='zed2i_right_raw'
    result['metadata_join_ok']=bool(headers_ok)
    result['event_status_counts']=dict(collections.Counter(e['status'] for e in events));result['rejection_and_failure_reasons']=dict(collections.Counter(e['reason'] for e in events if e['status']!='COMPLETED'))
    all_done=bool(events) and len(events)==len(done)==js.get('inputs')==js.get('completed')==summary.get('pairs_written') and headers_ok and js.get('event_log_ok') and not js.get('unlogged_inputs') and all(e['sof_420']=='1' and int(e['left_jpeg_bytes'])>0 and int(e['right_jpeg_bytes'])>0 for e in done)
    result['JPEG_SHADOW_COMPLETION']=state(all_done)
    result['JPEG_SHADOW_QUEUE']=state(bool(js) and not js.get('rejected') and not js.get('unlogged_inputs') and js.get('queue_drained') and js.get('worker_joined') and js.get('queue_peak',99)<=4)
    for key,fn in [('convert_pair_ms',lambda e:int(e['convert_pair_ns'])/1e6),('encode_pair_ms',lambda e:int(e['encode_pair_ns'])/1e6),('worker_pair_ms',lambda e:(int(e['completed_ns'])-int(e['worker_start_ns']))/1e6),('queue_wait_ms',lambda e:(int(e['worker_start_ns'])-int(e['submitted_ns']))/1e6),('copied_to_completed_ms',lambda e:(int(e['completed_ns'])-int(e['copied_ns']))/1e6)]:result[key]=stats([fn(e) for e in done])
    late=[e for e in done if int(e['completed_ns'])-int(e['copied_ns'])>33333333]
    result['late_pair_ids']=[int(e['pair_id']) for e in late];result['JPEG_SHADOW_LATENCY']=state(all_done and not late)
    result['latency_policy']='Strict deadline 33.333333ms from owned YUYV copy completion to JPEG completion; not exposure latency. All input events required, no threshold relaxation.'
    streams=check.get('streams',{});l=streams.get('/zed2i/left/image_raw',{});r=streams.get('/zed2i/right/image_raw',{})
    result['VIDEO_CONTINUITY']=state(bool(l) and l.get('count')==r.get('count') and check.get('stereo_sequence_and_stamps_equal') and all(l.get(k)==r.get(k)==0 for k in ['backwards','duplicates','long_intervals']) and summary.get('video_sequence_gaps')==0 and summary.get('invalid_video_buffers')==0)
    mid=all(streams.get(t,{}).get('count',0)>0 and all(streams[t].get(k)==0 for k in ['backwards','duplicates','long_intervals']) for t in ['/livox/lidar','/livox/imu'])
    mid &= check.get('cloud_structure_errors')==0 and check.get('cloud_sequence_discontinuities')==0 and check.get('cloud_empty_messages')==0
    result['MID360_CONTINUITY']=state(mid);result['mid_clock_types']=joint.get('mid_clock_types');result['mid_clock_switch_counts']=joint.get('mid_clock_switch_counts')
    result['mid_packet_completeness']='PENDING: ROS CustomMsg continuity cannot prove original Ethernet packet completeness'
    result['color_metadata']=read(session/'jpeg_shadow_color.json');result['zed_imu_time_classification']=check.get('zed_imu_time_classification');result['anchor_history_acceptance']=check.get('anchor_history_acceptance');result['mapping_candidate_coverage']=check.get('image_mapping_acceptance')
    result['resources']=check.get('resources');result['raw_queue_peak_bytes']=summary.get('queue_peak_bytes');result['raw_queue_overflows']=summary.get('queue_overflows');result['bag_readable_all_records']=check.get('bag_readable_all_records');result['streams']=streams;result['raw_timing']=check.get('acquisition_timing');result['io_diagnostics']=check.get('low_level_io_diagnostics')
    thermal_path=out/'thermal.jsonl';thermal=[json.loads(line) for line in thermal_path.open()] if thermal_path.exists() else []
    if done:
        lo=min(int(e['copied_ns']) for e in done);hi=max(int(e['completed_ns']) for e in done)
        thermal=[e for e in thermal if lo<=e['monotonic_ns']<=hi]
    temps=[float(e['thermal_raw_mC']['CPU-therm'])/1000 for e in thermal if str(e.get('thermal_raw_mC',{}).get('CPU-therm','')).lstrip('-').isdigit() and int(e['thermal_raw_mC']['CPU-therm'])>0]
    result['thermal_during_encoding']={'samples':len(thermal),'CPU_C_first_last_max':[temps[0],temps[-1],max(temps)] if temps else None,'nonzero_cooling_states':sorted({(k,v) for e in thermal for k,v in e.get('cooling_states',{}).items() if v not in ['0','UNAVAILABLE']}),'scaling_kHz_observed':sorted({v for e in thermal for v in e.get('scaling_cur_kHz',{}).values()}),'interpretation':'1Hz samples; DVFS is not proof of thermal throttling; power not measured'}
    baseline=read(BASE/'check_result.json');bs=read(BASE/'capture_summary.json');result['C2_baseline']={'resources':baseline.get('resources'),'streams':baseline.get('streams'),'bag_bytes':3460013078,'queue_peak_bytes':bs.get('queue_peak_bytes'),'raw_timing':baseline.get('acquisition_timing')}
    result['C4_minus_C2_resources']={k:float(v)-float(baseline.get('resources',{}).get(k,0)) for k,v in (result['resources'] or {}).items() if isinstance(v,(int,float)) and isinstance(baseline.get('resources',{}).get(k),(int,float))}
    # Join abnormal frames to both writer and JPEG events by immutable pair_id.
    em={int(e['pair_id']):e for e in events};io=rows(session/'video_io_events.csv');iom={int(e['pair_id']):e for e in io if int(e['pair_id'])};anomalies=[]
    for prev,cur in zip(video,video[1:]):
        dt=int(cur['raw_ns'])-int(prev['raw_ns']);seq=(int(cur['sequence'])-int(prev['sequence']))&0xffffffff
        if dt>50_000_000 or dt<=0 or seq!=1:
            pid=int(cur['pair_id']);anomalies.append({'pair_id':pid,'interval_ns':dt,'sequence_delta':seq,'previous_video':prev,'video':cur,'video_io':iom.get(pid),'shadow_event':em.get(pid),'note':'Temporal overlap only, not proof JPEG caused this event'})
    result['video_anomaly_timeline']=anomalies
    with (out/'c4_result.json').open('x') as f:json.dump(result,f,indent=2)
    report=out/'zed_720p_jpeg_c4_validation.md'
    lines=['**C4 720P Q95/420 实机影子验证**','',f'会话：`{session}`；联合诊断：`{test_dir}`。','', '| 验收 | 状态 |','| --- | --- |']
    for key in ['CAPTURE_RUNTIME','VIDEO_CONTINUITY','JPEG_SHADOW_COMPLETION','JPEG_SHADOW_QUEUE','JPEG_SHADOW_LATENCY','MID360_CONTINUITY','CLOCK_DIAGNOSTIC','DATA_INTEGRITY','L2B_MAPPING','PHYSICAL_SYNC']:lines.append(f'| {key} | {result[key]} |')
    lines+=['','原始YUYV仍写入bag；JPEG仅编码并记录尺寸/时序/SOF，未写图像或替换原Header。',f"图像：{l}。Bag：{result['bag_bytes']} bytes。",f'JPEG统计：`{js}`。',f"双目纯编码(ms)：{result.get('encode_pair_ms')}；完整worker(ms)：{result.get('worker_pair_ms')}；复制完成至编码完成(ms)：{result.get('copied_to_completed_ms')}。",f"超期pair_id：{result['late_pair_ids']}。原因计数：{result['rejection_and_failure_reasons']}。",f"资源：{result['resources']}。",f"C2资源：{result['C2_baseline']['resources']}。",f"原始队列峰值：{result['raw_queue_peak_bytes']}，C2：{bs.get('queue_peak_bytes')} bytes。",'','温度/频率时间序列见同目录thermal.jsonl（1Hz）；既有resources.jsonl及check_result提供CPU/RSS/磁盘统计。不得凭一次不同时间实验认定JPEG是异常唯一原因。','ZED IMU既有异常和锚点漏读保持严格DATA_INTEGRITY结论。MID360这里只评价ROS可观测连续性，时钟源/同步须独立复核。', '全部原始与影子异常按pair_id连接在c4_result.json/video_anomaly_timeline，可继续对齐CPU、writer、V4L2。','L2B、物理同步、720P标定及真实JPEG录包均未在本轮完成。是否进入正式压缩录包需复核本报告及色彩元数据后另行授权，不自动实施。']
    lines+=['',f"温度/频率：{result['thermal_during_encoding']}。",f"C4−C2同口径资源差：{result['C4_minus_C2_resources']}。CPU单位为单核=100%，复用的外部Livox进程可能不计入owned-child统计。"]
    with report.open('x') as f:f.write('\n'.join(lines)+'\n')
    # Expected top-level report location; never overwrite any previous report.
    top=ROOT.parents[1]/'zed_720p_jpeg_c4_validation.md'
    if publish_report and not top.exists():
        with top.open('x') as f:f.write(report.read_text())
    return result
