import pathlib,sys,unittest,yaml,tempfile,types,contextlib,io,json
from unittest.mock import patch,Mock
WS=pathlib.Path('/home/jetson/zed_capture_ws')
sys.path.insert(0,str(WS/'scripts'));sys.path.insert(0,'/home/jetson/clock_diag')
from jpeg_shadow_config import shadow_arguments,shadow_preflight
from joint_test import capture_command,capture_config
import session
class ConfigTests(unittest.TestCase):
 def cfg(self,name):return yaml.safe_load((WS/'src/zed_capture/config'/name).read_text())
 def test_defaults(self):
  for name,res in [('capture.yaml','HD1080'),('capture_hd720_c2.yaml','HD720')]:
   cfg=self.cfg(name);self.assertEqual(cfg['resolution'],res);self.assertEqual(shadow_arguments(cfg,30),[])
   with patch('jpeg_shadow_config.subprocess.run') as call:
    self.assertEqual(shadow_preflight(cfg,30,{})['status'],'DISABLED');call.assert_not_called()
 def test_only_opt_in_changes(self):
  c2=self.cfg('capture_hd720_c2.yaml');c4=self.cfg('capture_hd720_c4.yaml');self.assertTrue(c4.pop('jpeg_shadow_enable'));self.assertEqual(c2,c4)
 def test_cli_passthrough(self):
  p=WS/'src/zed_capture/config/capture_hd720_c4.yaml';path,data,cfg=capture_config(p)
  self.assertEqual(capture_command(path)[-2:],['--config',str(p)])
  self.assertEqual(shadow_arguments(cfg,30),['_jpeg_shadow_enable:=true'])
  self.assertNotIn('--config',capture_command())
 def test_bad_configs(self):
  c=self.cfg('capture_hd720_c4.yaml')
  for key,value in [('resolution','HD1080'),('jpeg_shadow_enable','false'),('pixel_layout','BGR')]:
   bad=dict(c);bad[key]=value
   with self.assertRaises(ValueError):shadow_arguments(bad,30)
  with self.assertRaises(ValueError):shadow_arguments(c,31)
  with self.assertRaises(FileNotFoundError):capture_config('/nonexistent C4 config.yaml')
 def launch_session(self,config_name):
  with tempfile.TemporaryDirectory(prefix='C4 SYNTHETIC config ') as tmp:
   root=pathlib.Path(tmp);cfg=self.cfg(config_name);cfg['output_root']=str(root/'data');path=root/'with spaces.yaml';path.write_text(yaml.safe_dump(cfg))
   master=Mock();master.getSystemState.return_value=([('/livox/lidar',['mock']),('/livox/imu',['mock'])],[],[]);master.getPublishedTopics.return_value=[('/livox/lidar','livox_ros_driver2/CustomMsg')]
   child=Mock();child.poll.return_value=0;child.returncode=0;child.pid=999999
   with patch.dict(sys.modules,{'rosgraph':types.SimpleNamespace(Master=lambda name:master)}),patch.object(sys,'argv',['session.py','--config',str(path),'--duration','30']),patch.object(session,'preflight',return_value={'errors':[],'dynamic_dependencies':{}}),patch.object(session,'capture_environment',return_value={'LD_LIBRARY_PATH':'SYNTHETIC'}),patch.object(session.subprocess,'Popen',return_value=child) as spawn,patch.object(session.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stdout='')),patch.object(session.signal,'signal'),patch.object(session.socket,'setdefaulttimeout'),contextlib.redirect_stdout(io.StringIO()):
    self.assertEqual(session.main(),0)
   enabled=cfg.get('jpeg_shadow_enable',False)
   self.assertEqual(spawn.call_count,1);self.assertIn('_jpeg_shadow_enable:='+str(enabled).lower(),spawn.call_args.args[0]);self.assertIn('_resolution:='+cfg['resolution'],spawn.call_args.args[0])
   if enabled:self.assertEqual(spawn.call_args.kwargs['env']['OPENBLAS_NUM_THREADS'],'1')
   else:self.assertNotIn('OPENBLAS_NUM_THREADS',spawn.call_args.kwargs['env'])
   folder=next((root/'data').iterdir());self.assertEqual(json.loads((folder/'capture_command.json').read_text())['jpeg_shadow_enable'],enabled);self.assertEqual(json.loads((folder/'session.json').read_text())['config_path'],str(path))
 def test_c4_reaches_actual_popen_boundary(self):self.launch_session('capture_hd720_c4.yaml')
 def test_default_c2_explicitly_clear_stale_ros_shadow(self):
  for config_name in ['capture.yaml','capture_hd720_c2.yaml']:self.launch_session(config_name)
if __name__=='__main__':unittest.main(verbosity=2)
