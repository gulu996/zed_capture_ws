#!/usr/bin/env python3
"""SYNTHETIC CSV faults, plus read-only regression of the real legacy sidecars."""
import csv,json,pathlib,tempfile,unittest
from analyze_io_diagnostics import audit
WS=pathlib.Path(__file__).resolve().parents[1]

class TestIoEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='capture_io_synthetic_');self.p=pathlib.Path(self.tmp.name)
        # Read field declarations to avoid letting drift in a header go unnoticed.
        src=(WS/'src/zed_capture/src/capture_node.cpp').read_text()
        def fields(stream):return src.split(stream+'<<"',1)[1].split('\\n"',1)[0].split(',')
        self.v=[];self.h=[]
        for i in range(2):
            v=dict.fromkeys(fields('video_io'),0)
            v.update(event_id=i+1,pair_id=i+1,select_before_ns=10+i*100,select_after_ns=20+i*100,select_result=1,dq_called=1,buffer_valid=1,sequence=i,v4l2_sec=1,v4l2_usec=33333*i,flags=8192,qbuf_called=1,qbuf_end_ns=30+i*100,iteration_end_ns=31+i*100)
            h=dict.fromkeys(fields('hid_io'),0)
            h.update(read_id=i+1,sample_id=i+1,read_before_ns=10+i*100,read_after_ns=25+i*100,result=64,tick_present=1,device_ticks=64+i*64,raw_callback_end_ns=30+i*100,libusb_arrival_monotonic_ns=15+i*100,dequeue_monotonic_ns=20+i*100,completed_reports=i+1,consumed_reports=i+1,queue_peak=1,transfer_completed=i+1,had_previous_tick=i,tick_delta=64 if i else 0,host_interval_ns=100 if i else 0)
            self.v.append(v);self.h.append(h)
        self.summary={'low_level_diagnostics_version':1,'video_io_events_written':2,'hid_io_events_written':2}
        self.save_raw();self.save()
    def tearDown(self):self.tmp.cleanup()
    def write(self,name,data):
        with (self.p/name).open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    def save_raw(self):
        self.write('video_timestamps.csv',[{'pair_id':r['pair_id'],'sequence':r['sequence'],'raw_ns':r['v4l2_sec']*10**9+r['v4l2_usec']*1000,'flags':r['flags']} for r in self.v if r['pair_id']])
        self.write('zed_imu_raw.csv',[{'sample_id':r['sample_id'],'device_ticks':r['device_ticks'],'read_after_ns':r['read_after_ns'],'raw_hex':(bytes([1,0])+r['device_ticks'].to_bytes(8,'little')+bytes(r['result']-10)).hex()} for r in self.h if r['result']>0])
    def save(self):
        (self.p/'capture_summary.json').write_text(json.dumps(self.summary));self.write('video_io_events.csv',self.v);self.write('hid_io_events.csv',self.h)
    def test_complete(self):self.assertEqual(audit(self.p)['status'],'OBSERVED_COMPLETE')
    def test_missing_event(self):
        self.v[1]['event_id']=3;self.save();self.assertIn('event_id missing/duplicate/reset',audit(self.p)['errors'])
    def test_sequence_tamper(self):
        self.v[1]['sequence']=9;self.save();self.assertIn('video event/raw metadata mismatch',audit(self.p)['errors'])
    def test_hid_queue_drop_detected(self):
        self.h[-1].update(completed_reports=3,queue_discards=1);self.save();self.assertIn('observed HIDAPI queue discard',audit(self.p)['errors'])
    def test_62_byte_report_tick(self):
        for h in self.h:h['result']=62
        self.save_raw();self.save();self.assertEqual(audit(self.p)['status'],'OBSERVED_COMPLETE')
        self.h[-1]['device_ticks']+=1;self.save();self.assertIn('HID tick mismatch',audit(self.p)['errors'])
    def test_missing_file(self):
        (self.p/'hid_io_events.csv').rename(self.p/'unavailable.csv');self.assertEqual(audit(self.p)['status'],'FAIL')
    def test_truncated_row(self):
        with (self.p/'video_io_events.csv').open('a') as f:f.write('3,0\n')
        self.assertEqual(audit(self.p)['status'],'FAIL')
    def test_timeout_in_gap_not_hidden(self):
        t=dict.fromkeys(self.v[0],0);t.update(event_id=2,select_before_ns=40,select_after_ns=100,iteration_end_ns=101,select_timeouts=1)
        self.v[1].update(event_id=3,sequence=8,v4l2_usec=133905,select_timeouts=1)
        self.v.insert(1,t);self.summary['video_io_events_written']=3;self.save_raw();self.save()
        r=audit(self.p);self.assertEqual(r['status'],'OBSERVED_COMPLETE');self.assertEqual(r['video']['select_timeouts'],1)
        g=r['video']['gap_events'][0];self.assertEqual(g['driver_ids_missing'],7);self.assertEqual(g['intervening_events'][0]['select_result'],0)
        # Complete diagnostics are not a DATA_INTEGRITY PASS.
    def test_legacy_not_falsely_claimed(self):
        self.summary={};self.save();self.assertEqual(audit(self.p)['status'],'UNAVAILABLE_IN_LEGACY_SESSION')
    def test_real_legacy_metadata_unchanged(self):
        p=pathlib.Path('/home/jetson/zed_capture_data/20261017_130643_750bf403')
        self.assertEqual(audit(p)['status'],'UNAVAILABLE_IN_LEGACY_SESSION')
        with (p/'video_timestamps.csv').open() as f:v=list(csv.DictReader(f))
        gaps=[(int(b['pair_id']),(int(b['sequence'])-int(a['sequence']))&0xffffffff,int(b['raw_ns'])-int(a['raw_ns'])) for a,b in zip(v,v[1:]) if (int(b['sequence'])-int(a['sequence']))&0xffffffff!=1]
        self.assertEqual(len(v),887);self.assertEqual(len(gaps),10);self.assertEqual(sum(g[1]-1 for g in gaps),24);self.assertIn((374,7,133905000),gaps)
        with (p/'zed_imu_raw.csv').open() as f:h=list(csv.DictReader(f))
        ticks=[int(b['device_ticks'])-int(a['device_ticks']) for a,b in zip(h,h[1:])]
        self.assertEqual(len(h),12190);self.assertEqual(sorted(d for d in ticks if d>96),[128,128,128,192,192]);self.assertTrue(all(d>0 for d in ticks))

if __name__=='__main__':unittest.main(verbosity=2)
