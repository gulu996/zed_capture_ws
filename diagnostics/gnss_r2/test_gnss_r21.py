#!/usr/bin/env python3
"""Offline regression. Synthetic counterexamples are not hardware evidence."""
import csv, hashlib, json, pathlib, shutil, subprocess, sys, unittest
from test_gnss_r2 import ROOT, CLOCK, decode
from gnss_r2_core import Stream, messages, TOPICS, message_types, clean
from gnss_r21_compat import split_record
from gnss_r1_compat import checksum, split_record as old_split
from gnss_receiver import Evidence

SESSION=pathlib.Path('/home/jetson/zed_capture_data/20261018_174130_d85a69b1')
PREFIX=b'$GNGGA,,,,,,0,,,'
RMC=b'$GNRMC,,V,,,,,,,,,,N,V*37\r\n'
FAULT=PREFIX+RMC

def nmea(body):
    value=0
    for b in body:value^=b
    return b'$'+body+b'*'+('%02X'%value).encode()+b'\r\n'

def replay_rows():
    raw=(SESSION/'gnss/serial_raw.bin').read_bytes();out=[];stream=Stream(out.append)
    for c in map(json.loads,(SESSION/'gnss/chunks.jsonl').read_text().splitlines()):
        stream.feed(raw[c['byte_offset']:c['byte_offset']+c['byte_count']],c['chunk_id'],c['receive_clocks'])
    stream.finish();return raw,stream,out

class Regression(unittest.TestCase):
    def test_real_bytes_ranges_chunks_clocks(self):
        raw,s,rows=replay_rows()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'dbdf7922bac9a73e9d9f1ca1a153bc0e2ac2515a4242617f266d58a141483a51')
        self.assertEqual(b''.join(bytes.fromhex(r['raw_hex']) for r in rows),raw)
        a,b=[r for r in rows if r['source_sequence']==22]
        self.assertEqual((a['byte_begin'],a['byte_end'],b['byte_begin'],b['byte_end']),(2058,2074,2074,2101))
        self.assertEqual((a['chunk_first'],a['chunk_last'],b['chunk_first'],b['chunk_last']),(3,3,4,4))
        chunks=list(map(json.loads,(SESSION/'gnss/chunks.jsonl').read_text().splitlines()))
        for r in (a,b):
            self.assertEqual(r['receive_clocks'],chunks[3]['receive_clocks'])
            self.assertEqual((r['parent_byte_begin'],r['parent_byte_end']),(2058,2101))
            self.assertEqual((r['parent_chunk_first'],r['parent_chunk_last']),(3,4))
            self.assertEqual(r['fragment_receive_clocks'],chunks[r['chunk_last']-1]['receive_clocks'])
        self.assertFalse(a['parsed']['checksum_valid']);self.assertIsNone(a['parsed']['pvt'])
        self.assertTrue(b['parsed']['checksum_valid']);self.assertEqual(b['parsed']['source'],'RMC')
        self.assertEqual(b['parsed']['time_fields']['status'],'V')
        self.assertFalse(b['parsed']['utc_valid'] or b['parsed']['position_valid'])
        self.assertEqual(s.counts['records'],1142);self.assertEqual(s.counts['checksum_errors'],1)
        self.assertEqual(s.counts['checksum_valid_records'],1141);self.assertEqual(s.protocols['RMC'],163)
        old=list(map(json.loads,(SESSION/'gnss/lines.jsonl').read_text().splitlines()))
        # Every unaffected parsed row and original clock is identical, in source order.
        unaffected={r['source_sequence']:r for r in rows if r['source_sequence']!=22}
        for r in old:
            if r['source_sequence']==22:continue
            for key in ('raw_hex','byte_begin','byte_end','chunk_first','chunk_last','receive_clocks','parsed','utc_delta_ns'):
                self.assertEqual(r[key],clean(unaffected[r['source_sequence']][key]))

    def test_complete_parent_valid_even_with_marker(self):
        for body in (b'GNGGA,,,,,,0,,,,,,,,',PREFIX[1:]+RMC[1:].split(b'*')[0],b'GNGGA,,,,,,0,,,$GNRMC,quoted_payload'):
            raw=nmea(body);self.assertTrue(checksum(raw)['checksum_valid'])
            self.assertEqual(split_record(raw),[(raw,'NONE')])

    def test_checksum_bad_missing_or_incomplete_tail_not_recovered(self):
        for tail in (RMC.replace(b'*37',b'*36'),RMC[:-2],RMC.replace(b'*37',b'*3'),RMC+b'junk',RMC.replace(b'*37',b'')):
            raw=PREFIX+tail;self.assertEqual(split_record(raw),[(raw,'NONE')])

    def test_unknown_prefix_payload_and_multiple_markers_not_recovered(self):
        for prefix in (b'$GNGGA,123,',b'$GNGGA,,,,,,4,,,',b'$GNGGA,"',b'garbage',b'$GPGST,',PREFIX+b'X',PREFIX+b',,,,,,'):
            raw=prefix+RMC;self.assertEqual(split_record(raw),[(raw,'NONE')])
        for raw in (PREFIX+RMC+RMC,PREFIX+nmea(b'GNRMC,$foo,V,,,,,,,,,,N,V')):
            self.assertEqual(split_record(raw),[(raw,'NONE')])

    def test_tail_structure_required_even_with_valid_xor(self):
        for body in (b'GNRMC,V',b'GNRMC,,X,,,,,,,,,,N,V',b'GLRMC,,V,,,,,,,,,,N,V',b'GNRMC,,V,,,,,,,,,,N,V,extra'):
            raw=PREFIX+nmea(body);self.assertEqual(split_record(raw),[(raw,'NONE')])

    def test_fragment_bound_and_all_chunk_boundaries(self):
        for boundary in range(1,len(FAULT)):
            out=[];s=Stream(out.append);s.feed(FAULT[:boundary],1,CLOCK);s.feed(FAULT[boundary:],2,CLOCK);s.finish()
            self.assertEqual(b''.join(bytes.fromhex(r['raw_hex']) for r in out),FAULT);self.assertEqual(len(out),2)
            for r in out:
                self.assertEqual(r['chunk_first'],1 if r['byte_begin']<boundary else 2)
                self.assertEqual(r['chunk_last'],1 if r['byte_end']<=boundary else 2)
            self.assertFalse(s.chunk_spans)
        out=[];s=Stream(out.append)
        for i in range(9000):
            s.feed(b'x',i,CLOCK);self.assertLessEqual(len(s.chunk_spans),8192)
        s.finish();self.assertFalse(s.chunk_spans)
        self.assertEqual(sum(len(bytes.fromhex(r['raw_hex'])) for r in out),9000)

    def test_old_agrica_rule_unchanged(self):
        raw=b'#AGRICA,1;GNSS,1,2,'+RMC
        self.assertEqual(split_record(raw),old_split(raw));self.assertEqual(len(split_record(raw)),2)

    def test_no_fix_invalid_mapping_and_md5(self):
        _,_,rows=replay_rows();types=message_types()
        for r in rows:
            self.assertFalse(r['parsed']['utc_valid'] or r['parsed']['position_valid'])
            for i,m in messages(r,123,456):
                self.assertEqual((m._type,m._md5sum),TOPICS[i][1:])
                if i in (1,2):self.assertFalse(m.valid_for_fusion or m.local_measurement_time_valid or m.mapping_version)
                if i==2:self.assertEqual(m.header.stamp.to_nsec(),0);self.assertFalse(m.pvt.valid_fix)
                self.assertNotEqual(i,4)

