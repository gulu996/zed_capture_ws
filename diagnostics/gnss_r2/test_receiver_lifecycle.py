"""SYNTHETIC serial/ROS services around real recorded bytes; never opens a tty."""
import json,os,pathlib,sys,tempfile,types,unittest
from unittest.mock import patch
import gnss_receiver as receiver
from test_gnss_r2 import REAL,CLOCK
receiver.message_types() # Preload generated/numpy modules before scoped sys.modules mock.
class Test(unittest.TestCase):
 def run_case(self,disconnect):
  with tempfile.TemporaryDirectory(prefix='GNSS_R2_SYNTHETIC_lifecycle_') as tmp:
   root=pathlib.Path(tmp);(root/'session.json').write_text(json.dumps(dict(config={'gnss_enable':True},boot_id='SYNTHETIC_BOOT',synthetic_fixture=True)))
   data=(REAL/'serial_raw.bin').read_bytes();packets=[data[i:i+4096] for i in range(0,len(data),4096)];index=[0];pubs={}
   class Publisher:
    def __init__(self,topic,*args,**kwargs):self.topic=topic;pubs[topic]=[]
    def get_num_connections(self):return 1
    def publish(self,m):pubs[self.topic].append(m)
   fake_ros=types.SimpleNamespace(init_node=lambda *a,**k:None,Publisher=Publisher,is_shutdown=lambda:False)
   def read(fd,n):
    self.assertEqual(fd,123456)
    if disconnect and index[0]==1:raise OSError('SYNTHETIC disconnect')
    value=packets[index[0]];index[0]+=1
    if index[0]==len(packets):(root/'gnss/stop').write_text('SYNTHETIC recorder stop')
    return value
   def sleep(_):
    if (root/'gnss/done').exists():(root/'gnss/ack').write_text('SYNTHETIC subscriber ack')
   actual_close=os.close
   with patch.dict(sys.modules,{'rospy':fake_ros}),patch.object(sys,'argv',['receiver','--session',str(root)]),patch.object(receiver.os,'geteuid',return_value=1000),patch.object(receiver,'open_checked',return_value=(123456,{'synthetic':True})),patch.object(receiver.os,'read',side_effect=read),patch.object(receiver.os,'close',side_effect=lambda fd:None if fd==123456 else actual_close(fd)),patch.object(receiver.select,'select',return_value=([123456],[],[])),patch.object(receiver,'clock_sample',return_value=CLOCK),patch.object(receiver.time,'sleep',side_effect=sleep),patch.object(receiver.signal,'signal'):
    code=receiver.main()
   summary=json.loads((root/'gnss/summary.json').read_text());self.assertTrue(summary['synthetic'])
   self.assertEqual(code,2 if disconnect else 0)
   self.assertEqual((root/'gnss/serial_raw.bin').read_bytes(),data[:4096] if disconnect else data)
   done=list(map(int,(root/'gnss/done').read_text().split()));self.assertEqual(done[0],int(disconnect))
   self.assertEqual(done[1:],[len(pubs[t[0]]) for t in receiver.TOPICS]);self.assertFalse(pubs['/sensor_time/utc_observation'])
   if disconnect:self.assertIn('SYNTHETIC disconnect',summary['errors'][0])
 def test_normal_no_fix_stop_and_flush(self):self.run_case(False)
 def test_disconnect_fails_preserves_received_residual(self):self.run_case(True)
if __name__=='__main__':unittest.main(verbosity=2)
