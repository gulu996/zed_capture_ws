"""C5F offline interface, not a clock mapper or production SLAM bag converter."""
import csv,hashlib,pathlib
import cv2,numpy as np
from sensor_msgs.msg import Image
cv2.setNumThreads(1)
def decode_original(session,row,eye):
    """Diagnostic image only: original MONOTONIC Header, NOT a MID-clock SLAM input."""
    if row['status']!='WRITTEN' or row['left_ok']!='1' or row['right_ok']!='1':raise ValueError('INCOMPLETE_STEREO_PAIR')
    root=pathlib.Path(session).resolve();p=(root/row[eye+'_path']).resolve()
    if root not in p.parents:raise ValueError('unsafe path')
    data=p.read_bytes();bgr=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
    if bgr is None or bgr.shape!=(720,1280,3):raise ValueError('bad JPEG')
    m=Image();m.header.seq=int(row[eye+'_seq']);m.header.stamp.secs=int(row[eye+'_sec']);m.header.stamp.nsecs=int(row[eye+'_nsec']);m.header.frame_id=row[eye+'_frame_id'];m.width=1280;m.height=720;m.encoding='bgr8';m.step=3840;m.data=bgr.tobytes();return m

def conversion_plan(session,mapping=None):
    """Future L2-B adapter must provide audited map bound to exact input digests.
    This only plans acceptance; it NEVER generates a sensor-clock stamp itself.
    """
    root=pathlib.Path(session)
    with (root/'frames.csv').open() as f:rows=list(csv.DictReader(f))
    accepted=[];rejected=[]
    bound=bool(mapping and mapping.get('validation_status')=='VALIDATED' and mapping.get('target_clock')=='MID360_DEVICE_GPS' and mapping.get('frames_sha256')==hashlib.sha256((root/'frames.csv').read_bytes()).hexdigest() and mapping.get('anchors_sha256')==hashlib.sha256((root/'anchors.jsonl').read_bytes()).hexdigest() and mapping.get('model_report_sha256'))
    previous=0
    for r in sorted(rows,key=lambda x:int(x['pair_id'])):
        pair=int(r['pair_id']);entry=mapping.get('pairs',{}).get(str(pair)) if bound else None;reason=None
        if r['status']!='WRITTEN' or r['left_ok']!='1' or r['right_ok']!='1':reason='INCOMPLETE_PAIR'
        elif not entry or entry.get('status')!='VALID':reason='L2B_MAPPING_UNVALIDATED_OR_REJECTED'
        elif entry.get('raw_ns')!=int(r['raw_ns']) or entry.get('sequence')!=int(r['sequence']):reason='MAP_INPUT_MISMATCH'
        elif type(entry.get('mapped_mid_ns')) is not int or entry['mapped_mid_ns']<=previous:reason='INVALID_MAPPED_TIME'
        if reason:rejected.append({'pair_id':pair,'raw_ns':int(r['raw_ns']),'reason':reason});continue
        previous=entry['mapped_mid_ns'];accepted.append({'pair_id':pair,'raw_ns':int(r['raw_ns']),'mapped_mid_ns':previous,'original_headers':{k:v for k,v in r.items() if k.endswith(('_seq','_sec','_nsec','_frame_id'))}})
    return {'status':'PENDING_L2B' if not bound else 'PLANNED_ONLY','accepted':accepted,'rejected':rejected,'bag_written':False,'note':'Future export uses mapped Image Header.stamp and retains original Header in immutable metadata; MID messages untouched. Raw MONOTONIC decode is never published as unified-clock data.'}
