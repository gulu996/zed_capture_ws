"""Software/SYNTHETIC regression; never opens sensors."""
import csv,io,json,math,pathlib,shutil,struct,sys,tempfile,unittest
import numpy as np
W=pathlib.Path('/home/jetson/zed_capture_ws');sys.path.insert(0,str(W/'scripts'))
from checker_store import Store,Numbers,Index,dump,equal
from checker_bag import cloud_decode
from livox_ros_driver2.msg import CustomMsg,CustomPoint
import checker_streams as new
from jpeg_file_check import file_audit as oldjpeg
from analyze_real_session import assess_anchor_coverage as oldcover
from checker_application import application_status as appnew
from jpeg_file_check import application_status as appold
class Tests(unittest.TestCase):
 def setUp(self):self.s=Store()
 def tearDown(self):self.s.close()
 def plain(self,x):f=io.StringIO();dump(x,f);return json.loads(f.getvalue())
 def test_store_precision_order_duplicates(self):
  s=self.s.seq([2**63+19,{'n':2**63+17},[1,2]]);self.assertEqual(self.plain(s),[2**63+19,{'n':2**63+17},[1,2]])
  d=Index(self.s);self.assertTrue(d.add(2**64-1));self.assertFalse(d.add(2**64-1));self.assertTrue(equal(self.s.seq([(1,2)]),[(1,2)]))
 def test_numeric_budget(self):
  old=Numbers.LIMIT;Numbers.LIMIT=3
  try:
   n=Numbers();n.append(1);n.append(2);n.append(3)
   with self.assertRaises(ValueError):n.append(4)
  finally:Numbers.LIMIT=old
 def test_cloud_all_fields_exact(self):
  for count in [0,1,19,20000]:
   m=CustomMsg();m.header.seq=4294967295;m.header.stamp.secs=1792000000;m.header.stamp.nsecs=123456789;m.header.frame_id='真实_test';m.timebase=m.header.stamp.to_nsec();m.point_num=count;m.lidar_id=7;m.rsvd=[1,2,3]
   m.points=[CustomPoint(i, i*.1,-i*.2,i*.3,i%256,(i+1)%256,(i+2)%256) for i in range(count)];b=io.BytesIO();m.serialize(b);raw=b.getvalue();old=CustomMsg().deserialize(raw);fast=cloud_decode(raw,CustomMsg,CustomMsg._md5sum)
   self.assertEqual(fast.header,old.header);self.assertEqual((fast.timebase,fast.point_num,fast.lidar_id,fast.rsvd),(old.timebase,old.point_num,old.lidar_id,old.rsvd));self.assertEqual(len(fast.points),len(old.points))
   for i,p in enumerate(old.points):
    for k in CustomPoint.__slots__:self.assertEqual(getattr(p,k),fast.points.view[i][k])
   if count:
    with self.assertRaises(Exception):cloud_decode(raw[:-1],CustomMsg,CustomMsg._md5sum)
   with self.assertRaises(ValueError):cloud_decode(raw,CustomMsg,'wrong')
 def test_jpeg_real_three_and_corruption(self):
  src=pathlib.Path((W/'diagnostics/zed_jpeg_c5f/real_run_path.txt').read_text())
  self.assertEqual(self.plain(new.file_audit(src,self.s)),self.plain(oldjpeg(src)))
  for mode in ['truncated','header','orphan','duplicate','metadata','wrong_sof']:
   with tempfile.TemporaryDirectory(prefix='C5H_SYNTHETIC_') as tmp:
    p=pathlib.Path(tmp)/'data';p.mkdir();shutil.copytree(src/'camera',p/'camera')
    for n in ['frames.csv','video_timestamps.csv','jpeg_files_summary.json']:shutil.copy2(src/n,p/n)
    if mode=='truncated':
     f=next((p/'camera').rglob('*.jpg'));f.write_bytes(f.read_bytes()[:-10])
    elif mode=='orphan':(p/'camera/orphan.jpg').write_bytes(b'bad')
    elif mode=='wrong_sof':
     f=next((p/'camera').rglob('*.jpg'));b=bytearray(f.read_bytes());at=b.index(b'\xff\xc0');b[at+7]=0;f.write_bytes(b)
    else:
     rs=list(csv.DictReader((p/'frames.csv').open()));fields=list(rs[0])
     if mode=='header':rs[0]['left_nsec']=str(int(rs[0]['left_nsec'])+1)
     if mode=='metadata':rs[0]['sequence']='999'
     if mode=='duplicate':rs.append(rs[0])
     with (p/'frames.csv').open('w') as f:writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rs)
    self.assertEqual(self.plain(new.file_audit(p,self.s)),self.plain(oldjpeg(p)),mode)
 def test_coverage_all_reasons(self):
  base=2**53+19
  good=[dict(host_monotonic_ns=base+i*5000000,writer_epoch=1,clock_source=2,validity='HOST_ARRIVAL_ANCHOR') for i in range(4)]
  videos=[dict(pair_id=i,raw_ns=ns,timestamp_type=typ) for i,(ns,typ) in enumerate([(base-1,8192),(base,8192),(base+6000000,8192),(base+20000000,8192),(base+1,0)])]
  for anchors in [good,good[::-1],[],good+[dict(good[-1],host_monotonic_ns=base+200000000)],good[:2]+[dict(good[2],writer_epoch=2)]+good[3:]]:
   self.assertEqual(self.plain(new.assess_anchor_coverage(videos,anchors,self.s)),oldcover(videos,anchors))
 def test_resources_timing_real(self):
  from check_recording import resources
  from analyze_real_session import timing_evidence
  p=pathlib.Path('/home/jetson/zed_capture_data/20261018_185527_61ca19f8')
  self.assertEqual(new.resources(p),resources(p));self.assertEqual(new.timing_evidence(p),timing_evidence(p))
 def test_application_order_precision(self):
  cfg={'slam_image_gap_policy':{'max_events':3,'max_missing_period_ratio':.01,'max_interval_ms':100},'long_recording':True}
  result={'duration_requested_s':300,'jpeg_files':{'status':'PASS','frames':[dict(pair_id=str(i),raw_ns=str(2**53+19+i*33333333),sequence=str(i)) for i in range(9000,0,-1)]},'streams':{'/zed2i/left/image_raw':{'duration_s':300,'max_interval_ms':33.334,'long_intervals':0},'/livox/lidar':{'count':3000,'fps':10},'/livox/imu':{'count':60000,'fps':200}},'bag_readable_all_records':True,'stereo_sequence_and_stamps_equal':True,'mid_clock_types':['2'],'mid_clock_switch_counts':['0']}
  self.assertEqual(appnew(result,cfg,self.s),appold(result,cfg))
 def test_gnss_single_pass_matches_legacy(self):
  from checker_gnss import GnssAudit
  from gnss_recording_check import check_gnss
  import rosbag,types
  root=W/'diagnostics/gnss_r2'
  for p in [root/'offline_integration_20261018_180502_4ad8bc5b/output',root/'r21_20261018_180214/latest_real_replay/writer']:
   expected=check_gnss(p);a=GnssAudit(p)
   with rosbag.Bag(str(p/'sensors.bag')) as bag:
    for topic,m,t in bag.read_messages():a.consume(topic,m)
   self.assertEqual(a.finish(),expected)
   a=GnssAudit(p);injected=False
   with rosbag.Bag(str(p/'sensors.bag')) as bag:
    for topic,m,t in bag.read_messages():
     if not injected:
      fields={k:getattr(m,k) for k in m.__slots__};fields.update(_type=m._type,_md5sum='WRONG',INVALID=getattr(m,'INVALID',0));m=types.SimpleNamespace(**fields);injected=True
     a.consume(topic,m)
   self.assertTrue(any('MD5 mismatch' in e for e in a.finish()['errors']))
 def test_streaming_io_matches_saved_real(self):
  import checker_io
  p=pathlib.Path('/home/jetson/zed_capture_data/20261018_185527_61ca19f8')
  expected=json.loads((p/'check_result.json').read_text())['low_level_io_diagnostics']
  self.assertEqual(self.plain(checker_io.audit(p,self.s)),expected)
 def test_gnss_disabled_legacy_bag(self):
  from checker_strict import check as optimized
  from check_recording import check as legacy
  p=pathlib.Path(json.loads((W/'diagnostics/zed_jpeg_c5f/legacy_offline_tests.log').read_text())['output'])/'complete_synthetic'
  a=legacy(p);b=self.plain(optimized(p,self.s));a.pop('offline_read_seconds');b.pop('offline_read_seconds')
  self.assertEqual(b,self.plain(a));self.assertNotIn('gnss',b)
 def test_disk_write_failure_not_success(self):
  with open('/dev/full','wb',buffering=0) as f:
   class Sink:
    def write(self,text):return f.write(text.encode())
   with self.assertRaises(OSError):dump({'evidence':list(range(10000))},Sink())
 def test_oversize_row_fails_closed(self):
  with self.assertRaises(ValueError):self.s.seq().append('x'*1048577)
 def test_index_budget_before_loading(self):
  from checker_bag import index_budget,MAX_INDEX_RECORDS
  import types
  fake=types.SimpleNamespace(get_message_count=lambda:MAX_INDEX_RECORDS,_connections={},_chunks=[])
  self.assertEqual(index_budget(fake),MAX_INDEX_RECORDS)
  with self.assertRaises(ValueError):index_budget(fake,1)
if __name__=='__main__':unittest.main(verbosity=2)
