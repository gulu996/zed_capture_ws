"""Bounded stream envelope around the unchanged, hash-pinned R1 parser.
No serial/ROS master is opened by this module. Receive clocks are NOT epochs.
"""
import collections, hashlib, json, math, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parent
VENDOR=ROOT/'vendor/r1'
for name,expected in json.loads((VENDOR/'source_hashes.json').read_text()).items():
    if hashlib.sha256((VENDOR/name).read_bytes()).hexdigest()!=expected:
        raise RuntimeError('R1 source hash mismatch: '+name)
sys.path.insert(0,str(VENDOR))
from gnss_r1_compat import Adapter
from gnss_r21_compat import split_record
TOPICS=(('/gnss/raw','sensor_time_msgs/RawSerialFrame','b3f0843fc91b42663f3ec3c977e3095b'),
        ('/gnss/status_v2','gnss_serial_driver/GnssStatus','89bd2929a7a8274c1f46b1f399c930ec'),
        ('/gnss/pvt_local','gnss_serial_driver/GnssPvtStamped','bdfb1e39cf636dda7ac090d7feb65573'),
        ('/ublox_driver/receiver_pvt','gnss_comm/GnssPVTSolnMsg','d18171357d7a159f76d4d7c0b12fb631'),
        ('/sensor_time/utc_observation','sensor_time_msgs/UtcObservation','55266fcd72cb453b63ebcad49e53171a'))
PORT='/dev/serial/by-id/usb-STMicroelectronics_STM32_Virtual_ComPort_5CF253593333-if00'
def clean(x):
    if isinstance(x,float) and not math.isfinite(x):return None
    if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    return x
def emit(f,x):f.write(json.dumps(clean(x),ensure_ascii=True,allow_nan=False,separators=(',',':'))+'\n')
def bump(counter,key):
    # Bound diagnostic category cardinality even for arbitrary corrupt input.
    counter[key if key in counter or len(counter)<64 else 'OTHER_CATEGORY_LIMIT']+=1
def message_types():
    from sensor_time_msgs.msg import RawSerialFrame,UtcObservation
    from gnss_serial_driver.msg import GnssStatus,GnssPvtStamped
    from gnss_comm.msg import GnssPVTSolnMsg
    types=(RawSerialFrame,GnssStatus,GnssPvtStamped,GnssPVTSolnMsg,UtcObservation)
    for t,(_,dtype,md5) in zip(types,TOPICS):
        if (t._type,t._md5sum)!=(dtype,md5):raise RuntimeError('GNSS message whitelist mismatch '+dtype)
    return types

