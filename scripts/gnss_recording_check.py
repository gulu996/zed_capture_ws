"""Optional, strict GNSS recording audit. Never promotes UTC-to-MID mapping."""
import hashlib,json,pathlib,sys,collections
from gnss_config import modules

def check_gnss(session):
    session=pathlib.Path(session);core,_=modules();errors=[];counts=collections.Counter()
    result=dict(GNSS_RAW_RECEPTION='FAIL',GNSS_PROTOCOL_VALIDITY='PENDING',GNSS_POSITION_QUALITY='UNRESOLVED',
        GNSS_UTC_VALIDITY='PENDING',GNSS_RECEIVE_CLOCK_VALIDITY='PENDING',GNSS_MEASUREMENT_MAPPING='PENDING',
        PHYSICAL_SYNC='PENDING',errors=errors)
    try:
        import rosbag
        folder=session/'gnss';summary=json.loads((folder/'summary.json').read_text());writer=json.loads((session/'gnss_writer_summary.json').read_text())
        raw=(folder/'serial_raw.bin').read_bytes();chunks=[json.loads(x) for x in (folder/'chunks.jsonl').read_text().splitlines()]
        rows=[json.loads(x) for x in (folder/'lines.jsonl').read_text().splitlines()]
        if summary['raw_sha256']!=hashlib.sha256(raw).hexdigest() or summary['raw_bytes']!=len(raw):errors.append('raw SHA256/size mismatch')
        offset=0;previous=None
        for c in chunks:
            if c['byte_offset']!=offset:errors.append('chunk byte offsets not contiguous')
            offset+=c['byte_count'];clock=c['receive_clocks']
            if clock['raw_after_ns']<clock['raw_before_ns'] or clock['raw_bracket_ns']!=clock['raw_after_ns']-clock['raw_before_ns']:errors.append('invalid RAW clock bracket')
            if previous and (clock['monotonic_ns']<previous['monotonic_ns'] or clock['raw_before_ns']<previous['raw_before_ns']):errors.append('host receive monotonic clock regression')
            previous=clock
        if offset!=len(raw):errors.append('chunk byte count mismatch')
        if b''.join(bytes.fromhex(r['raw_hex']) for r in rows)!=raw:errors.append('line partitions do not reconstruct raw input')
        if summary['status']!='RAW_RECEPTION_RECORDED' or not raw:errors.append('raw reader failed or empty')
        if not writer['complete']:errors.append('GNSS writer accounting incomplete')
        raw_index=0;observed_utc=[]
        with rosbag.Bag(str(session/'sensors.bag'),'r') as bag:
            for topic,m,t in bag.read_messages(topics=[x[0] for x in core.TOPICS]):
                i=next(i for i,x in enumerate(core.TOPICS) if x[0]==topic)
                if (m._type,m._md5sum)!=core.TOPICS[i][1:]:errors.append(topic+' datatype/MD5 mismatch')
                counts[topic]+=1
                if i==0:
                    if m.timestamp_source!=m.INVALID:errors.append('raw local timestamp source must remain INVALID until mapped')
                    row=rows[raw_index];raw_index+=1
                    if bytes(m.data)!=bytes.fromhex(row['raw_hex']) or m.source_sequence!=row['source_sequence']:errors.append('raw bag/sidecar bytes or order mismatch')
                    if m.host_receive_monotonic_ns!=row['receive_clocks']['monotonic_ns'] or m.host_receive_stamp.to_nsec()!=row['receive_clocks']['realtime_ns']:errors.append('raw receive time changed')
                if i in (1,2) and (m.valid_for_fusion or m.local_measurement_time_valid or m.mapping_version):errors.append('unverified measurement mapping promoted')
                if i==2 and (m.local_measurement_ns or m.header.stamp.to_nsec()):errors.append('PVT local time must be invalid zero')
                if i==4:
                    observed_utc.append(m.utc_stamp_ns)
                    if m.valid or m.local_stamp_ns:errors.append('UTC observation incorrectly marked mapped')
        expected_utc=[r['parsed']['utc_measurement_ns'] for r in rows if r['parsed']['utc_valid']]
        if observed_utc!=expected_utc:errors.append('measurement UTC sequence not preserved')
        for topic,_,_ in core.TOPICS:
            c=writer['topics'][topic];n=summary['published'][topic]
            if any(c[k]!=n for k in ('received','enqueued','written')) or counts[topic]!=n:errors.append(topic+' published/received/enqueued/written/bag count mismatch')
            if any(c[k] for k in ('rejected','serialization_errors','write_errors')):errors.append(topic+' recording errors')
        if raw_index!=len(rows):errors.append('raw records missing from bag')
        quality=summary['quality'];nvalid=summary['counts'].get('utc_valid',0)
        result.update(GNSS_RAW_RECEPTION='PASS' if not errors else 'FAIL',
            GNSS_PROTOCOL_VALIDITY='OBSERVED_WITH_INVALID_RAW_RECORDS' if summary['counts'].get('checksum_errors') else 'OBSERVED_CHECKSUM_VALID',
            GNSS_POSITION_QUALITY=quality,GNSS_UTC_VALIDITY='VALID_EPOCHS_RECORDED' if nvalid else 'UNAVAILABLE_RAW_CAPTURE_ALLOWED',
            GNSS_RECEIVE_CLOCK_VALIDITY='PASS' if not summary['host_clock_errors'] else 'FAIL',
            counts=dict(counts),raw_bytes=len(raw),raw_sha256=hashlib.sha256(raw).hexdigest(),
            diagnostic_counts=summary['counts'],utc_valid_records=nvalid,mapping_uncertainty_ns=None,
            note='CRC/NO_FIX/invalid UTC retained; reception is not measurement mapping; clock continuity is not precision validation')
    except Exception as e:errors.append(repr(e))
    if errors:result['GNSS_RAW_RECEPTION']='FAIL'
    return result
if __name__=='__main__':
    result=check_gnss(sys.argv[1]);print(json.dumps(result,indent=2));raise SystemExit(bool(result['errors']))
