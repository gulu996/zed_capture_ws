"""Bounded decode/metadata audit of C5F files. No rewriting or timestamp mapping."""
import csv,hashlib,json,pathlib,statistics,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'diagnostics/zed_jpeg_benchmark'))
from codec import sof
import cv2,numpy as np
cv2.setNumThreads(1)
def file_audit(session):
    session=pathlib.Path(session);errors=[];keys={'left':[],'right':[]};rows=[];verified=[]
    try:
        with (session/'frames.csv').open() as f:rows=list(csv.DictReader(f))
        with (session/'video_timestamps.csv').open() as f:video=list(csv.DictReader(f))
        meta={int(r['pair_id']):r for r in video};seen=set()
        for r in rows:
            pair=int(r['pair_id']);m=meta.get(pair)
            if pair in seen:raise ValueError('duplicate pair_id')
            seen.add(pair)
            if not m:raise ValueError('index pair absent in raw video sidecar')
            if any(r[k]!=m[k] for k in ['raw_ns','sequence','flags','timestamp_type','timestamp_source']):raise ValueError('index raw metadata mismatch')
            if int(r['raw_ns'])!=int(r['v4l2_sec'])*10**9+int(r['v4l2_usec'])*1000:raise ValueError('raw integer timestamp mismatch')
            if r['clock_domain']!='CLOCK_MONOTONIC' or int(r['timestamp_type'])!=8192:raise ValueError('unverified timestamp domain')
            if (int(r['width']),int(r['height']),int(r['quality']),r['subsampling'])!=(1280,720,95,'420'):raise ValueError('mode mismatch')
            if r.get('encoding_status')!='ENCODED_420' or r.get('write_status')!=r['status']:errors.append('encoding/write status mismatch for '+str(pair))
            if r['status']!='WRITTEN' or r['left_ok']!='1' or r['right_ok']!='1':errors.append('incomplete pair '+str(pair)+': '+r['status']);continue
            item={'pair_id':pair,'raw_ns':int(r['raw_ns'])}
            for eye in ['left','right']:
                expected=f'camera/{eye}/{(pair-1)//1000:06d}/{pair:012d}.jpg'
                if r[eye+'_path']!=expected:raise ValueError('unsafe/unexpected image path')
                p=(session/expected).resolve()
                if session.resolve() not in p.parents:raise ValueError('path escapes session')
                data=p.read_bytes()
                if len(data)!=int(r[eye+'_bytes']) or not data.endswith(b'\xff\xd9'):raise ValueError('truncated JPEG '+str(pair))
                info=sof(data)
                if not info['is_420'] or (info['width'],info['height'])!=(1280,720):raise ValueError('JPEG SOF mismatch')
                image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
                if image is None or image.shape!=(720,1280,3):raise ValueError('JPEG decode failed')
                seq=int(r[eye+'_seq']);ns=int(r[eye+'_sec'])*10**9+int(r[eye+'_nsec'])
                if seq!=int(r['sequence']) or ns!=int(r['raw_ns']):raise ValueError('Header changed')
                if not r[eye+'_frame_id']:raise ValueError('missing frame_id')
                item[eye+'_sha256']=hashlib.sha256(data).hexdigest();keys[eye].append((seq,ns))
            verified.append(item)
        expected_paths={r[eye+'_path'] for r in rows for eye in ['left','right'] if r[eye+'_path']}
        observed_paths={str(p.relative_to(session)) for p in (session/'camera').rglob('*.jpg')}
        if expected_paths!=observed_paths:errors.append('index/file path set differs (partial/orphan files retained)')
        if seen!=set(meta):errors.append('frames index/video pair set differs')
        s=json.loads((session/'jpeg_files_summary.json').read_text())
        if s['failed'] or not s['final_synced'] or not s['workers_joined']:errors.append('JPEG pipeline failed or not durably finalized')
        if s['inputs']!=len(rows) or s['completed']!=len(verified):errors.append('JPEG summary count mismatch')
    except Exception as e:errors.append(str(e))
    return {'status':'PASS' if not errors and rows else 'FAIL','errors':errors,'keys':keys,'frames':rows,'verified':verified,'note':'WRITTEN means both files closed; durable acceptance additionally requires final_synced; power loss can lose unsynced batch.'}
def application_status(check,cfg):
    """Independently report eligibility; NEVER imply mapped/physical-synced PASS."""
    reasons=[];f=check.get('jpeg_files',{});streams=check.get('streams',{})
    if f.get('status')!='PASS':reasons.append('JPEG files/metadata/durability failed')
    for topic in ['/livox/lidar','/livox/imu']:
        s=streams.get(topic,{})
        if s.get('count',0)<2 or any(s.get(k,0) for k in ['backwards','duplicates','long_intervals']):reasons.append('required MID continuity: '+topic)
        if (s.get('fps') or 0)<(8 if topic.endswith('lidar') else 100):reasons.append('required MID rate: '+topic)
    for k in ['cloud_structure_errors','cloud_empty_messages','cloud_sequence_discontinuities']:
        if check.get(k):reasons.append(k)
    if check.get('mid_clock_types')!=['2'] or check.get('mid_clock_switch_counts')!=['0']:reasons.append('MID clock source not confirmed GPS/type2 without switch')
    if not check.get('bag_readable_all_records') or not check.get('stereo_sequence_and_stamps_equal'):reasons.append('bag/pairing invalid')
    v=streams.get('/zed2i/left/image_raw',{});policy=cfg['slam_image_gap_policy']
    frames=sorted(f.get('frames',[]),key=lambda x:int(x['pair_id']));ts=[int(x['raw_ns']) for x in frames];d=[b-a for a,b in zip(ts,ts[1:])];period=statistics.median(d) if d else 0
    missing=sum(max(0,round(x/period)-1) for x in d) if period>0 else 0;ratio=missing/(len(ts)+missing) if ts else 1
    seq=[int(x['sequence']) for x in frames]
    if any(((b-a)&0xffffffff)==0 or ((b-a)&0xffffffff)>=0x80000000 for a,b in zip(seq,seq[1:])):reasons.append('driver sequence duplicate/reset')
    if not d or min(d)<=0:reasons.append('invalid/nonmonotonic image time')
    if v.get('long_intervals',0)>policy['max_events'] or ratio>policy['max_missing_period_ratio'] or v.get('max_interval_ms',float('inf'))>policy['max_interval_ms']:reasons.append('source image gaps exceed explicit application policy')
    required_seconds=check.get('duration_requested_s',300)*.9 if cfg.get('long_recording',False) else 27
    if v.get('duration_s',0)<required_seconds:reasons.append('short C5F capture')
    if any('raw sidecar' in e or 'timestamp sidecar missing' in e or 'anchor history mismatch' in e or 'no anchor state' in e or 'missing required topic' in e for e in check.get('errors',[])):reasons.append('missing required raw evidence')
    if any('capture summary:' in e or 'low-level diagnostics:' in e for e in check.get('errors',[]) if 'video_sequence_gaps' not in e):reasons.append('capture/runtime/IO failure')
    return {'status':'FAIL' if reasons else 'PENDING_L2B_AND_PHYSICAL_SYNC','required_sensor_recording':'FAIL' if reasons else 'PASS_WITH_RECORDED_GAPS' if v.get('long_intervals') else 'PASS','reasons':reasons,'image_gap_policy':policy,'cadence_missing_periods_estimate':missing,'missing_period_ratio':ratio,'warning':'cadence estimate is not physical exposure loss count; driver sequence missing is separate','L2B_MAPPING':'PENDING','PHYSICAL_SYNC':'PENDING'}
