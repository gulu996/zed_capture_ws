"""SYNTHETIC acceptance tests: do not turn strict raw FAIL into JPEG failure/PASS."""
import csv,json,pathlib,tempfile,unittest
from analyze_c4 import analyze
def save(p,data):p.write_text(json.dumps(data))
def csvwrite(p,rows):
 with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
class AcceptanceTests(unittest.TestCase):
 def fixture(self,root,late=False,rejected=False):
  s=root/'session';s.mkdir();j=root/'joint';j.mkdir();o=root/'output';o.mkdir()
  save(j/'test_result.json',{'session_path':str(s),'capture_runtime':'CAPTURE_RUNTIME_PASS','clock_diagnostic':'CLOCK_DIAGNOSTIC_PASS'})
  stream={'count':1,'long_intervals':0,'backwards':0,'duplicates':0,'fps':30}
  save(s/'check_result.json',{'capture_integrity':'FAIL','errors':['SYNTHETIC ZED IMU startup anomaly','SYNTHETIC anchor skips'],'streams':{t:stream for t in ['/zed2i/left/image_raw','/zed2i/right/image_raw','/livox/lidar','/livox/imu']},'stereo_sequence_and_stamps_equal':True,'cloud_structure_errors':0,'cloud_sequence_discontinuities':0,'cloud_empty_messages':0})
  save(s/'capture_summary.json',{'pairs_written':1,'video_sequence_gaps':0,'invalid_video_buffers':0})
  save(s/'jpeg_shadow_summary.json',{'inputs':1,'completed':0 if rejected else 1,'rejected':int(rejected),'event_log_ok':True,'unlogged_inputs':0,'queue_drained':True,'worker_joined':True,'queue_peak':1})
  csvwrite(s/'video_timestamps.csv',[{'pair_id':1,'sequence':0,'raw_ns':1000000000,'timestamp_type':8192,'timestamp_source':65536}])
  csvwrite(s/'jpeg_shadow_events.csv',[dict(pair_id=1,sequence=0,raw_ns=1000000000,timestamp_type=8192,timestamp_source=65536,left_seq=0,right_seq=0,left_sec=1,right_sec=1,left_nsec=0,right_nsec=0,left_frame_id='zed2i_left_raw',right_frame_id='zed2i_right_raw',copied_ns=1000000000,submitted_ns=1000000001,worker_start_ns=1000000002,completed_ns=1040000000 if late else 1020000000,convert_pair_ns=1000000,encode_pair_ns=1000000,left_jpeg_bytes=100,right_jpeg_bytes=100,sof_420=1,status='REJECTED' if rejected else 'COMPLETED',reason='QUEUE_FULL' if rejected else '')])
  return j,o
 def test_raw_integrity_remains_fail(self):
  with tempfile.TemporaryDirectory(prefix='C4_ANALYSIS_SYNTHETIC_') as t:
   j,o=self.fixture(pathlib.Path(t));r=analyze(j,o);self.assertEqual(r['DATA_INTEGRITY'],'FAIL');self.assertEqual(r['JPEG_SHADOW_COMPLETION'],'PASS');self.assertEqual(r['JPEG_SHADOW_LATENCY'],'PASS');self.assertEqual(r['L2B_MAPPING'],'PENDING')
 def test_deadline_not_relaxed(self):
  with tempfile.TemporaryDirectory(prefix='C4_ANALYSIS_SYNTHETIC_') as t:
   j,o=self.fixture(pathlib.Path(t),late=True);r=analyze(j,o);self.assertEqual(r['JPEG_SHADOW_COMPLETION'],'PASS');self.assertEqual(r['JPEG_SHADOW_LATENCY'],'FAIL')
 def test_rejection_fails_shadow_not_raw(self):
  with tempfile.TemporaryDirectory(prefix='C4_ANALYSIS_SYNTHETIC_') as t:
   j,o=self.fixture(pathlib.Path(t),rejected=True);r=analyze(j,o);self.assertEqual(r['JPEG_SHADOW_COMPLETION'],'FAIL');self.assertEqual(r['JPEG_SHADOW_QUEUE'],'FAIL');self.assertEqual(r['VIDEO_CONTINUITY'],'PASS')
if __name__=='__main__':unittest.main(verbosity=2)
