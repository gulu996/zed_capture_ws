import contextlib,io,json,pathlib,sys,tempfile,types,unittest,yaml
from unittest.mock import Mock,patch
W=pathlib.Path('/home/jetson/zed_capture_ws');sys.path.insert(0,str(W/'scripts'))
import session
class Test(unittest.TestCase):
 def run_manager(self,enabled=True,existing=False):
  with tempfile.TemporaryDirectory(prefix='GNSS_R2_MOCK_session_') as tmp:
   cfg=yaml.safe_load((W/'src/zed_capture/config/capture_hd720_c5f_gnss.yaml').read_text());cfg['output_root']=tmp+'/data';cfg['gnss_enable']=enabled
   path=pathlib.Path(tmp)/'config with spaces.yaml';path.write_text(yaml.safe_dump(cfg))
   pubs=[('/livox/lidar',['existing']),('/livox/imu',['existing'])]
   if existing:pubs.append(('/gnss/raw',['existing_gnss']))
   master=Mock();master.getSystemState.return_value=(pubs,[],[]);master.getPublishedTopics.return_value=[('/livox/lidar','livox_ros_driver2/CustomMsg')]
   def make_child(*args,**kwargs):
    child=Mock();child.poll.return_value=0;child.wait.return_value=0;child.returncode=0;child.pid=999999;return child
   with patch.dict(sys.modules,{'rosgraph':types.SimpleNamespace(Master=lambda _:master)}),patch.object(sys,'argv',['session.py','--config',str(path)]),patch.object(session,'preflight',return_value={'errors':[],'dynamic_dependencies':{}}),patch.object(session,'capture_environment',return_value={'LD_LIBRARY_PATH':'SYNTHETIC'}),patch.object(session.subprocess,'Popen',side_effect=make_child) as spawn,patch.object(session.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stdout='')),patch.object(session.signal,'signal'),patch.object(session.socket,'setdefaulttimeout'),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
    code=session.main()
   argv=[c.args[0] for c in spawn.call_args_list]
   if existing:self.assertEqual(code,2);self.assertFalse(argv);return
   self.assertEqual(code,0);self.assertEqual(len(argv),2 if enabled else 1)
   self.assertIn('_gnss_enable:='+str(enabled).lower(),argv[-1]);self.assertEqual(sum('gnss_receiver.py' in ' '.join(x) for x in argv),int(enabled))
   self.assertFalse(any(x[0] in ('roscore','roslaunch','rosbag') for x in argv))
   folder=next((pathlib.Path(tmp)/'data').iterdir());self.assertEqual((folder/'gnss_software.json').exists(),enabled)
   self.assertEqual(json.loads((folder/'session.json').read_text())['config_path'],str(path))
 def test_enabled_single_reader_unique_writer(self):self.run_manager()
 def test_disabled_no_gnss_process(self):self.run_manager(False)
 def test_existing_gnss_refused_without_killing(self):self.run_manager(True,True)
if __name__=='__main__':unittest.main(verbosity=2)
