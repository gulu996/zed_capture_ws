import io,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
import genpy
from gnss_receiver import Evidence,open_checked
from test_gnss_r2 import CLOCK
class Test(unittest.TestCase):
 def test_publish_serialization_failure_preserves_raw_and_classifies(self):
  with tempfile.TemporaryDirectory(prefix='GNSS_R2_SYNTHETIC_fault_') as tmp:
   def fail(i,m):raise genpy.SerializationError('SYNTHETIC injected serialization failure')
   e=Evidence(pathlib.Path(tmp)/'gnss',1,2,fail)
   data=b'$GNRMC,,V,,,,,,,,,,N,V*37\r\n'
   with self.assertRaises(genpy.SerializationError):e.feed(data,CLOCK)
   e.close('PUBLISH_FAILURE')
   self.assertEqual((e.out/'serial_raw.bin').read_bytes(),data)
   self.assertEqual(e.serialization_errors[0],1);self.assertEqual(e.publication_errors[0],1)
   self.assertEqual(len((e.out/'lines.jsonl').read_text().splitlines()),1)
   self.assertEqual(json.loads((e.out/'publication_events.jsonl').read_text())['topic'],'/gnss/raw')
 def test_busy_serial_never_opens(self):
  import types
  with patch('gnss_receiver.identity',return_value={'node':'/dev/SYNTHETIC'}),patch('gnss_receiver.subprocess.run',return_value=types.SimpleNamespace(returncode=0,stdout='123',stderr='')),patch('gnss_receiver.os.open') as opened:
   with self.assertRaises(RuntimeError):open_checked('/dev/SYNTHETIC')
   opened.assert_not_called()
 def test_receiver_clock_order_and_residual(self):
  with tempfile.TemporaryDirectory(prefix='GNSS_R2_SYNTHETIC_residual_') as tmp:
   e=Evidence(pathlib.Path(tmp)/'gnss',1,2,lambda *_:None)
   e.stream.adapter.date_reference_ns=123
   e.feed(b'incomplete',CLOCK);e.serial_open=False;e.close('DISCONNECT')
   row=json.loads((e.out/'lines.jsonl').read_text());self.assertEqual(row['recovery_reason'],'DISCONNECT')
   self.assertFalse(row['serial_open']);self.assertEqual(bytes.fromhex(row['raw_hex']),b'incomplete')
   self.assertIsNone(e.stream.adapter.date_reference_ns);self.assertFalse(row['parsed']['utc_valid'])
if __name__=='__main__':unittest.main(verbosity=2)
