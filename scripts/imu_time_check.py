#!/usr/bin/env python3
"""Offline gyro-norm lag check; not a clock mapper or image synchronization test."""
import argparse,json,pathlib,time
import numpy as np

def compare(zt,zv,lt,lv,window=10.0,max_lag=2.0,rate=200.0,min_motion=.02):
    zt=np.asarray(zt,dtype=np.int64);lt=np.asarray(lt,dtype=np.int64)
    zv=np.asarray(zv,dtype=float);lv=np.asarray(lv,dtype=float)
    if len(zt)<10 or len(lt)<10:raise ValueError('each IMU needs at least 10 samples')
    if np.any(np.diff(zt)<=0) or np.any(np.diff(lt)<=0):raise ValueError('non-increasing IMU timestamps; segment restarts before correlation')
    if not np.isfinite(zv).all() or not np.isfinite(lv).all():raise ValueError('non-finite gyro values')
    if window<=0 or max_lag<=0 or rate<=0:raise ValueError('window, lag and rate must be positive')
    z=(zt-zt[0]).astype(float)*1e-9;l=(lt-lt[0]).astype(float)*1e-9
    zn=np.linalg.norm(zv,axis=1);ln=np.linalg.norm(lv,axis=1)
    zd=float(np.median(np.diff(z)));ld=float(np.median(np.diff(l)))
    hz=min(rate,1/zd,1/ld);step=1/hz
    lags=np.arange(-max_lag,max_lag+step*.5,step);results=[]
    start=max_lag;end=min(z[-1],l[-1]-max_lag)
    while start+window<=end:
        grid=np.arange(start,start+window,step);a=np.interp(grid,z,zn);motion=float(np.std(a));scores=[]
        zg=np.diff(z[(z>=start-step)&(z<=start+window+step)])
        lg=np.diff(l[(l>=start-max_lag-step)&(l<=start+window+max_lag+step)])
        gap=bool((len(zg) and zg.max()>5*zd) or (len(lg) and lg.max()>5*ld))
        for lag in lags:
            b=np.interp(grid+lag,l,ln);bc=b-b.mean();ac=a-a.mean();den=np.linalg.norm(ac)*np.linalg.norm(bc)
            scores.append(float(np.dot(ac,bc)/den) if den>1e-12 else -1.)
        scores=np.array(scores);i=int(np.argmax(scores));best=float(lags[i]);peak=float(scores[i])
        distant=np.abs(lags-best)>max(.1,3*step);runner=float(scores[distant].max()) if distant.any() else peak
        reasons=[]
        if motion<min_motion:reasons.append('insufficient rotational excitation')
        if peak<.7:reasons.append('weak correlation')
        if peak-runner<.03:reasons.append('ambiguous/broad or periodic peak')
        if i in [0,len(lags)-1]:reasons.append('peak at search boundary; expand lag search')
        if gap:reasons.append('sampling gaps in window')
        results.append({'window_z_relative_s':[float(start),float(start+window)],'lag_s_relative_first_samples':best,'offset_zed_to_livox_ns':int(lt[0])-int(zt[0])+round(best*1e9),'correlation':peak,'runner_up_outside_100ms':runner,'peak_margin':peak-runner,'gyro_norm_std_rad_s':motion,'grid_step_s':step,'confidence':'SUPPORTED_BY_MOTION' if not reasons else 'LOW','reasons':reasons})
        start+=window/2
    good=[r['offset_zed_to_livox_ns'] for r in results if r['confidence']=='SUPPORTED_BY_MOTION']
    # Subtract an integer origin before statistics; different device epochs may be very far apart.
    origin=good[0] if good else 0;offset=origin+round(float(np.median([g-origin for g in good]))) if good else None
    return {'status':'ESTIMATE_ONLY' if good else 'PENDING','offset_convention':'t_livox_ns ~= t_zed_raw_ns + offset_zed_to_livox_ns','offset_zed_to_livox_ns':offset,'supported_windows':len(good),'windows':results,'median_absolute_window_deviation_ms':float(np.median([abs(g-offset) for g in good]))/1e6 if good else None,'input_rates_hz':{'zed':1/zd,'livox':1/ld},'resampled_rate_hz':hz,'clock_mapping_implemented':False,'physical_image_sync_verified':False,'limits':'Gyro-norm cross-correlation is a motion-dependent IMU consistency estimate, not image exposure alignment, calibrated latency, or drift correction. Relative-first-sample lag search must cover the acquisition start offset.'}

def read_bag(session):
    import rosbag
    ts={'/zed2i/imu/data_raw':[],'/livox/imu':[]};vs={k:[] for k in ts}
    for path in sorted(pathlib.Path(session).glob('*.bag')):
        with rosbag.Bag(str(path),'r') as bag:
            for topic,m,_ in bag.read_messages(topics=list(ts)):
                ts[topic].append(m.header.stamp.to_nsec());v=m.angular_velocity;vs[topic].append([v.x,v.y,v.z])
    return ts['/zed2i/imu/data_raw'],vs['/zed2i/imu/data_raw'],ts['/livox/imu'],vs['/livox/imu']

def main():
    ap=argparse.ArgumentParser();ap.add_argument('session');ap.add_argument('--window',type=float,default=10);ap.add_argument('--max-lag',type=float,default=2);ap.add_argument('--rate',type=float,default=200);a=ap.parse_args()
    r=compare(*read_bag(a.session),window=a.window,max_lag=a.max_lag,rate=a.rate)
    p=pathlib.Path(a.session)/('imu_time_check_%d.json'%time.time_ns())
    with p.open('x') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2))
if __name__=='__main__':main()
