"""Software only: observer cannot request stop; independent field policies."""
import unittest,subprocess,sys,time,tempfile,signal,json,io,contextlib
from pathlib import Path
from unittest.mock import patch
import field_capture as f,field_common as c,field_policy as policy
from test_field import Processes
import yaml
class Continuous(unittest.TestCase):
    def test_receiver_guard_no_legacy_cap(self):
        cfg=yaml.safe_load(f.CONFIG.read_text())
        self.assertEqual(policy.guard_seconds(cfg,0),float('inf'))
        for duration in [30,300,1200,7200]:self.assertEqual(policy.guard_seconds(cfg,duration),duration+60)
        for duration in [-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):policy.validate(cfg,duration)
    def test_observer_actual_process_ctrlc_and_hup(self):
        helper=Processes()
        with tempfile.TemporaryDirectory(prefix='C5I_SYNTHETIC_OBSERVER_') as tmp:
            p=Path(tmp)/'SYNTHETIC_SESSION';p.mkdir();manager=helper.launch_fixture(p,'hup_stop')
            try:
                helper.await_file(p/'capture_metrics.jsonl')
                for sig in (signal.SIGINT,signal.SIGHUP):
                    code="from pathlib import Path;import field_capture as f;raise SystemExit(f.wait_status(Path(%r),False,True))"%str(p)
                    with (p/('observer_%d.log'%sig)).open('x') as log:
                        observer=subprocess.Popen([sys.executable,'-B','-c',code],cwd=str(c.HERE),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    time.sleep(1.3);self.assertIsNone(observer.poll());self.assertIsNone(manager.poll())
                    observer.send_signal(sig);observer.wait(timeout=5)
                    self.assertFalse((p/'field_stop_request.json').exists());self.assertIsNone(manager.poll())
                self.assertEqual(c.request_stop(p),'STOP_REQUESTED');self.assertEqual(manager.wait(timeout=15),0)
                self.assertTrue(c.load(p/'capture_finalization.json')['BAG_FINALIZED'])
            finally:
                if manager.poll() is None:c.request_stop(p);manager.wait(timeout=15)
    def test_status_read_has_no_side_effect(self):
        p=c.ROOT/'20261019_141336_6cfd54e4'
        before={x.name:(x.stat().st_size,x.stat().st_mtime_ns) for x in p.iterdir() if x.is_file()}
        for _ in range(10):self.assertEqual(f.view(p)['state'],'FINALIZED')
        after={x.name:(x.stat().st_size,x.stat().st_mtime_ns) for x in p.iterdir() if x.is_file()}
        self.assertEqual(before,after)
    def test_gnss_parser_code_unchanged(self):
        original=(c.WS/'diagnostics/gnss_r2/gnss_receiver.py').read_text()
        field=(c.HERE/'gnss_field.py').read_text()
        field=field.replace("sys.path.insert(0,'/home/jetson/zed_capture_ws/diagnostics/gnss_r2')\n",'').replace('from field_policy import validate as long_validate,guard_seconds','from long_recording import validate as long_validate,guard_seconds')
        self.assertEqual(original,field)
    def test_checker_only_segment_adaptation(self):
        original=(c.WS/'scripts/checker_strict.py').read_text()
        updated=(c.HERE/'checker_strict_field.py').read_text()
        updated=updated.replace("gnss is not None and (path.name=='sensors.bag' or path.name.startswith('sensors_'))","gnss is not None and path.name=='sensors.bag'").replace('index_records+=index_budget(bag,0)  # budget is per independently released segment index','index_records=index_budget(bag,index_records)')
        self.assertEqual(original,updated)
if __name__=='__main__':unittest.main(verbosity=2)