def writer_replay(out,writer):
    """New test artifacts only; actual recorded byte chunks and receive clocks.
    Uses existing production C++ writer test, not a replacement recorder.
    """
    import rosbag,genpy
    from gnss_recording_check import check_gnss
    from capture_environment import capture_environment
    out=pathlib.Path(out);out.mkdir(exist_ok=False)
    raw=(SESSION/'gnss/serial_raw.bin').read_bytes();summary=json.loads((SESSION/'gnss/summary.json').read_text())
    chunk_rows=list(map(json.loads,(SESSION/'gnss/chunks.jsonl').read_text().splitlines()))
    with rosbag.Bag(str(out/'input_messages.bag'),'w') as bag:
        clock=[None]
        def publish(i,m):
            ns=clock[0]['realtime_ns'];bag.write(TOPICS[i][0],m,genpy.Time(ns//10**9,ns%10**9))
        e=Evidence(out/'gnss',summary['session_id'],summary['writer_epoch'],publish)
        for c in chunk_rows:
            clock[0]=c['receive_clocks'];e.feed(raw[c['byte_offset']:c['byte_offset']+c['byte_count']],clock[0],c['read_before_monotonic_ns'])
        e.close('OFFLINE_REPLAY_END')
    result=e.summary();result.update(status='RAW_RECEPTION_RECORDED',hardware_run=False,source_session=str(SESSION),receive_clocks_origin='REAL_RECORDED_REPLAY_NOT_NEW_MEASUREMENTS')
    (out/'gnss/summary.json').write_text(json.dumps(result,indent=2)+'\n')
    assert (out/'gnss/serial_raw.bin').read_bytes()==raw
    assert list(map(json.loads,(out/'gnss/chunks.jsonl').read_text().splitlines()))==chunk_rows
    subprocess.run([str(writer),str(out/'input_messages.bag'),str(out/'writer')],check=True,env=capture_environment())
    shutil.copytree(out/'gnss',out/'writer/gnss');shutil.copy2(out/'writer/writer_counts.json',out/'writer/gnss_writer_summary.json')
    verified=check_gnss(out/'writer');assert not verified['errors'],verified
    assert verified['counts']['/gnss/raw']==1142 and verified['counts']['/gnss/status_v2']==1142
    assert verified['counts']['/gnss/pvt_local']==489 and verified['counts']['/ublox_driver/receiver_pvt']==489
    assert verified['utc_valid_records']==0
    (out/'replay_result.json').write_text(json.dumps(verified,indent=2)+'\n')
    print(json.dumps(verified,indent=2))

if __name__=='__main__':
    if len(sys.argv)==4 and sys.argv[1]=='--writer-replay':writer_replay(sys.argv[2],sys.argv[3])
    else:unittest.main(verbosity=2)
