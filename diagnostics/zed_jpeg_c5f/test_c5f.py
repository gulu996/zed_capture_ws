import copy,csv,hashlib,io,json,pathlib,sys,unittest,yaml,tempfile,shutil
from unittest.mock import patch,Mock
import contextlib,types
W=pathlib.Path('/home/jetson/zed_capture_ws');D=W/'diagnostics/zed_jpeg_c5f';sys.path.insert(0,str(W/'scripts'));sys.path.insert(0,str(D));sys.path.insert(0,'/home/jetson/clock_diag')
import session
from storage_mode import storage_arguments,bag_name
from jpeg_shadow_config import shadow_arguments
from jpeg_file_check import file_audit,application_status
from offline_interface import decode_original,conversion_plan
from check_recording import check
import joint_test
import rosbag
class Tests(unittest.TestCase):
 def test_default_modes_unchanged(self):
  for name in ['capture.yaml','capture_hd720_c2.yaml','capture_hd720_c4.yaml','capture_hd720_c41_off.yaml','capture_hd720_c41_on.yaml']:
   cfg=yaml.safe_load((W/'src/zed_capture/config'/name).read_text());self.assertEqual(storage_arguments(cfg,30),['_storage_mode:=raw_bag']);self.assertEqual(bag_name(cfg),'data.bag')
 def test_explicit_files_no_shadow(self):
  cfg=yaml.safe_load((W/'src/zed_capture/config/capture_hd720_c5f.yaml').read_text());self.assertEqual(storage_arguments(cfg,30),['_storage_mode:=jpeg_files','_jpeg_sync_ms:=1000']);self.assertEqual(shadow_arguments(cfg,30),[]);self.assertEqual(bag_name(cfg),'sensors.bag');self.assertIn('--config',joint_test.capture_command(str(W/'src/zed_capture/config/capture_hd720_c5f.yaml')))
  for k,v in [('jpeg_shadow_enable',True),('resolution','HD1080'),('jpeg_quality',90),('jpeg_subsampling','422'),('jpeg_sync_ms',0),('storage_mode','bad')]:
   bad=dict(cfg);bad[k]=v
   with self.assertRaises(ValueError):storage_arguments(bad,30)
  with self.assertRaises(ValueError):storage_arguments(cfg,31)
 def test_c5f_reaches_child_with_explicit_mode(self):
  with tempfile.TemporaryDirectory(prefix='C5F_SYNTHETIC_config_') as tmp:
   root=pathlib.Path(tmp);cfg=yaml.safe_load((W/'src/zed_capture/config/capture_hd720_c5f.yaml').read_text());cfg['output_root']=str(root/'data');path=root/'config with spaces.yaml';path.write_text(yaml.safe_dump(cfg))
   master=Mock();master.getSystemState.return_value=([('/livox/lidar',['mock']),('/livox/imu',['mock'])],[],[]);master.getPublishedTopics.return_value=[('/livox/lidar','livox_ros_driver2/CustomMsg')]
   child=Mock();child.poll.return_value=0;child.returncode=0;child.pid=999999
   with patch.dict(sys.modules,{'rosgraph':types.SimpleNamespace(Master=lambda _:master)}),patch.object(sys,'argv',['session.py','--config',str(path),'--duration','30']),patch.object(session,'preflight',return_value={'errors':[],'dynamic_dependencies':{}}),patch.object(session,'capture_environment',return_value={'LD_LIBRARY_PATH':'SYNTHETIC'}),patch.object(session.subprocess,'Popen',return_value=child) as spawn,patch.object(session.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stdout='')),patch.object(session.signal,'signal'),patch.object(session.socket,'setdefaulttimeout'),contextlib.redirect_stdout(io.StringIO()):
    self.assertEqual(session.main(),0)
   self.assertEqual(spawn.call_count,1);argv=spawn.call_args.args[0];self.assertIn('_storage_mode:=jpeg_files',argv);self.assertIn('_jpeg_shadow_enable:=false',argv);self.assertIn('_jpeg_sync_ms:=1000',argv);self.assertEqual(spawn.call_args.kwargs['env']['OMP_NUM_THREADS'],'1')
   folder=next((root/'data').iterdir());meta=json.loads((folder/'session.json').read_text());self.assertEqual(meta['sensor_bag'],'sensors.bag');self.assertEqual(meta['config_path'],str(path));self.assertTrue((folder/'c5f_software.json').exists())
 def test_real_three_pairs(self):
  p=pathlib.Path((D/'real_run_path.txt').read_text());audit=file_audit(p);self.assertEqual(audit['status'],'PASS',audit['errors']);self.assertEqual(len(audit['verified']),3)
  for r in audit['frames']:
   for eye in ['left','right']:
    m=decode_original(p,r,eye);self.assertEqual(m.header.stamp.to_nsec(),int(r['raw_ns']));self.assertEqual(m.header.seq,int(r['sequence']));self.assertEqual(m.encoding,'bgr8');self.assertEqual((m.width,m.height,m.step,len(m.data)),(1280,720,3840,2764800));self.assertEqual(m.header.frame_id,r[eye+'_frame_id']);buf=io.BytesIO();m.serialize(buf);self.assertGreater(len(buf.getvalue()),len(m.data))
  with rosbag.Bag(str(p/'sensors.bag')) as b:
   types={m._type for _,m,_ in b.read_messages()}
   self.assertNotIn('sensor_msgs/Image',types);self.assertNotIn('sensor_msgs/CompressedImage',types);self.assertIn('livox_ros_driver2/CustomMsg',types);self.assertIn('sensor_msgs/Imu',types)
  plan=conversion_plan(p);self.assertEqual(len(plan['accepted']),0);self.assertEqual(len(plan['rejected']),3);self.assertFalse(plan['bag_written'])
  bad=dict(audit['frames'][0],status='WRITE_FAILED')
  with self.assertRaises(ValueError):decode_original(p,bad,'left')
 def test_corrupt_and_timestamp_rejected(self):
  src=pathlib.Path((D/'real_run_path.txt').read_text())
  for mode in ['truncated','header_changed']:
   with tempfile.TemporaryDirectory(prefix='C5F_SYNTHETIC_CORRUPTION_') as tmp:
    p=pathlib.Path(tmp)/'fixture';shutil.copytree(src,p)
    if mode=='truncated':
     f=next((p/'camera').rglob('*.jpg'));f.write_bytes(f.read_bytes()[:-10])
    else:
     with (p/'frames.csv').open() as f:reader=csv.DictReader(f);rows=list(reader);fields=reader.fieldnames
     rows[0]['left_nsec']=str(int(rows[0]['left_nsec'])+1)
     with (p/'frames.csv').open('w') as f:writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    self.assertEqual(file_audit(p)['status'],'FAIL')
 def test_no_mapping_or_sync_pass(self):
  policy={'max_events':3,'max_missing_period_ratio':.01,'max_interval_ms':100};cfg={'slam_image_gap_policy':policy}
  r={'jpeg_files':{'status':'PASS','frames':[{'pair_id':str(i+1),'sequence':str(i),'raw_ns':str(1000000000+i*33333333)} for i in range(901)]},'streams':{'/zed2i/left/image_raw':{'duration_s':30,'max_interval_ms':33.334,'long_intervals':0},'/livox/lidar':{'count':300,'fps':10},'/livox/imu':{'count':6000,'fps':200}},'bag_readable_all_records':True,'stereo_sequence_and_stamps_equal':True,'mid_clock_types':['2'],'mid_clock_switch_counts':['0']}
  self.assertEqual(application_status(r,cfg)['status'],'PENDING_L2B_AND_PHYSICAL_SYNC')
  r['streams']['/livox/imu']['long_intervals']=1;self.assertEqual(application_status(r,cfg)['status'],'FAIL');r['streams']['/livox/imu']['long_intervals']=0
  r['jpeg_files']['status']='FAIL';self.assertEqual(application_status(r,cfg)['status'],'FAIL')
 def test_node_path_is_metadata_only_for_file_mode(self):
  s=(W/'src/zed_capture/src/capture_node.cpp').read_text();self.assertIn('record_left=jpeg_files?sensor_msgs::Image::Ptr():left',s);self.assertIn('if(meta->payload_valid){if(!jpeg_files){bag.write',s);self.assertIn('if(!jpeg_files){left_pub=',s);self.assertIn('"sensors.bag"',s)
if __name__=='__main__':unittest.main(verbosity=2)
