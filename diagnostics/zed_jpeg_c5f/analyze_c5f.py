import csv,json,pathlib,sys
import numpy as np
WS=pathlib.Path(__file__).resolve().parents[2]
def analyze(test_dir,out,publish_report=True):
    test=json.loads((test_dir/'test_result.json').read_text());session=pathlib.Path(test['session_path']) if test.get('session_path') else None
    if not session:return {'CAPTURE_RUNTIME':'HARDWARE_PENDING','errors':test.get('errors',[])}
    def load(n):
        p=session/n;return json.loads(p.read_text()) if p.exists() else {}
    check=load('check_result.json');summary=load('jpeg_files_summary.json');capture=load('capture_summary.json');cfg=load('session.json').get('config',{})
    rows=list(csv.DictReader((session/'frames.csv').open())) if (session/'frames.csv').exists() else []
    def stats(a):return dict(zip(['p50','p95','p99','max'],[float(x) for x in np.percentile(a,[50,95,99,100])])) if a else {}
    perf={}
    for name,start,end in [('encoding_latency_ms','copied_ns','encode_end_ns'),('encode_queue_wait_ms','submitted_ns','encode_begin_ns'),('writer_queue_wait_ms','encode_end_ns','write_begin_ns'),('write_ms','write_begin_ns','write_end_ns')]:perf[name]=stats([(int(r[end])-int(r[start]))/1e6 for r in rows if r['status']=='WRITTEN'])
    for name,col in [('conversion_ms','convert_ns'),('jpeg_encode_ms','encode_ns')]:perf[name]=stats([int(r[col])/1e6 for r in rows if r['status']=='WRITTEN'])
    jpeg=sum(p.stat().st_size for p in (session/'camera').rglob('*.jpg'));bag=(session/'sensors.bag').stat().st_size if (session/'sensors.bag').exists() else 0;total=sum(p.stat().st_size for p in session.rglob('*') if p.is_file())
    video=check.get('streams',{}).get('/zed2i/left/image_raw',{});types=test.get('mid_clock_types',[]);switch=test.get('mid_clock_switch_counts',[])
    app=check.get('SLAM_REQUIRED_DATA_STATUS',{'status':'FAIL','reasons':['missing checks']})
    if test.get('capture_runtime')!='CAPTURE_RUNTIME_PASS' or test.get('clock_diagnostic')!='CLOCK_DIAGNOSTIC_PASS' or types!=['2'] or switch!=['0']:
        app=dict(app,status='FAIL',reasons=app.get('reasons',[])+['runtime/clock/GPS source not validated'])
    result={'session':str(session),'test_dir':str(test_dir),'CAPTURE_RUNTIME':test.get('capture_runtime'),'JPEG_FILE_STORAGE':check.get('jpeg_files',{}).get('status','FAIL'),'DATA_INTEGRITY':check.get('capture_integrity','FAIL'),'SLAM_REQUIRED_DATA_STATUS':app,'CLOCK_DIAGNOSTIC':test.get('clock_diagnostic'),'L2B_MAPPING':'PENDING','PHYSICAL_SYNC':'PENDING','jpeg_files':summary,'performance':perf,'video':video,'v4l2_driver_ids_missing':capture.get('video_sequence_gaps'),'raw_queue_peak_bytes':capture.get('queue_peak_bytes'),'raw_queue_overflows':capture.get('queue_overflows'),'resources':check.get('resources'),'errors':check.get('errors',[]),'sizes':{'jpeg_bytes':jpeg,'sensors_bag_bytes':bag,'all_session_bytes':total,'vs_C2_3460013078_reduction_percent':100*(1-total/3460013078),'observed_total_bytes_per_video_second':total/video['duration_s'] if video.get('duration_s') else None},'comparison_limits':'C2 has different scene/counts; no CompressedImage bag experiment performed. Per-file metadata/IO syscall overhead exists but difference not measured.','anchors':check.get('anchor_history_acceptance'),'MID_clock_types':types,'MID_clock_switch_counts':switch}
    thermal=out/'thermal.jsonl'
    if thermal.exists():
        ts=[json.loads(x) for x in thermal.read_text().splitlines()];temp=[float(x['thermal_raw_mC']['CPU-therm'])/1000 for x in ts if x['thermal_raw_mC'].get('CPU-therm') not in [None,'UNAVAILABLE']];result['temperature_C_whole_test']={'min':min(temp),'max':max(temp)} if temp else {'status':'UNAVAILABLE'}
    with (out/'c5f_result.json').open('x') as f:json.dump(result,f,indent=2)
    text='**C5-F实际验证（自动记录，仍需复核）**\n\n原始YUYV未写入本实验bag；JPEG文件与sensors.bag独立保存。编码、写盘失败及原始视频缺口分别保留。L2-B和物理同步不由存储通过推导。\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n'
    (out/'zed_720p_jpeg_c5f_validation.md').write_text(text)
    if publish_report:
        p=WS/'zed_720p_jpeg_c5f_validation.md'
        if p.exists():p=WS/('zed_720p_jpeg_c5f_validation_'+session.name+'.md')
        with p.open('x') as f:f.write(text)
    return result
