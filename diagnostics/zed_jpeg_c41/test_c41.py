"""Offline only: SYNTHETIC fixtures and mocked launcher, never opens sensors."""
import contextlib,io,json,pathlib,sys,tempfile,unittest,types
from unittest.mock import patch,Mock
import run_control
from analyze_worker import analyze,csvrows
ROOT=pathlib.Path(__file__).resolve().parent
class Tests(unittest.TestCase):
 def test_only_feature_config_difference(self):
  paths,cfg=run_control.control_configs();self.assertEqual({k for k in cfg['off'] if cfg['off'][k]!=cfg['on'][k]},{'jpeg_shadow_enable'})
 def test_on_cannot_run_before_off(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(run_control,'ROOT',pathlib.Path(tmp)),patch.object(run_control,'code_hashes',return_value={}),patch.object(sys,'argv',['run_control','--arm','on','--experiment','test','--conditions-note','SYNTHETIC']),patch.object(run_control.subprocess,'Popen') as spawn,contextlib.redirect_stderr(io.StringIO()):
   with self.assertRaises(SystemExit):run_control.main()
   spawn.assert_not_called()
 def test_one_arm_one_child_no_retry(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);joint=root/'mock_joint';joint.mkdir();(joint/'test_result.json').write_text(json.dumps({'session_path':None}))
   child=Mock();child.stdout=iter(['TEST_DIR='+str(joint)+'\n']);child.wait.return_value=2
   with patch.object(run_control,'ROOT',root),patch.object(run_control,'code_hashes',return_value={}),patch.object(sys,'argv',['run_control','--arm','off','--experiment','one','--conditions-note','SYNTHETIC']),patch.object(run_control.subprocess,'Popen',return_value=child) as spawn,patch.object(run_control.subprocess,'run',return_value=types.SimpleNamespace(stdout='SYNTHETIC')),patch.object(run_control.signal,'signal'),contextlib.redirect_stdout(io.StringIO()):
    self.assertEqual(run_control.main(),2)
   self.assertEqual(spawn.call_count,1);self.assertTrue(str(spawn.call_args.args[0][-1]).endswith('capture_hd720_c41_off.yaml'));self.assertFalse((root/'runs/one/on').exists())
 def fixture(self):return pathlib.Path(json.loads((ROOT/'cpp_tests.json').read_text())[0]['argv'][1])
 def test_trace_and_synthetic_warmup_not_real_count(self):
  p=self.fixture()/'real_codec_synthetic_pixels';r=analyze(p);self.assertEqual(r['status'],'SOFTWARE_EVIDENCE_COMPLETE');self.assertTrue(r['warmup_before_first_real_copy']);self.assertEqual(len(r['rows']),1)
  self.assertEqual(r['warmup']['pairs'],3);self.assertEqual(r['warmup']['real_sensor_inputs'],0);self.assertFalse(r['warmup']['counted_in_shadow_inputs'])
  self.assertEqual(json.loads((p/'jpeg_shadow_summary.json').read_text())['inputs'],1)
 def test_failed_encoding_and_rejected_events_have_trace(self):
  for n in ['encode_failure','queue_and_ownership','raw_rejected']:
   p=self.fixture()/n;e=csvrows(p/'jpeg_shadow_events.csv');t=csvrows(p/'jpeg_shadow_worker_timing.csv');self.assertEqual(len(e),len(t));self.assertEqual({x['input_id'] for x in e},{x['input_id'] for x in t})
 def test_warmup_barrier_precedes_bag_and_camera_in_source(self):
  src=(run_control.WS/'src/zed_capture/src/capture_node.cpp').read_text();start=src.index(' int run()');self.assertLess(src.index('initShadow();',start),src.index('bag.open(',start));self.assertLess(src.index('bag.open(',start),src.index('camera->initializeVideo',start))
if __name__=='__main__':unittest.main(verbosity=2)
