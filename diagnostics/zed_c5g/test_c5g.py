"""Offline only: mock manager and repeated real bytes with SYNTHETIC clocks."""
import pathlib,sys,unittest,yaml,json,hashlib,tempfile,io,contextlib,types
from unittest.mock import patch,Mock
W=pathlib.Path('/home/jetson/zed_capture_ws');R=W/'diagnostics/gnss_r2'
sys.path[:0]=[str(W/'scripts'),str(R),'/home/jetson/clock_diag']
from long_recording import validate,node_arguments,guard_seconds
from storage_mode import storage_arguments
from gnss_config import gnss_arguments
from gnss_receiver import Evidence
import joint_test,session
CFG=yaml.safe_load((W/'src/zed_capture/config/capture_hd720_c5g.yaml').read_text())
class Tests(unittest.TestCase):
 def test_policy_and_old_limits(self):
  self.assertTrue(validate(CFG,300));self.assertEqual(guard_seconds(CFG,300),330)
  self.assertIn('_long_recording:=true',node_arguments(CFG,300));storage_arguments(CFG,300);gnss_arguments(CFG,300)
  for duration in (0,-1,301,1200,float('nan'),float('inf')):
   with self.assertRaises(ValueError):validate(CFG,duration)
  for name in ('capture_hd720_c5f.yaml','capture_hd720_c5f_gnss.yaml'):
   cfg=yaml.safe_load((W/'src/zed_capture/config'/name).read_text())
   self.assertFalse(validate(cfg,30));self.assertEqual(guard_seconds(cfg,30),55)
   with self.assertRaises(ValueError):storage_arguments(cfg,300)
  for key,val in [('minimum_free_gb',0),('storage_mode','raw_bag'),('jpeg_shadow_enable',True),('long_recording','true')]:
   with self.assertRaises(ValueError):validate(dict(CFG,**{key:val}),300)
 def test_joint_duration_and_paths(self):
  self.assertEqual(joint_test.capture_command()[-1],'30')
  a=joint_test.capture_command('/tmp/space path/capture.yaml',300)
  self.assertEqual(a[-1],'/tmp/space path/capture.yaml');self.assertEqual(a[2],'300')
 def test_application_duration_not_just_thirty_seconds(self):
  from jpeg_file_check import application_status
  p=pathlib.Path('/home/jetson/zed_capture_data/20261018_174130_d85a69b1/check_result.json')
  check=json.loads(p.read_text());check['duration_requested_s']=300
  self.assertIn('short C5F capture',application_status(check,CFG)['reasons'])
  self.assertNotIn('short C5F capture',application_status(check,dict(CFG,long_recording=False))['reasons'])
 def test_manager_300_with_gnss_both_modes(self):
  for enabled in (False,True):
   with tempfile.TemporaryDirectory(prefix='C5G_MOCK_') as tmp:
    cfg=dict(CFG,gnss_enable=enabled,output_root=tmp+'/data');p=pathlib.Path(tmp)/'c5g.yaml';p.write_text(yaml.safe_dump(cfg))
    master=Mock();master.getSystemState.return_value=([('/livox/lidar',['existing']),('/livox/imu',['existing'])],[],[]);master.getPublishedTopics.return_value=[('/livox/lidar','livox_ros_driver2/CustomMsg')]
    child=Mock();child.poll.return_value=0;child.returncode=0;child.pid=999999;child.wait.return_value=0
    with patch.dict(sys.modules,{'rosgraph':types.SimpleNamespace(Master=lambda _:master)}),patch.object(sys,'argv',['session.py','--config',str(p),'--duration','300']),patch.object(session,'preflight',return_value={'errors':[],'dynamic_dependencies':{}}),patch.object(session,'capture_environment',return_value={'LD_LIBRARY_PATH':'SYNTHETIC'}),patch.object(session.subprocess,'Popen',return_value=child) as spawn,patch.object(session.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stdout='')),patch.object(session.signal,'signal'),patch.object(session.socket,'setdefaulttimeout'),contextlib.redirect_stdout(io.StringIO()):
     self.assertEqual(session.main(),0)
    self.assertEqual(spawn.call_count,2 if enabled else 1);a=spawn.call_args.args[0];self.assertIn('_long_recording:=true',a);self.assertIn('_duration:=300.0',a);self.assertIn('_gnss_enable:='+str(enabled).lower(),a)
 def test_repeated_gnss_and_periodic_sync(self):
  raw=(pathlib.Path('/home/jetson/zed_capture_data/20261018_174130_d85a69b1/gnss/serial_raw.bin')).read_bytes()
  with tempfile.TemporaryDirectory(prefix='C5G_REPEAT_NOT_HARDWARE_') as tmp:
   counts=[0]*5;clock=[0.0]
   def publish(i,m):counts[i]+=1
   with patch('gnss_receiver.time.monotonic',side_effect=lambda:clock[0]):
    e=Evidence(pathlib.Path(tmp)/'gnss',1,2,publish,sync_period=5)
    for repeat in range(11):
     for at in range(0,len(raw),4096):
      clock[0]+=1.1;ns=int(clock[0]*1e9)
      c=dict(monotonic_ns=ns,raw_before_ns=ns+10,realtime_ns=1792316492000000000+ns,raw_after_ns=ns+50,raw_bracket_ns=40)
      e.feed(raw[at:at+4096],c)
    e.close('SYNTHETIC_REPEATED_INPUT_END')
   self.assertEqual((e.out/'serial_raw.bin').read_bytes(),raw*11)
   self.assertEqual(e.summary()['raw_sha256'],hashlib.sha256(raw*11).hexdigest())
   self.assertEqual(counts,[12562,12562,5379,5379,0]);self.assertGreater(e.sync_count,50)
   self.assertEqual(e.summary()['counts'].get('utc_valid',0),0);self.assertEqual(e.summary()['host_clock_errors'],0)
   rows=[json.loads(x) for x in (e.out/'sync_checkpoints.jsonl').read_text().splitlines()]
   self.assertEqual(rows[-1]['raw_bytes'],111834*11)
 def test_sync_failure_preserves_raw_and_raises(self):
  with tempfile.TemporaryDirectory(prefix='C5G_SYNC_FAULT_') as tmp:
   e=Evidence(pathlib.Path(tmp)/'gnss',1,2,lambda *a:None,sync_period=5)
   c=dict(monotonic_ns=1,raw_before_ns=2,realtime_ns=3,raw_after_ns=4,raw_bracket_ns=2)
   e.feed(b'incomplete',c)
   with patch('gnss_receiver.os.fsync',side_effect=OSError('SYNTHETIC_ENOSPC')):
    with self.assertRaises(OSError):e.close('SYNTHETIC_ERROR')
   self.assertEqual((e.out/'serial_raw.bin').read_bytes(),b'incomplete')
if __name__=='__main__':unittest.main(verbosity=2)
