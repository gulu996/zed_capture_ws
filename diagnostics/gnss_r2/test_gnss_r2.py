#!/usr/bin/env python3
"""Software only. Real byte fixtures; synthetic clocks/faults explicitly identified."""
import collections,hashlib,io,json,math,os,pathlib,subprocess,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parents[1]/'scripts'))
from gnss_r2_core import Stream,TOPICS,message_types,messages
from gnss_receiver import Evidence,write_all
from gnss_config import gnss_arguments,gnss_preflight
from gnss_r1_compat import Adapter,frames
IN=ROOT/'preparation_20261018_155919/incoming/gnss_r1_20261018'
REAL=IN/'inputs/jetson/zed_capture_ws/diagnostics/gnss_usb/runs/independent_20261018_151102_0ed1de0b'
HISTORY=IN/'inputs/history/gps_imu_recv_20260723_104943.txt'
# Explicitly synthetic receive-clock envelope for historical logs without host clocks.
CLOCK=dict(raw_before_ns=1000000000,monotonic_ns=1000000020,realtime_ns=1700000000000000000,raw_after_ns=1000000040,raw_bracket_ns=40)
def decode(raw,step=4096):
    rows=[];s=Stream(rows.append)
    for i in range(0,len(raw),step):s.feed(raw[i:i+step],i//step+1,CLOCK)
    s.finish();return s,rows
class Test(unittest.TestCase):
    def test_stream_real_chunk_partition_and_r1_identical(self):
        raw=(REAL/'serial_raw.bin').read_bytes();rows=[];s=Stream(rows.append)
        for c in map(json.loads,(REAL/'chunks.jsonl').read_text().splitlines()):
            s.feed(raw[c['byte_offset']:c['byte_offset']+c['byte_count']],c['chunk_id'],c['receive_clocks'])
        s.finish();reference=list(frames(raw));a=Adapter()
        self.assertEqual(b''.join(bytes.fromhex(r['raw_hex']) for r in rows),raw)
        self.assertEqual([r['raw_hex'] for r in rows],[r['raw_hex'] for r in reference])
        self.assertEqual(len(rows),546)
        for r in rows:
            old=a.parse(bytes.fromhex(r['raw_hex']))
            for key in ('source','checksum_valid','raw_quality','utc_valid','utc_measurement_ns','solution_quality'):
                self.assertEqual(r['parsed'][key],old[key])
        self.assertEqual(s.counts['checksum_valid_records'],544)
        self.assertEqual(sum(r['recovery_reason']=='RESYNC_AFTER_TRUNCATED_AGRICA' for r in rows),1)
        self.assertEqual(s.protocols['UNIHEADINGA'],78)
        self.assertEqual(s.counts['utc_valid'],0)
    def test_no_fix_raw_persistence_with_actual_three_clocks(self):
        raw=(REAL/'serial_raw.bin').read_bytes();published=[]
        with tempfile.TemporaryDirectory(prefix='gnss_r2_') as tmp:
            e=Evidence(pathlib.Path(tmp)/'gnss',123,456,lambda i,m:published.append((i,m)))
            for c in map(json.loads,(REAL/'chunks.jsonl').read_text().splitlines()):e.feed(raw[c['byte_offset']:c['byte_offset']+c['byte_count']],c['receive_clocks'])
            e.close('END_OF_TEST');summary=e.summary()
            self.assertEqual(hashlib.sha256((e.out/'serial_raw.bin').read_bytes()).hexdigest(),hashlib.sha256(raw).hexdigest())
            self.assertEqual(summary['raw_bytes'],53472)
            self.assertEqual(b''.join(bytes(m.data) for i,m in published if i==0),raw)
            self.assertTrue(all(not m.valid_for_fusion and not m.local_measurement_time_valid for i,m in published if i in (1,2)))
            self.assertTrue(all(m.utc_measurement_ns==0 and not m.utc_valid for i,m in published if i==2))
            self.assertFalse(any(i==4 for i,m in published));self.assertEqual(summary['host_clock_errors'],0)
    def test_bounded_fragment_and_disconnect_preserve_bytes(self):
        raw=b'x'*20000+b'\r\n$unfinished';s,rows=decode(raw,7)
        self.assertEqual(b''.join(bytes.fromhex(r['raw_hex']) for r in rows),raw)
        self.assertTrue(all(len(bytes.fromhex(r['raw_hex']))<=8192 for r in rows))
        self.assertFalse(s.buf);self.assertIsNone(s.adapter.date_reference_ns)
        self.assertTrue(any(r['recovery_reason']=='OVERSIZE_FRAGMENT' for r in rows))
    def test_bytewise_crlf_boundaries(self):
        raw=b'a\r\nb\rc\n\r\nlast';_,rows=decode(raw,1)
        self.assertEqual([r['raw_hex'] for r in rows],[r['raw_hex'] for r in frames(raw)])
    def test_historical_quality_time_backwards_and_duplicates(self):
        s,rows=decode(HISTORY.read_bytes());self.assertGreater(s.counts['utc_backwards'],0);self.assertGreater(s.counts['utc_duplicates'],0)
        self.assertTrue(any(r['utc_delta_ns']==-100000000 for r in rows))
        found=collections.Counter()
        for r in rows:
            p=r['parsed']
            if p['source'] in ('KSXT','AGRICA','GGA') and p['solution_quality'] in (3,4):found[p['source'],p['solution_quality']]+=1
            if p['source']=='AGRICA' and p['utc_valid'] and p['raw_quality']==0:found['FINE_NO_FIX']+=1
        for source in ('KSXT','AGRICA','GGA'):
            for q in (3,4):self.assertGreater(found[source,q],0)
        self.assertEqual(found['FINE_NO_FIX'],1003)
    def test_ros_types_semantics_unknown_fields(self):
        _,rows=decode(HISTORY.read_bytes());types=message_types();checked=set()
        for row in rows:
            p=row['parsed'];key=(p['source'],p['raw_quality'],p['utc_valid'])
            if key in checked:continue
            checked.add(key)
            for i,m in messages(row,123,456):
                self.assertEqual((m._type,m._md5sum),TOPICS[i][1:])
                stream=io.BytesIO();m.serialize(stream);restored=types[i]().deserialize(stream.getvalue());other=io.BytesIO();restored.serialize(other);self.assertEqual(stream.getvalue(),other.getvalue())
                if i==0:self.assertEqual(m.timestamp_source,m.INVALID)
                if i in (1,2):self.assertFalse(m.valid_for_fusion or m.local_measurement_time_valid or m.mapping_version)
                if i==2:
                    self.assertEqual(m.utc_measurement_ns,p['utc_measurement_ns']);self.assertEqual(m.header.stamp.to_nsec(),0)
                    self.assertEqual(m.local_measurement_ns,0);self.assertTrue(math.isnan(m.pvt.p_dop))
                    self.assertTrue(math.isnan(m.pvt.altitude))
                if i==4:self.assertFalse(m.valid);self.assertEqual(m.local_stamp_ns,0);self.assertEqual(m.utc_stamp_ns,p['utc_measurement_ns'])
        self.assertGreater(len(checked),15)
    def test_short_write_and_disk_failure(self):
        class Short(io.BytesIO):
            def write(self,b):return super().write(b[:3])
        f=Short();write_all(f,b'abcdefgh');self.assertEqual(f.getvalue(),b'abcdefgh')
        class Failed:
            def write(self,b):return 0
        with self.assertRaises(OSError):write_all(Failed(),b'a')
        with open('/dev/full','wb',buffering=0) as f:
            with self.assertRaises(OSError):write_all(f,b'x')
    def test_gnss_disabled_and_opt_in(self):
        import yaml
        configs=ROOT.parents[1]/'src/zed_capture/config'
        for path in configs.glob('*.yaml'):
            cfg=yaml.safe_load(path.read_text())
            if path.name in ('capture_hd720_c5f_gnss.yaml','capture_hd720_c5g.yaml'):self.assertEqual(gnss_arguments(cfg,30),['_gnss_enable:=true'])
            else:self.assertEqual(gnss_arguments(cfg,30),['_gnss_enable:=false']);self.assertEqual(gnss_preflight(cfg,30),{'enabled':False,'errors':[]})
        cfg=yaml.safe_load((configs/'capture_hd720_c5f_gnss.yaml').read_text())
        for key,value in [('gnss_port','/dev/ttyACM0'),('gnss_rts',True),('storage_mode','raw_bag'),('gnss_baud',115200)]:
            bad=dict(cfg);bad[key]=value
            with self.assertRaises(ValueError):gnss_arguments(bad,30)
        with self.assertRaises(ValueError):gnss_arguments(cfg,31)

def make_fixture(out):
    """Actual R1 input with explicit SYNTHETIC receive times, not live acquisition."""
    import rosbag,genpy
    out=pathlib.Path(out);out.mkdir(exist_ok=False)
    _,rows=decode(HISTORY.read_bytes());selected=[];seen=set()
    for r in rows:
        p=r['parsed'];key=(p['source'],p['raw_quality'],p['utc_valid'])
        if key not in seen or (r['utc_delta_ns'] is not None and r['utc_delta_ns']<=0):selected.append(r);seen.add(key)
    # Include complete real indoor NO_FIX/corruption/recovery sequence.
    _,indoor=decode((REAL/'serial_raw.bin').read_bytes());selected+=indoor
    # Strictly increasing BAG reception times only, never alter original measurement fields.
    # The rows' receive envelope is explicitly SYNTHETIC because historical logs lack it.
    with rosbag.Bag(str(out/'input_messages.bag'),'w') as bag:
        for j,row in enumerate(selected):
            for i,m in messages(row,123,456):bag.write(TOPICS[i][0],m,genpy.Time(1700000000,j*1000))
    (out/'fixture.json').write_text(json.dumps(dict(hardware_run=False,receive_clocks='SYNTHETIC',
        protocol_bytes='REAL historical/indoor fixtures; no reordering within each input',source_records=len(selected),
        raw_input_sha256=hashlib.sha256(HISTORY.read_bytes()).hexdigest()),indent=2)+'\n')
if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':make_fixture(sys.argv[2])
    else:unittest.main(verbosity=2)
