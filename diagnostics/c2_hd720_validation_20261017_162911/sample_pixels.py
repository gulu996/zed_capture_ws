#!/usr/bin/env python3
"""Read-only bounded inspection of three recorded stereo pairs; no hardware."""
import csv,hashlib,json,pathlib
import cv2,numpy as np,rosbag,genpy
S=pathlib.Path('/home/jetson/zed_capture_data/20261017_162911_883e3a79')
OUT=pathlib.Path(__file__).resolve().parent
rows=list(csv.DictReader((S/'video_timestamps.csv').open()))
selected=[rows[0],rows[len(rows)//2],rows[-1]]
topics=['/zed2i/left/image_raw','/zed2i/right/image_raw','/zed2i/video_stamp']
def stamp(ns):return genpy.Time(ns//10**9,ns%10**9)
results=[];panels=[]
before=(S/'data.bag').stat()
with rosbag.Bag(str(S/'data.bag'),'r') as bag:
 for row in selected:
  seq=int(row['sequence']);rt=int(row['realtime_ns']);found={}
  for topic,msg,t in bag.read_messages(topics=topics,start_time=stamp(rt-1_000_000),end_time=stamp(rt+200_000_000)):
   if msg.header.seq==seq:found[topic]=msg
   if len(found)==3:break
  assert len(found)==3,(seq,list(found))
  meta=found[topics[2]];left,right=found[topics[0]],found[topics[1]]
  assert meta.pair_id==int(row['pair_id']) and left.header.stamp==right.header.stamp==meta.header.stamp
  assert meta.header.stamp.to_nsec()==meta.v4l2_sec*10**9+meta.v4l2_usec*1000==int(row['raw_ns'])
  assert (meta.stereo_width,meta.height,meta.row_stride,meta.bytesused,meta.pixel_format)==(2560,720,5120,3686400,int.from_bytes(b'YUYV','little'))
  result={'pair_id':meta.pair_id,'sequence':seq,'raw_ns':int(row['raw_ns']),'stereo_width':meta.stereo_width,'height':meta.height,'row_stride':meta.row_stride,'bytesused':meta.bytesused,'pixel_format':meta.pixel_format,'eyes':{}}
  previews=[];ys=[]
  for label,msg in [('left',left),('right',right)]:
   assert (msg.width,msg.height,msg.step,msg.encoding,len(msg.data))==(1280,720,2560,'8UC2',1843200)
   raw=np.frombuffer(msg.data,dtype=np.uint8).reshape(720,1280,2);y=raw[:,:,0];ys.append(y)
   result['eyes'][label]={'width':msg.width,'height':msg.height,'step':msg.step,'encoding':msg.encoding,'data_length':len(msg.data),'sha256':hashlib.sha256(msg.data).hexdigest(),'luma_min':int(y.min()),'luma_max':int(y.max()),'luma_mean':float(y.mean()),'luma_std':float(y.std()),'all_luma_zero':bool(np.all(y==0)),'fraction_luma_le_16':float(np.mean(y<=16)),'adjacent_row_identical_fraction':float(np.mean(np.all(y[1:]==y[:-1],axis=1)))}
   bgr=cv2.cvtColor(raw,cv2.COLOR_YUV2BGR_YUY2)
   # Preview-only downscale. Original bag pixels remain untouched.
   preview=cv2.resize(bgr,(512,288),interpolation=cv2.INTER_AREA)
   cv2.putText(preview,'pair %d %s'%(meta.pair_id,label),(8,22),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,0),1)
   previews.append(preview)
  result['left_right_bytes_identical']=left.data==right.data
  result['left_right_luma_mean_abs_difference']=float(np.mean(np.abs(ys[0].astype(np.int16)-ys[1].astype(np.int16))))
  results.append(result);panels.append(np.hstack(previews))
after=(S/'data.bag').stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
with (OUT/'pixel_samples.json').open('x') as f:json.dump({'samples':results,'original_bag_size':after.st_size,'bag_size_mtime_unchanged':True,'scope':'Three stereo pairs only; PNG is a reduced preview, not a dataset transformation or calibration check.'},f,indent=2)
preview_path=OUT/'stereo_preview.png';assert not preview_path.exists();assert cv2.imwrite(str(preview_path),np.vstack(panels))
print(json.dumps(results,indent=2))
