"""One-pass bag consumer; exact raw evidence, MD5 and invalid-time checks."""
import collections,hashlib,json,pathlib
from checker_streams import json_rows
from gnss_config import modules
class GnssAudit:
 def __init__(self,session):
  self.session=pathlib.Path(session);self.core,_=modules();self.errors=[];self.counts=collections.Counter();self.raw_index=0;self.disabled=False
  self.result=dict(GNSS_RAW_RECEPTION='FAIL',GNSS_PROTOCOL_VALIDITY='PENDING',GNSS_POSITION_QUALITY='UNRESOLVED',GNSS_UTC_VALIDITY='PENDING',GNSS_RECEIVE_CLOCK_VALIDITY='PENDING',GNSS_MEASUREMENT_MAPPING='PENDING',PHYSICAL_SYNC='PENDING',errors=self.errors)
  try:
   folder=self.session/'gnss';self.summary=json.loads((folder/'summary.json').read_text());self.writer=json.loads((self.session/'gnss_writer_summary.json').read_text());self.bytes=0;h=hashlib.sha256()
   with (folder/'serial_raw.bin').open('rb') as f:
    for b in iter(lambda:f.read(1024*1024),b''):self.bytes+=len(b);h.update(b)
   self.sha=h.hexdigest()
   if self.summary['raw_sha256']!=self.sha or self.summary['raw_bytes']!=self.bytes:self.errors.append('raw SHA256/size mismatch')
   offset=0;previous=None
   for c in json_rows(folder/'chunks.jsonl'):
    if c['byte_offset']!=offset:self.errors.append('chunk byte offsets not contiguous')
    offset+=c['byte_count'];clock=c['receive_clocks']
    if clock['raw_after_ns']<clock['raw_before_ns'] or clock['raw_bracket_ns']!=clock['raw_after_ns']-clock['raw_before_ns']:self.errors.append('invalid RAW clock bracket')
    if previous and (clock['monotonic_ns']<previous['monotonic_ns'] or clock['raw_before_ns']<previous['raw_before_ns']):self.errors.append('host receive monotonic clock regression')
    previous=clock
   if offset!=self.bytes:self.errors.append('chunk byte count mismatch')
   self.row_count=0;part_ok=True
   with (folder/'serial_raw.bin').open('rb') as f:
    for r in json_rows(folder/'lines.jsonl'):
     self.row_count+=1;b=bytes.fromhex(r['raw_hex'])
     if f.read(len(b))!=b:part_ok=False
    if f.read(1):part_ok=False
   if not part_ok:self.errors.append('line partitions do not reconstruct raw input')
   if self.summary['status']!='RAW_RECEPTION_RECORDED' or not self.bytes:self.errors.append('raw reader failed or empty')
   if not self.writer['complete']:self.errors.append('GNSS writer accounting incomplete')
   self.rows=iter(json_rows(folder/'lines.jsonl'));self.utcs=(r['parsed']['utc_measurement_ns'] for r in json_rows(folder/'lines.jsonl') if r['parsed']['utc_valid']);self.utc_equal=True
   self.topics={x[0]:i for i,x in enumerate(self.core.TOPICS)}
  except Exception as e:self.errors.append(repr(e));self.disabled=True;self.topics={}
 def consume(self,topic,m):
  if self.disabled or topic not in self.topics:return
  try:
   i=self.topics[topic]
   if (m._type,m._md5sum)!=self.core.TOPICS[i][1:]:self.errors.append(topic+' datatype/MD5 mismatch')
   self.counts[topic]+=1
   if i==0:
    if m.timestamp_source!=m.INVALID:self.errors.append('raw local timestamp source must remain INVALID until mapped')
    row=next(self.rows);self.raw_index+=1
    if bytes(m.data)!=bytes.fromhex(row['raw_hex']) or m.source_sequence!=row['source_sequence']:self.errors.append('raw bag/sidecar bytes or order mismatch')
    if m.host_receive_monotonic_ns!=row['receive_clocks']['monotonic_ns'] or m.host_receive_stamp.to_nsec()!=row['receive_clocks']['realtime_ns']:self.errors.append('raw receive time changed')
   if i in (1,2) and (m.valid_for_fusion or m.local_measurement_time_valid or m.mapping_version):self.errors.append('unverified measurement mapping promoted')
   if i==2 and (m.local_measurement_ns or m.header.stamp.to_nsec()):self.errors.append('PVT local time must be invalid zero')
   if i==4:
    if next(self.utcs,None)!=m.utc_stamp_ns:self.utc_equal=False
    if m.valid or m.local_stamp_ns:self.errors.append('UTC observation incorrectly marked mapped')
  except Exception as e:self.errors.append(repr(e));self.disabled=True
 def finish(self):
  if not self.disabled:
   try:
    if next(self.utcs,None) is not None or not self.utc_equal:self.errors.append('measurement UTC sequence not preserved')
    for topic,_,_ in self.core.TOPICS:
     c=self.writer['topics'][topic];n=self.summary['published'][topic]
     if any(c[k]!=n for k in ('received','enqueued','written')) or self.counts[topic]!=n:self.errors.append(topic+' published/received/enqueued/written/bag count mismatch')
     if any(c[k] for k in ('rejected','serialization_errors','write_errors')):self.errors.append(topic+' recording errors')
    if self.raw_index!=self.row_count:self.errors.append('raw records missing from bag')
    s=self.summary;nvalid=s['counts'].get('utc_valid',0)
    self.result.update(GNSS_RAW_RECEPTION='PASS' if not self.errors else 'FAIL',GNSS_PROTOCOL_VALIDITY='OBSERVED_WITH_INVALID_RAW_RECORDS' if s['counts'].get('checksum_errors') else 'OBSERVED_CHECKSUM_VALID',GNSS_POSITION_QUALITY=s['quality'],GNSS_UTC_VALIDITY='VALID_EPOCHS_RECORDED' if nvalid else 'UNAVAILABLE_RAW_CAPTURE_ALLOWED',GNSS_RECEIVE_CLOCK_VALIDITY='PASS' if not s['host_clock_errors'] else 'FAIL',counts=dict(self.counts),raw_bytes=self.bytes,raw_sha256=self.sha,diagnostic_counts=s['counts'],utc_valid_records=nvalid,mapping_uncertainty_ns=None,note='CRC/NO_FIX/invalid UTC retained; reception is not measurement mapping; clock continuity is not precision validation')
   except Exception as e:self.errors.append(repr(e))
  if self.errors:self.result['GNSS_RAW_RECEPTION']='FAIL'
  for key in ('rows','utcs'):
   g=getattr(self,key,None)
   if g is not None:g.close()
  return self.result
