#!/usr/bin/env python3
import collections,copy,datetime,hashlib,importlib.util,io,json,os,pathlib,struct,subprocess,sys,tempfile,unittest
from unittest import mock
import independent_probe as probe
ROOT=pathlib.Path(__file__).resolve().parent
OLD=pathlib.Path('/home/jetson/catkin_ws/src')

def nmea(s):
    c=0
    for x in s:c^=ord(x)
    return '${}*{:02X}'.format(s,c)

class Tests(unittest.TestCase):
    def test_chunk_boundaries_raw_and_integer_clocks(self):
        out=io.StringIO();d=probe.Decoder(out);clock=probe.clock_sample()
        b=(nmea('GNZDA,123456.123456,18,10,2026,00,00')+'\r\n').encode()
        d.feed(b[:12],1,clock);self.assertEqual(out.getvalue(),'');d.feed(b[12:],2,clock)
        r=json.loads(out.getvalue());self.assertEqual(bytes.fromhex(r['raw_line_hex']),b[:-2]);self.assertEqual(r['chunk_id'],2)
        self.assertTrue(r['parsed'][0]['utc_valid']);self.assertFalse(r['parsed'][0]['mapping_valid'])
        self.assertIsInstance(r['receive_clocks']['monotonic_ns'],int)
    def test_checksum_and_unknown_crc(self):
        d=probe.Decoder(io.StringIO());c=probe.clock_sample()
        d.feed(b'$GNZDA,000000.0,18,10,2026,00,00*ZZ\n',1,c)
        self.assertEqual(d.counts['checksum_FAIL'],1)
        d.feed(b'#AGRICA,COM1;bad*00000000\n',2,c)
        self.assertEqual(d.counts['checksum_UNKNOWN_NOT_VERIFIED_BY_LEGACY'],1)
    def test_reconnect_does_not_glue_or_keep_date(self):
        out=io.StringIO();d=probe.Decoder(out);c=probe.clock_sample()
        d.feed(b'$KSXT,partial',1,c);d.discontinuity('DISCONNECT')
        d.feed((nmea('GNZDA,000000.0,18,10,2026,00,00')+'\n').encode(),2,c)
        self.assertEqual(d.counts['incomplete_lines'],1);self.assertEqual(d.sources['ZDA'],1)
    def test_bounded_overflow_and_unsupported_bytes(self):
        d=probe.Decoder(io.StringIO());c=probe.clock_sample();d.feed(b'x'*9000+b'\n',1,c)
        self.assertEqual(d.counts['oversize_lines'],1);self.assertLessEqual(len(d.buf),8192)
        d.feed(b'\xffunrecognized\n',2,c);self.assertEqual(d.counts['no_parsed_records'],1)
    def test_busy_port_refuses_before_open(self):
        with mock.patch.object(probe.subprocess,'run',return_value=type('R',(),dict(returncode=0,stdout='123',stderr=''))()),mock.patch.object(probe.os,'open') as op:
            with self.assertRaises(RuntimeError):probe.open_checked('/dev/ttyACM0')
            op.assert_not_called()
    def test_exclusive_precedes_settings_and_failure_closes(self):
        order=[]
        def ioctl(fd,cmd,*args):order.append(cmd);raise OSError('synthetic exclusive failure')
        with mock.patch.object(probe.subprocess,'run',return_value=type('R',(),dict(returncode=1,stdout='',stderr=''))()),mock.patch.object(probe.os,'open',return_value=99),mock.patch.object(probe.os,'close') as close,mock.patch.object(probe.fcntl,'flock'),mock.patch.object(probe.fcntl,'ioctl',side_effect=ioctl),mock.patch.object(probe.tty,'setraw') as settings:
            with self.assertRaises(OSError):probe.open_checked('/dev/ttyACM0')
            self.assertEqual(order,[probe.termios.TIOCEXCL]);settings.assert_not_called();close.assert_called_once_with(99)
    def test_clock_monotonicity(self):
        xs=[probe.clock_sample() for _ in range(50)]
        self.assertTrue(all(a['raw_before_ns']<=a['raw_after_ns'] for a in xs))
        self.assertTrue(all(a['monotonic_ns']<=b['monotonic_ns'] for a,b in zip(xs,xs[1:])))

