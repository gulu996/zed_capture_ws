import pathlib,sys,unittest,yaml,json,tempfile,copy,io,contextlib,types,hashlib
from unittest.mock import patch,Mock
W=pathlib.Path('/home/jetson/zed_capture_ws');sys.path.insert(0,str(W/'scripts'))
from ima1_diagnostic_config import selection,bind_result
import session
class TestConfig(unittest.TestCase):
 def test_old_configs_off_and_same_binary(self):
  for p in (W/'src/zed_capture/config').glob('*.yaml'):
   c=yaml.safe_load(p.read_text());b,args,identity=selection(c)
   self.assertEqual(b,W/'devel/lib/zed_capture/zed_capture_node');self.assertEqual(args,[]);self.assertIsNone(identity)
 def test_invalid_bool_and_missing_manifest_fail(self):
  for c in [dict(ima1_read_diagnostics='false'),dict(ima1_read_diagnostics=True),dict(ima1_diagnostic_build_manifest='/tmp/missing_l2d2_manifest.json')]:
   with self.assertRaises((ValueError,OSError)):selection(c)
 def test_enabled_and_disabled_manager_subprocess(self):
  build=W/'diagnostics/ima1_l2d2/build_candidate_03/build_manifest.json'
  for enabled in (False,True):
   cfg=yaml.safe_load((W/'src/zed_capture/config/capture_hd720_c5g.yaml').read_text())
   cfg.update(ima1_read_diagnostics=enabled,ima1_diagnostic_build_manifest=str(build),gnss_enable=False)
   binary,args,identity=selection(cfg)
   self.assertEqual(args,['_ima1_read_diagnostics:='+str(enabled).lower()])
   with tempfile.TemporaryDirectory(prefix='L2D2_CONFIG_SYNTHETIC_') as tmp:
    cfg['output_root']=tmp+'/sessions';config=pathlib.Path(tmp)/'space path.yaml';config.write_text(yaml.safe_dump(cfg))
    master=Mock();master.getSystemState.return_value=([('/livox/lidar',['existing']),('/livox/imu',['existing'])],[],[]);master.getPublishedTopics.return_value=[('/livox/lidar','livox_ros_driver2/CustomMsg')]
    child=Mock();child.poll.return_value=0;child.returncode=0;child.pid=999999;child.wait.return_value=0
    with patch.dict(sys.modules,{'rosgraph':types.SimpleNamespace(Master=lambda _:master)}),patch.object(sys,'argv',['session.py','--config',str(config),'--duration','30']),patch.object(session,'preflight',return_value={'errors':[],'dynamic_dependencies':{}}),patch.object(session,'capture_environment',return_value={'LD_LIBRARY_PATH':'SYNTHETIC'}),patch.object(session.subprocess,'Popen',return_value=child) as spawn,patch.object(session.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stdout='')),patch.object(session.signal,'signal'),patch.object(session.socket,'setdefaulttimeout'),contextlib.redirect_stdout(io.StringIO()):
     self.assertEqual(session.main(),0)
    self.assertEqual(spawn.call_count,1);argv=spawn.call_args.args[0];self.assertEqual(argv[0],str(binary));self.assertIn(args[0],argv)
    s=next(pathlib.Path(cfg['output_root']).iterdir());meta=json.loads((s/'session.json').read_text());self.assertEqual(meta['config_sha256'],hashlib.sha256(config.read_bytes()).hexdigest())
    bound=json.loads((s/'ima1_diagnostic_binding.json').read_text());self.assertEqual(bound['status'],'DIAGNOSTIC_INCOMPLETE' if enabled else 'DIAGNOSTIC_OFF')
if __name__=='__main__':unittest.main(verbosity=2)
