import numpy as np
from checker_store import Numbers
def application_status(check,cfg,store):
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
    name=store.name();store.db.execute('CREATE TABLE '+name+' (pair INTEGER, ordinal INTEGER, ns INTEGER, seq INTEGER)')
    count=0
    for r in f.get('frames',[]):
        store.db.execute('INSERT INTO '+name+' VALUES (?,?,?,?)',(int(r['pair_id']),count,int(r['raw_ns']),int(r['sequence'])));count+=1
    d=Numbers();previous=None;seq_bad=False
    for ns,seq in store.db.execute('SELECT ns,seq FROM '+name+' ORDER BY pair,ordinal'):
        if previous:
            d.append(ns-previous[0]);delta=(seq-previous[1])&0xffffffff;seq_bad|=delta==0 or delta>=0x80000000
        previous=(ns,seq)
    period=float(np.median(d)) if d else 0
    missing=sum(max(0,round(x/period)-1) for x in d) if period>0 else 0;ratio=missing/(count+missing) if count else 1
    if seq_bad:reasons.append('driver sequence duplicate/reset')
    if not d or min(d)<=0:reasons.append('invalid/nonmonotonic image time')
    if v.get('long_intervals',0)>policy['max_events'] or ratio>policy['max_missing_period_ratio'] or v.get('max_interval_ms',float('inf'))>policy['max_interval_ms']:reasons.append('source image gaps exceed explicit application policy')
    required_seconds=check.get('duration_requested_s',300)*.9 if cfg.get('long_recording',False) else 27
    if v.get('duration_s',0)<required_seconds:reasons.append('short C5F capture')
    if any('raw sidecar' in e or 'timestamp sidecar missing' in e or 'anchor history mismatch' in e or 'no anchor state' in e or 'missing required topic' in e for e in check.get('errors',[])):reasons.append('missing required raw evidence')
    if any('capture summary:' in e or 'low-level diagnostics:' in e for e in check.get('errors',[]) if 'video_sequence_gaps' not in e):reasons.append('capture/runtime/IO failure')
    return {'status':'FAIL' if reasons else 'PENDING_L2B_AND_PHYSICAL_SYNC','required_sensor_recording':'FAIL' if reasons else 'PASS_WITH_RECORDED_GAPS' if v.get('long_intervals') else 'PASS','reasons':reasons,'image_gap_policy':policy,'cadence_missing_periods_estimate':missing,'missing_period_ratio':ratio,'warning':'cadence estimate is not physical exposure loss count; driver sequence missing is separate','L2B_MAPPING':'PENDING','PHYSICAL_SYNC':'PENDING'}
