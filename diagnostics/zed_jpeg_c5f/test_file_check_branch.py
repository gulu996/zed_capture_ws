"""SYNTHETIC checker integration. JPEG decode separately tested on real3."""
import csv,json,pathlib,shutil,sys,time
from unittest.mock import patch
import rosbag
W=pathlib.Path('/home/jetson/zed_capture_ws');D=W/'diagnostics/zed_jpeg_c5f';sys.path.insert(0,str(W/'scripts'));from check_recording import check
src=pathlib.Path(json.loads((D/'legacy_offline_tests.log').read_text())['output'])/'complete_synthetic';out=D/('synthetic_checker_'+str(time.time_ns()));out.mkdir()
for p in src.iterdir():
 if p.is_file() and p.suffix!='.bag' and p.name!='check_result.json':shutil.copy2(p,out/p.name)
meta=json.loads((out/'session.json').read_text());meta['config'].update(storage_mode='jpeg_files',slam_image_gap_policy={'max_events':3,'max_missing_period_ratio':.01,'max_interval_ms':100});(out/'session.json').write_text(json.dumps(meta))
keys={'left':[],'right':[]};frames=[]
with rosbag.Bag(str(src/'data.bag')) as b,rosbag.Bag(str(out/'sensors.bag'),'w') as dest:
 for topic,m,t in b.read_messages():
  if topic in ['/zed2i/left/image_raw','/zed2i/right/image_raw']:keys['left' if 'left' in topic else 'right'].append((m.header.seq,m.header.stamp.to_nsec()));continue
  if topic=='/zed2i/video_stamp':frames.append({'pair_id':str(m.pair_id),'raw_ns':str(m.header.stamp.to_nsec()),'sequence':str(m.v4l2_sequence)})
  dest.write(topic,m,t)
fixture={'status':'PASS','errors':[],'keys':keys,'frames':frames,'verified':[],'synthetic':True}
with patch('jpeg_file_check.file_audit',return_value=fixture):r=check(out)
assert r['capture_integrity']=='PASS',r['errors'];assert r['counts'].get('/zed2i/left/image_raw',0)==0;assert r['streams']['/zed2i/left/image_raw']['count']==len(keys['left']);assert r['SLAM_REQUIRED_DATA_STATUS']['status']!='PASS'
fixture['errors']=['SYNTHETIC disk error'];fixture['status']='FAIL'
with patch('jpeg_file_check.file_audit',return_value=fixture):r=check(out)
assert r['capture_integrity']=='FAIL';assert r['SLAM_REQUIRED_DATA_STATUS']['status']=='FAIL'
print('SYNTHETIC CHECKER PASS: nonimage bag mode, unchanged strict errors, actual bag counts, separate image stats, file-failure gating, no SLAM PASS')