def offline_bag(output):
    import rospy,rosbag
    rospy.rostime.set_rostime_initialized(True)
    for name in ['loginfo_throttle','logwarn_throttle']:setattr(rospy,name,lambda *a,**k:None)
    path=OLD/'gnss_serial_driver/scripts/gnss_serial_node.py'
    spec=importlib.util.spec_from_file_location('audited_old_gnss_node',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    n=module.GnssSerialNode.__new__(module.GnssSerialNode)
    for k,v in dict(timestamp_mode='host_local',sequence=0,mapping=None,last_local_measurement_ns=0,serial_open=False,checksum_errors=0,parse_errors=0,reconnect_count=0,timestamp_mapping_drop_count=0,raw_log=None,parsed_log=None,imu_time_mapper=None,replay_mode='preserve',replay_file='SYNTHETIC_FIXTURE',port='SYNTHETIC',gps_utc_leap_seconds=18,accepted_qualities={4},replay_has_pps_association=False).items():setattr(n,k,v)
    n.parser=probe.GnssParser();n._host_local=lambda t:(0,0,0,0)
    observed=[]
    class Pub:
        def __init__(self,topic):self.topic=topic
        def publish(self,m):observed.append((self.topic,copy.deepcopy(m)))
    for attr,topic in [('raw_pub','/gnss/raw'),('status_pub','/gnss/status_v2'),('local_pub','/gnss/pvt_local'),('compat_pub','/ublox_driver/receiver_pvt'),('utc_pub','/sensor_time/utc_observation')]:setattr(n,attr,Pub(topic))
    for line in (OLD/'sensor_recording_bringup/data/gnss_replay.txt').read_text().splitlines():n._handle_line(line,False)
    n._handle_line(nmea('GNGGA,104915.00,3016.447800,N,12009.309600,E,0,00,9.9,0.0,M,0.0,M,,'),False)
    bag=output/'synthetic_gnss.bag';assert not bag.exists()
    with rosbag.Bag(str(bag),'w') as b:
        for i,(topic,msg) in enumerate(observed):b.write(topic,msg,rospy.Time(1700000000,i*1000000))
    types={};counts=collections.Counter()
    with rosbag.Bag(str(bag),'r') as b:
        for topic,m,t in b.read_messages():
            counts[topic]+=1;types[topic]={'type':m._type,'md5':m._md5sum}
            if topic=='/gnss/pvt_local':assert m.utc_measurement_ns>0 and not m.local_measurement_time_valid and not m.valid_for_fusion and m.header.stamp.to_nsec()==0
            if topic=='/sensor_time/utc_observation':assert not m.valid and m.utc_stamp_ns>0
    for x in types.values():
        computed=subprocess.check_output(['rosmsg','md5',x['type']],text=True).strip();assert computed==x['md5'];x['source_md5_matches_generated']=True
    assert len(types)==5 and n.sequence==4
    result=dict(synthetic=True,hardware_test=False,all_records_deserialized=True,counts=dict(counts),messages=types,old_node_handle_line_reused=True,missing_mapping_does_not_discard_host_local_pvt=True,no_fix_raw_retained=True)
    (output/'offline_bag_test.json').write_text(json.dumps(result,indent=2));return result

if __name__=='__main__':
    out=ROOT/'software_results';out.mkdir(exist_ok=False)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    with (out/'tests.log').open('w') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    print('NEW_TESTS',result.testsRun,'PASS',result.wasSuccessful())
    if not result.wasSuccessful():raise SystemExit(1)
    print(json.dumps(offline_bag(out),indent=2))
