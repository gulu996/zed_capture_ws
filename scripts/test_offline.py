#!/usr/bin/env python3
"""Synthetic tests only. Output cannot authorize hardware/long-duration PASS."""
import csv,json,pathlib,struct,sys,time
import numpy as np
import rosbag,rospy
from sensor_msgs.msg import Image,Imu
from std_msgs.msg import String
from livox_ros_driver2.msg import CustomMsg,CustomPoint
from zed_capture.msg import VideoStamp,ImuStamp,TimeAnchor
from check_recording import check
from analyze_timestamps import analyze
from imu_time_check import compare
WS=pathlib.Path(__file__).resolve().parents[1]
ROOT=WS/'evidence'/('synthetic_tests_%d'%time.time_ns());ROOT.mkdir()
def stamp(ns):return rospy.Time(ns//10**9,ns%10**9)
def fixture(name,missing_right=False,bad_anchor=False,time_classification=False):
    p=ROOT/name;p.mkdir();(p/'session.json').write_text(json.dumps({'synthetic_fixture':True,'fixture_dimensions':[4,2],'config':{'resolution':'HD1080'}}))
    anchor_raw=struct.pack('<IIQQQQQIIQ',0x31414d49,1,5,2,10000000000,1000000000,1000000001,2,1,10000000)
    a={'reader_monotonic_ns':1000000010,'writer_epoch':5,'write_sequence':2,'imu_stamp_ns':10000000000,'host_monotonic_ns':1000000000,'update_monotonic_ns':1000000001,'clock_source':2,'ready':True,'uncertainty_ns':10000000,'skipped_updates':0,'raw_hex':anchor_raw.hex()}
    if bad_anchor:a['write_sequence']=4
    (p/'anchors.jsonl').write_text(json.dumps(a)+'\n')
    with rosbag.Bag(str(p/'data.bag'),'w') as bag,open(p/'video_timestamps.csv','w') as vf,open(p/'zed_imu_raw.csv','w') as hf:
        vw=csv.writer(vf);hw=csv.writer(hf);vw.writerow('pair_id,sequence,raw_ns,flags,timestamp_type,timestamp_source,dq_before_ns,dq_after_ns,realtime_ns,oc_rebased_ns,bytesused,stride,payload_valid'.split(','));hw.writerow(['sample_id','device_ticks','imu_valid'])
        for i in range(12):
            raw=1000000000+i*33333000;record=stamp(1700000000000000000+i*33333000)
            image=Image();image.header.seq=i;image.header.stamp=stamp(raw);image.width=4;image.height=2;image.encoding='8UC2';image.step=8;image.data=bytes(range(16))
            bag.write('/zed2i/left/image_raw',image,record)
            if not (missing_right and i==4):bag.write('/zed2i/right/image_raw',image,record)
            v=VideoStamp();v.header=image.header;v.v4l2_sequence=i;v.v4l2_sec=raw//10**9;v.v4l2_usec=(raw%10**9)//1000;v.payload_valid=True;v.timestamp_type=0x2000;v.v4l2_flags=0x2000;v.pair_id=i
            bag.write('/zed2i/video_stamp',v,record);vw.writerow([i,i,raw,0x2000,0x2000,0,raw+500000,raw+1000000,record.to_nsec(),0,32,16,1])
            for topic in ['/zed2i/imu/data_raw','/livox/imu']:
                imu=Imu();imu.header.seq=i;imu.header.stamp=stamp(2000000000+i*5000000);imu.angular_velocity.x=i*.01;bag.write(topic,imu,record)
            m=ImuStamp();m.sample_id=i;m.device_ticks=i;bag.write('/zed2i/imu_stamp',m,record);hw.writerow([i,i,1])
            if time_classification:
                d={'sample_id':i,'segment_id':1,'decision_sample_id':max(i,7),'time_validity':'VALID_CONTIGUOUS','reason':'SYNTHETIC_CONTINUITY'}
                bag.write('/zed2i/imu/time_validity',String(data=json.dumps(d)),record)
            c=CustomMsg();c.header.seq=i;c.timebase=3000000000+i*100000000;c.header.stamp=stamp(c.timebase);c.point_num=1;c.points=[CustomPoint()];bag.write('/livox/lidar',c,record)
        msg=TimeAnchor();msg.writer_epoch=5;msg.write_sequence=2;msg.raw_state=anchor_raw;bag.write('/zed2i/time_anchor',msg,record)
        bag.write('/zed2i/diagnostics',String(data='{"sync_status":"SYNC_PENDING"}'),record)
    (p/'capture_summary.json').write_text(json.dumps({'pairs_written':12,'failed':False,'bag_finalized':True}))
    if time_classification:
        with (p/'zed_imu_time_validity.csv').open('x') as f:
            w=csv.writer(f);w.writerow(['sample_id','segment_id','decision_sample_id','time_validity','reason'])
            for i in range(12):w.writerow([i,1,max(i,7),'VALID_CONTIGUOUS','SYNTHETIC_CONTINUITY'])
    return p
results=[]
def passed(name,detail):results.append({'test':name,'status':'PASS','detail':detail})
p=fixture('complete_synthetic');good=check(p);assert good['capture_integrity']=='PASS',good
assert good['synthetic_fixture'] and good['physical_sync_verified'] is False
(p/'check_result.json').write_text(json.dumps(good,indent=2));passed('complete synthetic bag deserialization and stereo matching',good['counts'])
bad=check(fixture('missing_right',missing_right=True));assert bad['capture_integrity']=='FAIL' and not bad['stereo_sequence_and_stamps_equal'];passed('missing right frame rejected',bad['errors'])
pbad=fixture('anchor_mismatch',bad_anchor=True);bad=check(pbad);assert bad['capture_integrity']=='FAIL';assert analyze(pbad)['anchor_protocol_or_sidecar_errors']==1;passed('anchor sidecar mismatch rejected',bad['errors'])
seg=fixture('imu_segment_metadata',time_classification=True);verified=check(seg);assert verified['capture_integrity']=='PASS' and verified['zed_imu_time_classification']['bag_sidecar_equal'];passed('IMU raw/bag/sidecar classification linkage',verified['zed_imu_time_classification'])
segfile=seg/'zed_imu_time_validity.csv';segfile.write_text('\n'.join(segfile.read_text().splitlines()[:-1])+'\n');rejected=check(seg);assert rejected['capture_integrity']=='FAIL' and not rejected['zed_imu_time_classification']['all_raw_reports_classified_once'];passed('missing IMU classification rejected',rejected['zed_imu_time_classification'])
audit=analyze(p);assert audit['anchor_protocol_or_sidecar_errors']==0 and audit['mapping_implemented'] is False;passed('raw timestamp audit without mapping',audit['video_timestamp_types'])
# Nonperiodic motion sampled at 200 and 400 Hz, unequal start times and far-separated epochs.
rng=np.random.RandomState(22);base=np.arange(0,40,.02);motion=rng.uniform(.3,2,len(base))
def signal(t):return np.interp(t,base,motion)
lphys=np.arange(0,36,1/200);zphys=np.arange(.237,36,1/400)
zt=7000000000000+np.round(zphys*1e9).astype(np.int64);lt=1700000000000000000+np.round(lphys*1e9).astype(np.int64)
zv=np.column_stack([signal(zphys),np.zeros(len(zphys)),np.zeros(len(zphys))]);lv=np.column_stack([signal(lphys),np.zeros(len(lphys)),np.zeros(len(lphys))])
r=compare(zt,zv,lt,lv,window=6,max_lag=.6);expected=1700000000000000000-7000000000000
assert r['supported_windows']>=4,r
assert abs(r['offset_zed_to_livox_ns']-expected)<=5000000,r
passed('IMU unequal rates multiwindow known lag',{'estimated_offset_ns':r['offset_zed_to_livox_ns'],'expected_offset_ns':expected,'supported_windows':r['supported_windows']})
low=compare(zt,np.ones_like(zv),lt,np.ones_like(lv),window=6,max_lag=.6);assert low['status']=='PENDING' and low['offset_zed_to_livox_ns'] is None;passed('stationary IMU cannot claim alignment',low['status'])
try:compare(np.array([0]*20),np.ones((20,3)),lt,lv)
except ValueError:passed('timestamp reset/duplicate requires segmentation','rejected')
else:raise AssertionError('duplicate clock accepted')
(ROOT/'results.json').write_text(json.dumps({'status':'SOFTWARE_TESTED','synthetic_only':True,'tests':results},indent=2))
print(json.dumps({'output':str(ROOT),'tests':results},indent=2))
