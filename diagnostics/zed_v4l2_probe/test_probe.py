#!/usr/bin/env python3
"""SYNTHETIC unit tests + read-only A regression; never open video hardware."""
import csv,json,os,pathlib,tempfile,unittest
from analyze import metrics,historical,comparison,native_mode_evidence,MODES,ROOT,read
from run import processes,probe_dependencies
class ProbeTests(unittest.TestCase):
    def test_probe_dependency_check_does_not_require_unused_hid(self):
        self.assertEqual(probe_dependencies()['errors'],[])
    def row(self,pair,seq,ns,event=None):
        return dict(event_id=event or pair,pair_id=pair,sequence=seq,v4l2_sec=ns//10**9,v4l2_usec=ns%10**9//1000,iteration_end_ns=ns+2,select_before_ns=ns,iteration_cpu_ns=1,select_result=1,dq_called=1,dq_result=0,dq_errno=0,qbuf_called=1,qbuf_result=0,payload_valid=1,bytesused=8294400,width=3840,height=1080,stride=7680)
    def test_normal(self):
        r=metrics([self.row(i+1,i,10**9+i*33333000) for i in range(10)]);self.assertEqual(r['long_intervals'],0);self.assertAlmostEqual(r['fps'],30.0003,places=4)
    def test_gap_not_physical_count(self):
        r=metrics([self.row(1,0,10**9),self.row(2,3,1066900000)]);self.assertEqual(r['driver_sequence_missing'],2);self.assertEqual(r['long_intervals'],1);self.assertEqual(r['physical_exposures_missing'],'UNKNOWN')
    def test_wrap_duplicate_reset(self):
        r=metrics([self.row(1,0xffffffff,10**9),self.row(2,0,1033333000),self.row(3,0,1066666000),self.row(4,0xffffffff,1099999000)])
        self.assertEqual(r['driver_sequence_missing'],0);self.assertEqual(r['sequence_duplicate'],1);self.assertEqual(r['sequence_reset_or_backward'],1)
    def test_startup_timeout(self):
        t=self.row(0,0,0,1);t.update(select_result=0,dq_called=0,qbuf_called=0)
        r=metrics([t,self.row(1,0,10**9,2)]);self.assertEqual(r['startup_select_timeouts'],1)
    def test_missing_event_rejected(self):
        self.assertFalse(metrics([self.row(1,0,10**9,2)])['event_ids_contiguous'])
    def test_busy_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)/'999999';p.mkdir();(p/'fd').mkdir();(p/'cmdline').write_bytes(b'/fake/zed_capture_node\0')
            self.assertTrue(processes(['/dev/video0'],pathlib.Path(tmp))['busy'])
    def test_busy_fd_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)/'999999';p.mkdir();(p/'fd').mkdir();(p/'cmdline').write_bytes(b'/fake/other\0');(p/'fd/4').symlink_to('/dev/video0')
            r=processes(['/dev/video0'],pathlib.Path(tmp));self.assertTrue(any(e['reason']=='ZED video node already open' for e in r['busy']))
    def test_latest_A(self):
        a=historical();m=a['metrics'];self.assertEqual(m['frames'],891);self.assertEqual(m['events'],893);self.assertEqual(m['long_intervals'],8);self.assertEqual(m['driver_sequence_missing'],16)
        self.assertEqual([e['pair_id'] for e in a['events']],[23,32,96,98,206,361,561,872]);self.assertTrue(all(not e['intervening_nonframe_events'] for e in a['events']))
    def test_failed_run_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp);rs=[self.row(1,0,10**9),self.row(2,1,31*10**9)]
            with (p/'video_io_events.csv').open('w') as f:
                w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
            (p/'probe_end.json').write_text(json.dumps({'returncode':2,'buffers':4,'completed_duration':True,'overflow':False,'fatal_io':False}))
            self.assertEqual(comparison(p)['low_load_runtime'],'FAIL')
    def native_fixture(self,p):
        # SYNTHETIC 720P metadata, never claimed to be a camera observation.
        (p/'session.json').write_text(json.dumps({'resolution_mode':'HD720','resolution':[2560,720]}))
        end={'returncode':0,'buffers':4,'completed_duration':True,'overflow':False,'fatal_io':False,'resolution_mode':'HD720','negotiated_verified':True,'after_settings_verified':True}
        (p/'probe_end.json').write_text(json.dumps(end))
        enum={'requested':'HD720','width':2560,'height':720,'pixel_format':'YUYV','enumeration_complete':True,'requested_mode_enumerated':True,
          'VIDIOC_ENUM_FMT':[{'result':0,'fourcc':int.from_bytes(b'YUYV','little')}],
          'VIDIOC_ENUM_FRAMESIZES':[{'result':0,'type':1,'width':2560,'height':720}],
          'VIDIOC_ENUM_FRAMEINTERVALS':[{'result':0,'type':1,'numerator':333333,'denominator':10000000}]}
        (p/'v4l2_enumeration.json').write_text(json.dumps(enum))
        fmt={'format_result':0,'parm_result':0,'width':2560,'height':720,'fourcc':int.from_bytes(b'YUYV','little'),'stride':5120,'sizeimage':3686400,'interval_numerator':1,'interval_denominator':30}
        (p/'v4l2_negotiated.json').write_text(json.dumps(fmt))
        rs=[dict(self.row(i+1,i,10**9+i*33333000),bytesused=3686400,width=2560,height=720,stride=5120) for i in range(901)]
        with (p/'video_io_events.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
        return fmt,enum,end
    def test_native720_positive_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp);self.native_fixture(p);r=comparison(p)
            self.assertEqual(r['NATIVE_720P_SUPPORTED'],'VERIFIED');self.assertEqual(r['LOW_LOAD_720P_RUNTIME'],'PASS');self.assertEqual(r['LOW_LOAD_720P_CONTINUITY'],'PASS')
            self.assertEqual(r['B']['frames'],901);self.assertIn('not a controlled',r['interpretation'])
    def test_native720_reject_negotiation_fallback(self):
        for key,value in [('width',3840),('height',1080),('fourcc',int.from_bytes(b'MJPG','little')),('interval_denominator',15),('parm_result',-1),('stride',7680)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as tmp:
                p=pathlib.Path(tmp);fmt,_,_=self.native_fixture(p);fmt[key]=value;(p/'v4l2_negotiated.json').write_text(json.dumps(fmt))
                self.assertEqual(comparison(p)['LOW_LOAD_720P_RUNTIME'],'FAIL')
    def test_native720_missing_actual_enumeration(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp);self.native_fixture(p);(p/'v4l2_enumeration.json').unlink()
            self.assertEqual(comparison(p)['NATIVE_720P_SUPPORTED'],'UNVERIFIED')
    def test_native720_wrong_enumerated_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp);_,enum,_=self.native_fixture(p);enum['VIDIOC_ENUM_FRAMEINTERVALS'][0].update(numerator=1,denominator=60)
            (p/'v4l2_enumeration.json').write_text(json.dumps(enum));self.assertFalse(native_mode_evidence(p,'HD720')['verified'])
    def test_native720_keeps_gap_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp);self.native_fixture(p);rs=read(p/'video_io_events.csv')
            for r in rs[100:]:
                ns=r['v4l2_sec']*10**9+r['v4l2_usec']*1000+33333000;r.update(sequence=r['sequence']+2,v4l2_sec=ns//10**9,v4l2_usec=ns%10**9//1000)
            with (p/'video_io_events.csv').open('w') as f:
                w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
            r=comparison(p);self.assertEqual(r['LOW_LOAD_720P_RUNTIME'],'PASS');self.assertEqual(r['LOW_LOAD_720P_CONTINUITY'],'FAIL');self.assertEqual(r['B']['long_intervals'],1);self.assertEqual(r['B']['driver_sequence_missing'],2)
    def test_old1080_b_still_continuous(self):
        r=metrics(read(ROOT/'runs/probe_20261017_152106_349a1c1e/video_io_events.csv'))
        self.assertEqual(MODES['HD1080'],(3840,1080));self.assertEqual(r['frames'],898);self.assertEqual(r['long_intervals'],0);self.assertEqual(r['driver_sequence_missing'],0)
    def test_uvc_old_flow_explanation_is_only_synthetic(self):
        # Abstract the old v5.10 ordering, not a kernel or USB packet emulator:
        # good A(0), partial B(1), new C boundary counted once before retry,
        # and once on retry because last_fid was not yet changed.
        sequence=0;last_fid=0
        def boundary(fid,old_partial):
            nonlocal sequence,last_fid
            if fid!=last_fid:sequence+=1
            if old_partial:return 'RETRY'
            last_fid=fid;return sequence
        self.assertEqual(boundary(1,False),1)
        self.assertEqual(boundary(0,True),'RETRY')
        self.assertEqual(boundary(0,False),3)
        # Demonstrates a possible +3 counter over two frame periods, not that
        # the Tegra binary/camera really took this branch.
if __name__=='__main__':unittest.main(verbosity=2)
