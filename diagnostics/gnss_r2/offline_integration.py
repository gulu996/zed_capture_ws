#!/usr/bin/env python3
"""Real byte subsets through R1, legacy messages and the production writer.
This is OFFLINE: receive clock envelope is SYNTHETIC and no device is opened.
"""
import hashlib,json,pathlib,shutil,subprocess,sys,time,uuid
import genpy,rosbag
from test_gnss_r2 import ROOT,REAL,HISTORY,decode,CLOCK
from gnss_receiver import Evidence
from gnss_r2_core import TOPICS
sys.path.insert(0,str(ROOT.parents[1]/'scripts'))
from gnss_recording_check import check_gnss
from capture_environment import capture_environment

def main():
    out=ROOT/('offline_integration_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir()
    _,rows=decode(HISTORY.read_bytes());selected_indices=set();seen=set();previous_by_source={}
    for idx,r in enumerate(rows):
        p=r['parsed'];key=(p['source'],p['raw_quality'],p['utc_valid'])
        if key not in seen or (r['utc_delta_ns'] is not None and r['utc_delta_ns']<=0):
            selected_indices.add(idx);seen.add(key)
        if r['utc_delta_ns'] is not None and r['utc_delta_ns']<=0:
            selected_indices.add(previous_by_source[p['source']])
        if p['utc_valid']:previous_by_source[p['source']]=idx
    selected=[r for idx,r in enumerate(rows) if idx in selected_indices]
    raw_history_subset=b''.join(bytes.fromhex(r['raw_hex']) for r in selected)
    raw=raw_history_subset+(REAL/'serial_raw.bin').read_bytes()
    provenance=dict(hardware_run=False,receive_clock_origin='SYNTHETIC',
        history_input=str(HISTORY),history_sha256=hashlib.sha256(HISTORY.read_bytes()).hexdigest(),
        selected_history_byte_ranges=[(r['byte_begin'],r['byte_end']) for r in selected],
        real_indoor_input=str(REAL),real_indoor_sha256=hashlib.sha256((REAL/'serial_raw.bin').read_bytes()).hexdigest(),
        combined_raw_sha256=hashlib.sha256(raw).hexdigest(),measurement_time_order='Unsorted, not deduplicated',
        note='Subsets test recording semantics; does not validate live serial/ROS transport/physical sync')
    with rosbag.Bag(str(out/'input_messages.bag'),'w') as b:
        index=[0]
        def publish(i,msg):
            index[0]+=1;b.write(TOPICS[i][0],msg,genpy.Time(1700000000,index[0]*1000))
        e=Evidence(out/'gnss_evidence',123,456,publish)
        for i in range(0,len(raw),4096):
            clock={k:v+i if k!='raw_bracket_ns' else v for k,v in CLOCK.items()}
            e.feed(raw[i:i+4096],clock)
        e.close('END_OF_OFFLINE_FIXTURE')
    summary=e.summary();assert summary['counts']['utc_backwards']>=1 and summary['counts']['utc_duplicates']>=1
    summary.update(status='RAW_RECEPTION_RECORDED',synthetic_receive_clocks=True,hardware_run=False,provenance=provenance)
    (e.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    assert (e.out/'serial_raw.bin').read_bytes()==raw
    writer=ROOT.parents[1]/'devel/lib/zed_capture/capture_gnss_writer_test'
    subprocess.run([str(writer),str(out/'input_messages.bag'),str(out/'output')],check=True,env=capture_environment())
    shutil.copytree(e.out,out/'output/gnss');shutil.copy2(out/'output/writer_counts.json',out/'output/gnss_writer_summary.json')
    result=check_gnss(out/'output');result.update(hardware_run=False,synthetic_receive_clocks=True)
    (out/'gnss_check.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print('OFFLINE_DIR='+str(out));print(json.dumps(result,indent=2));return bool(result['errors'])
if __name__=='__main__':sys.exit(main())