def messages(record,session_id,writer_epoch,device=PORT):
    """Legacy MD5s, conservative unknown fields, no invented local measurement stamp."""
    import genpy
    raw_t,status_t,pvt_t,compat_t,utc_t=message_types()
    parsed=record['parsed']; seq=record['source_sequence'];clock=record['receive_clocks']
    real=int(clock['realtime_ns']); host=genpy.Time(real//10**9,real%10**9)
    detail=json.dumps(clean(dict(protocol=parsed['source'],raw_quality=parsed['raw_quality'],
        checksum=parsed['checksum_reason'],utc_valid=parsed['utc_valid'],time_reason=parsed['time_reason'],
        measurement_to_mid_mapping='PENDING',uncertainty_ns=None,
        header_clock='HOST_REALTIME_RECEPTION_NOT_MEASUREMENT',record_sequence=record['record_sequence'],
        unknown_navigation_fields='NaN; legacy GNSS time unknown unless validated AGRICA week/TOW')))
    def header(m,measurement=False):
        m.header.seq=seq&0xffffffff;m.header.frame_id='gnss_receiver'
        m.header.stamp=genpy.Time(0,0) if measurement else host
        if hasattr(m,'session_id'):m.session_id=session_id;m.writer_epoch=writer_epoch
        if hasattr(m,'source_sequence'):m.source_sequence=seq
        return m
    raw=header(raw_t());raw.host_receive_stamp=host;raw.host_receive_monotonic_ns=clock['monotonic_ns']
    raw.timestamp_source=raw.INVALID;raw.time_uncertainty_ns=0 # UNKNOWN; host fields observed, local/MID time invalid
    raw.device=device;raw.protocol=parsed['source'];raw.data=bytes.fromhex(record['raw_hex'])
    status=header(status_t());status.serial_open=record.get('serial_open',True)
    status.utc_valid=parsed['utc_valid'];status.position_valid=parsed['position_valid']
    status.solution_quality=parsed['solution_quality'];status.source_message=parsed['source'];status.detail=detail
    status.checksum_error_count=record['checksum_error_count'];status.parse_error_count=record['parse_error_count']
    # mapping_version, local_measurement_time_valid, valid_for_fusion stay 0/false.
    out=[(0,raw),(1,status)]
    if parsed['pvt'] is not None:
        p=compat_t();p.time.week=0;p.time.tow=float('nan')
        for key in p.__slots__:
            if key=='time':continue
            if key in parsed['pvt']:setattr(p,key,parsed['pvt'][key])
        # R1/legacy defaults are not evidence of zero velocity or accuracy.
        for key in ('h_acc','v_acc','p_dop','vel_acc'):setattr(p,key,float('nan'))
        # Navigation velocity semantics are outside R1's CRC/time/quality validation.
        p.vel_n=p.vel_e=p.vel_d=float('nan')
        # R1 preserves raw heights but legacy GGA defaults missing geoid to 0.
        # Do not promote that value (or AGRICA/KSXT raw height) to ellipsoid height.
        p.altitude=float('nan')
        if parsed['source'] not in ('GGA','KSXT'):p.height_msl=float('nan')
        fields=parsed['time_fields']
        if parsed['source']=='AGRICA' and parsed['utc_valid']:
            p.time.week=int(fields['week']);p.time.tow=int(fields['tow_ms'])/1000.0
        stamped=header(pvt_t(),measurement=True);stamped.pvt=p
        stamped.utc_measurement_ns=parsed['utc_measurement_ns'];stamped.utc_valid=parsed['utc_valid']
        # Zero header/local time means INVALID here; never serial arrival projected as epoch.
        out.extend(((2,stamped),(3,p)))
    if parsed['utc_valid']:
        obs=header(utc_t());obs.utc_stamp_ns=parsed['utc_measurement_ns']
        obs.association_type=obs.HOST_SERIAL_ASSOCIATED;obs.valid=False;obs.detail=detail
        out.append((4,obs))
    return out

class Stream:
    """8192-byte framing bound; every byte is accounted, even oversized/partial input.
    CRLF is preserved across read boundaries. source_sequence identifies a physical
    line/fragment; record_sequence distinguishes recovered AGRICA/RMC partitions.
    """
    def __init__(self,callback,limit=8192):
        self.callback=callback;self.limit=limit;self.buf=bytearray();self.offset=0;self.begin=0
        self.first_chunk=None;self.last_chunk=None;self.clock=None;self.last_clock=None
        # At most limit spans (one per byte in the worst case); cleared per line.
        self.chunk_spans=[]
        self.source_sequence=0;self.record_sequence=0;self.adapter=Adapter()
        self.counts=collections.Counter();self.protocols=collections.Counter();self.quality=collections.Counter();self.utc={};self.parse_reasons=collections.Counter();self.time_reasons=collections.Counter()
    def feed(self,data,chunk_id,clock):
        for value in data:
            if self.buf and self.buf[-1]==13 and value!=10:self._line('NONE')
            if not self.buf:self.begin=self.offset;self.first_chunk=chunk_id
            if not self.chunk_spans or self.chunk_spans[-1][2]!=chunk_id:
                self.chunk_spans.append([self.offset,self.offset,chunk_id,clock])
            self.chunk_spans[-1][1]=self.offset+1
            self.buf.append(value);self.offset+=1;self.last_chunk=chunk_id;self.clock=clock
            if value==10:self._line('NONE')
            elif len(self.buf)>=self.limit:self._line('OVERSIZE_FRAGMENT')
    def _line(self,reason):
        if not self.buf:return
        self.source_sequence+=1;begin=self.begin
        parts=split_record(bytes(self.buf)) if reason=='NONE' else [(bytes(self.buf),reason)]
        spans=self.chunk_spans;self.chunk_spans=[]
        parent_end=self.begin+len(self.buf)
        self.buf.clear() # Do not retry/duplicate a record if a downstream sink throws.
        for raw,recovery in parts:
            self.record_sequence+=1;parsed=self.adapter.parse(raw)
            # Oversize/unfinished fragments remain raw evidence, never promoted to PVT.
            if reason!='NONE':
                parsed.update(utc_valid=False,utc_measurement_ns=0,position_valid=False,pvt=None,
                              time_reason=reason,solution_quality=0)
            self.counts['records']+=1;self.counts['checksum_errors']+=not parsed['checksum_valid']
            self.counts['parse_errors']+=parsed.get('parse_reason') in ('field_count_or_value','UNSUPPORTED_FORMAT_PRESERVED') or parsed['source']=='UNCLASSIFIED'
            bump(self.parse_reasons,parsed.get('parse_reason','UNKNOWN'));bump(self.time_reasons,parsed['time_reason'])
            self.counts['checksum_valid_records']+=parsed['checksum_valid']
            self.counts['position_valid_records']+=parsed['position_valid']
            bump(self.protocols,parsed['source']);bump(self.quality,parsed['source']+':'+str(parsed['raw_quality']))
            delta=None
            if parsed['utc_valid']:
                self.counts['utc_valid']+=1;prior=self.utc.get(parsed['source'])
                if prior is not None:
                    delta=parsed['utc_measurement_ns']-prior
                    self.counts['utc_backwards']+=delta<0;self.counts['utc_duplicates']+=delta==0
                self.utc[parsed['source']]=parsed['utc_measurement_ns']
            row=dict(source_sequence=self.source_sequence,record_sequence=self.record_sequence,
                byte_begin=begin,byte_end=begin+len(raw),raw_hex=raw.hex(),
                chunk_first=self.first_chunk,chunk_last=self.last_chunk,receive_clocks=self.clock,
                recovery_reason=recovery,parsed=parsed,utc_delta_ns=delta,
                checksum_error_count=self.counts['checksum_errors'],parse_error_count=self.counts['parse_errors'],
                measurement_to_mid_mapping='PENDING',mapping_version=0,mapping_uncertainty_ns=None,
                local_measurement_time_valid=False,valid_for_fusion=False,
                receive_semantics='clock bracket after os.read; last chunk of record; not PPS or measurement epoch')
            if recovery in ('TRUNCATED_GGA_BEFORE_VALID_RMC','RESYNC_AFTER_TRUNCATED_GGA'):
                overlapping=[x for x in spans if x[0]<row['byte_end'] and x[1]>begin]
                row.update(parent_byte_begin=self.begin,parent_byte_end=parent_end,
                    parent_chunk_first=self.first_chunk,parent_chunk_last=self.last_chunk,
                    parent_receive_clocks=self.clock,chunk_first=overlapping[0][2],
                    chunk_last=overlapping[-1][2],fragment_receive_clocks=overlapping[-1][3],
                    receive_semantics='original parent last-chunk clock preserved; fragment_receive_clocks identifies fragment last chunk; neither is a measurement epoch')
            self.callback(row);begin+=len(raw)
        self.buf.clear();self.begin=self.offset
    def finish(self,reason='END_OF_STREAM'):
        if self.buf:self._line('NONE' if self.buf[-1] in (10,13) else reason)
        self.adapter=Adapter() # Only AFTER residual was recorded.
