#!/usr/bin/env python3
"""C3 bounded offline benchmark. Never opens sensors or creates a derived bag."""
import argparse,collections,copy,csv,datetime,hashlib,io,json,math,os,pathlib,queue,signal,struct,sys,threading,time,uuid
import cv2,numpy as np,psutil,rosbag
from sensor_msgs.msg import Image
from codec import Encoder,sof,convert,selftest,LIB
from monitor import Monitor
ROOT=pathlib.Path(__file__).resolve().parent
SESSION=pathlib.Path('/home/jetson/zed_capture_data/20261017_162911_883e3a79')
LEFT='/zed2i/left/image_raw';RIGHT='/zed2i/right/image_raw'
STOP=threading.Event()
def save(p,d):
    with p.open('x') as f:json.dump(d,f,indent=2,allow_nan=False)
def csvout(p,rows):
    with p.open('x',newline='') as f:
        if rows:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def desc(values):
    v=np.asarray(values,dtype=float)
    return {k:float(np.percentile(v,q)) for k,q in [('p50',50),('p95',95),('p99',99),('max',100)]} if len(v) else {}
def header(h):return {'seq':int(h.seq),'stamp_sec':int(h.stamp.secs),'stamp_nsec':int(h.stamp.nsecs),'stamp_ns':int(h.stamp.to_nsec()),'frame_id':h.frame_id}

def load_samples(out,monitor):
    monitor.phase='input_scan_excluded_from_encoding'
    with (SESSION/'video_timestamps.csv').open() as f:video=list(csv.DictReader(f))
    # Equal original-time strata, not repeated copies of a single scene/frame.
    times=np.array([int(r['raw_ns']) for r in video],dtype=np.int64)
    targets=[times[0]+(times[-1]-times[0])*i//47 for i in range(48)]
    indices=[min(range(len(times)),key=lambda k:abs(int(times[k])-t)) for t in targets]
    selected={int(video[i]['sequence']):video[i] for i in indices};assert len(selected)==48
    pairs={seq:{'video':row,'images':{}} for seq,row in selected.items()}
    counts=collections.Counter();sizes=collections.Counter();image_headers=0;first_record=last_record=None
    begin=time.perf_counter();n=0
    with rosbag.Bag(str(SESSION/'data.bag'),'r') as bag:
        for topic,raw,t in bag.read_messages(raw=True):
            datatype,data,md5,pos,cls=raw;counts[topic]+=1;sizes[topic]+=len(data);n+=1
            if first_record is None:first_record=t.to_nsec()
            last_record=t.to_nsec()
            if topic in [LEFT,RIGHT]:
                image_headers+=len(data)-1843200
                seq=struct.unpack_from('<I',data,0)[0]
                if seq in selected:
                    msg=cls();msg.deserialize(data)
                    assert (msg.width,msg.height,msg.step,msg.encoding,len(msg.data))==(1280,720,2560,'8UC2',1843200)
                    assert msg.header.stamp.to_nsec()==int(selected[seq]['raw_ns'])
                    pairs[seq]['images']['left' if topic==LEFT else 'right']=msg
            if n%1000==0:monitor.guard()
            if STOP.is_set():raise RuntimeError('Interrupted during input scan')
    samples=[];metas=[]
    for seq,p in sorted(pairs.items()):
        assert set(p['images'])=={'left','right'}
        l,r=p['images']['left'],p['images']['right'];assert l.header.stamp==r.header.stamp and l.header.seq==r.header.seq
        item={'pair_id':int(p['video']['pair_id']),'sequence':seq,'raw_ns':int(p['video']['raw_ns']),'video_raw_fields':p['video'],'eyes':{}}
        for eye,msg in p['images'].items():
            raw=np.frombuffer(msg.data,np.uint8).reshape(720,1280,2);y=raw[:,:,0];small=y[::4,::4].astype(np.float32)
            item['eyes'][eye]={'header':header(msg.header),'width':1280,'height':720,'encoding':'8UC2','step':2560,'bytes':len(msg.data),'sha256':hashlib.sha256(msg.data).hexdigest(),
                'dark_fraction_y_le32':float(np.mean(y<=32)),'highlight_fraction_y_ge220':float(np.mean(y>=220)),'luma_p05':float(np.percentile(y,5)),'luma_p95':float(np.percentile(y,95)),
                'gradient_mean_subsample4':float(np.mean(np.abs(np.diff(small,axis=0))))}
        samples.append(p);metas.append(item)
    stats={'input_scan_s':time.perf_counter()-begin,'counts':dict(counts),'serialized_bytes':dict(sizes),'serialized_total':sum(sizes.values()),'container_bytes':(SESSION/'data.bag').stat().st_size-sum(sizes.values()),'image_message_overhead_bytes':image_headers,'bag_bytes':(SESSION/'data.bag').stat().st_size,'record_span_s':(last_record-first_record)/1e9,'session_projection_basis_s':30,'sample_pairs':48,'resident_raw_pixel_bytes':48*2*1843200,'selection':'48 equally spaced original-time strata, inclusive endpoints; content coverage features recorded for every eye'}
    save(out/'sample_metadata.json',metas);save(out/'bag_accounting.json',stats)
    return samples,metas,stats

def pair(encoder,sample,q):
    start=time.perf_counter_ns();convert_ns=code_ns=copy_ns=0;encoded=[];individual={}
    for eye in ['left','right']:
        a=time.perf_counter_ns();bgr=convert(sample['images'][eye].data);b=time.perf_counter_ns()
        data,c,d=encoder.encode(bgr,q);convert_ns+=b-a;code_ns+=c;copy_ns+=d;encoded.append(data)
        individual.update({eye+'_convert_ms':(b-a)/1e6,eye+'_encode_ms':c/1e6,eye+'_copy_free_ms':d/1e6})
    end=time.perf_counter_ns()
    return dict(convert_pair_ms=convert_ns/1e6,encode_pair_ms=code_ns/1e6,output_copy_free_pair_ms=copy_ns/1e6,pair_process_ms=(end-start)/1e6,jpeg_bytes_pair=sum(map(len,encoded)),**individual),encoded

def memory_benchmark(samples,q,monitor,out):
    monitor.phase='memory_Q'+str(q);encoder=Encoder();rows=[]
    try:
        for sample in samples[:5]:pair(encoder,sample,q) # excluded warm-up
        start=time.perf_counter();cpu=time.process_time()
        for repeat in range(5):
            for sample in samples:
                if STOP.is_set():raise RuntimeError('Interrupted')
                m,data=pair(encoder,sample,q)
                rows.append(dict(phase='memory',quality=q,repeat=repeat,pair_id=int(sample['video']['pair_id']),**m))
            monitor.guard()
        elapsed=time.perf_counter()-start
        result={'pairs':len(rows),'elapsed_s':elapsed,'fastest_sequential_pairs_per_s':len(rows)/elapsed,'cpu_percent_one_core_100':100*(time.process_time()-cpu)/elapsed,'metrics':{k:desc([r[k] for r in rows]) for k in ['convert_pair_ms','encode_pair_ms','output_copy_free_pair_ms','pair_process_ms']}}
        result['per_eye_metrics']={kind:desc([r[eye+'_'+kind] for r in rows for eye in ['left','right']]) for kind in ['convert_ms','encode_ms','copy_free_ms']}
    finally:encoder.close()
    return rows,result

def quality(ref,decoded):
    mse=float(np.mean((ref.astype(np.float32)-decoded.astype(np.float32))**2));psnr=10*math.log10(255**2/mse) if mse else 100.0
    a=cv2.cvtColor(ref,cv2.COLOR_BGR2GRAY);b=cv2.cvtColor(decoded,cv2.COLOR_BGR2GRAY)
    x=a.astype(np.float32);y=b.astype(np.float32)
    blur=lambda z:cv2.GaussianBlur(z,(11,11),1.5)
    mx,my=blur(x),blur(y);vx=np.maximum(0,blur(x*x)-mx*mx);vy=np.maximum(0,blur(y*y)-my*my);cov=blur(x*y)-mx*my
    ssim=float(np.mean(((2*mx*my+6.5025)*(2*cov+58.5225)/((mx*mx+my*my+6.5025)*(vx+vy+58.5225)))[5:-5,5:-5]))
    corners=lambda z:cv2.goodFeaturesToTrack(z,maxCorners=1000,qualityLevel=.01,minDistance=7,blockSize=3)
    c0,c1=corners(a),corners(b);n0=0 if c0 is None else len(c0);n1=0 if c1 is None else len(c1);matched=0
    if n0 and n1:
        mask=np.ones(a.shape,np.uint8)
        coords=np.rint(c1[:,0]).astype(int);mask[coords[:,1],coords[:,0]]=0
        distances=cv2.distanceTransform(mask,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
        coords=np.rint(c0[:,0]).astype(int);matched=int(np.sum(distances[coords[:,1],coords[:,0]]<=2))
    grad=lambda z:cv2.magnitude(cv2.Sobel(z,cv2.CV_32F,1,0,ksize=3),cv2.Sobel(z,cv2.CV_32F,0,1,ksize=3))
    ga,gb=grad(x),grad(y);mae=float(np.mean(np.abs(ga-gb)))
    return {'psnr_bgr_db':psnr,'ssim_gray':ssim,'reference_corners':n0,'jpeg_corners':n1,'retained_within_2px':matched,'corner_retention_fraction':matched/n0 if n0 else None,'gradient_magnitude_mae':mae,'gradient_mae_fraction_of_ref_mean':mae/float(np.mean(ga)) if np.mean(ga)>0 else None}

def quality_and_disk(samples,q,monitor,out):
    monitor.phase='quality_Q'+str(q);encoder=Encoder();rows=[];encoded_pairs=[];metadata=[]
    try:
        for sample in samples:
            monitor.guard();pid=int(sample['video']['pair_id']);blobs=[]
            for eye in ['left','right']:
                msg=sample['images'][eye];ref=convert(msg.data);data,_,_=encoder.encode(ref,q);info=sof(data)
                assert info['is_420'] and (info['width'],info['height'])==(1280,720)
                decoded=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR);assert decoded.shape==(720,1280,3)
                restored=Image();restored.header=copy.deepcopy(msg.header);restored.width=1280;restored.height=720;restored.encoding='bgr8';restored.step=3840;restored.is_bigendian=0;restored.data=decoded.tobytes()
                buf=io.BytesIO();restored.serialize(buf);again=Image();again.deserialize(buf.getvalue())
                assert header(again.header)==header(msg.header) and len(again.data)==2764800 and again.encoding=='bgr8'
                metrics=quality(ref,decoded);rows.append(dict(quality=q,pair_id=pid,eye=eye,jpeg_bytes=len(data),raw_yuyv_bytes=1843200,compression_ratio_yuyv=1843200/len(data),**metrics))
                name='Q%d_pair%04d_%s.jpg'%(q,pid,eye);blobs.append((name,data))
                metadata.append({'file':'jpeg_samples/'+name,'pair_id':pid,'eye':eye,'original_header':header(msg.header),'original_raw_sha256':hashlib.sha256(msg.data).hexdigest(),'jpeg_sha256':hashlib.sha256(data).hexdigest(),'jpeg_bytes':len(data),'sof':info,'ros_image_roundtrip_header_equal':True,'decoded_encoding':'bgr8','decoded_step':3840})
            encoded_pairs.append(blobs)
            if STOP.is_set():raise RuntimeError('Interrupted')
    finally:encoder.close()
    monitor.phase='disk_Q'+str(q);dest=out/'jpeg_samples';dest.mkdir(exist_ok=True);writes=[]
    cpu=time.process_time();start=time.perf_counter_ns()
    for blobs in encoded_pairs:
        begin=time.perf_counter_ns();sync_ns=0
        for name,data in blobs:
            with (dest/name).open('xb') as f:
                f.write(data);f.flush();t=time.perf_counter_ns();os.fdatasync(f.fileno());sync_ns+=time.perf_counter_ns()-t
        writes.append({'quality':q,'pair_write_including_fdatasync_ms':(time.perf_counter_ns()-begin)/1e6,'fdatasync_pair_ms':sync_ns/1e6,'jpeg_bytes_pair':sum(len(d) for _,d in blobs)})
    fd=os.open(str(dest),os.O_RDONLY);os.fsync(fd);os.close(fd)
    elapsed=(time.perf_counter_ns()-start)/1e9
    result={'pairs':len(writes),'elapsed_s':elapsed,'MBps_including_sync':sum(r['jpeg_bytes_pair'] for r in writes)/elapsed/1e6,'cpu_percent_one_core_100':100*(time.process_time()-cpu)/elapsed,'pair_write_including_fdatasync_ms':desc([r['pair_write_including_fdatasync_ms'] for r in writes]),'fdatasync_pair_ms':desc([r['fdatasync_pair_ms'] for r in writes]),'policy':'Two separate JPEG files per pair, flush+fdatasync each file, directory fsync at end. No encoding or input read in timed region; not a rosbag throughput measurement.'}
    for item in metadata:
        blob=(out/item['file']).read_bytes();assert hashlib.sha256(blob).hexdigest()==item['jpeg_sha256'] and sof(blob)['is_420']
        item['written_file_sha256_verified']=True
    csvout(out/('disk_Q%d.csv'%q),writes)
    return rows,metadata,result

def sustained(samples,q,monitor,out):
    monitor.phase='sustained_Q'+str(q);fifo=queue.Queue(maxsize=4);rows=[];fail=[];peak=0;offered=0;abort=threading.Event()
    start=time.monotonic_ns()+200_000_000;cpu=time.process_time();period=1e9/30
    def worker():
        enc=Encoder()
        try:
            while True:
                item=fifo.get()
                if item is None:fifo.task_done();break
                index,deadline,enqueued=item;beg=time.monotonic_ns()
                m,data=pair(enc,samples[index%len(samples)],q);end=time.monotonic_ns()
                rows.append(dict(quality=q,input_index=index,pair_id=int(samples[index%len(samples)]['video']['pair_id']),scheduled_ns=deadline,enqueued_ns=enqueued,worker_begin_ns=beg,done_ns=end,input_lateness_ms=(enqueued-deadline)/1e6,queue_wait_ms=(beg-enqueued)/1e6,end_to_end_ms=(end-deadline)/1e6,**m))
                fifo.task_done()
        except Exception as e:fail.append(str(e));abort.set()
        finally:enc.close()
    thread=threading.Thread(target=worker,daemon=True);thread.start();overflow=0
    try:
        for i in range(900):
            deadline=start+i*1_000_000_000//30
            while time.monotonic_ns()<deadline:
                if STOP.is_set() or abort.is_set():raise RuntimeError('Interrupted/worker failed')
                time.sleep(max(0,(deadline-time.monotonic_ns())/1e9))
            enqueued=time.monotonic_ns();offered+=1
            try:fifo.put_nowait((i,deadline,enqueued))
            except queue.Full:overflow+=1;fail.append('Bounded queue full; run aborted and FAILED, no silent frame skipping');break
            peak=max(peak,fifo.qsize())
            if i%30==0:monitor.guard()
        end_window=start+30_000_000_000
        if not overflow and time.monotonic_ns()<end_window:STOP.wait((end_window-time.monotonic_ns())/1e9)
    except Exception as e:fail.append(str(e))
    finally:
        try:fifo.put(None,timeout=5)
        except queue.Full:fail.append('Worker did not drain; no unbounded wait')
        thread.join(timeout=10)
        if thread.is_alive():fail.append('Worker not stopped within bound')
    wall=max(30.,(max([r['done_ns'] for r in rows] or [start])-start)/1e9)
    misses=sum(r['end_to_end_ms']>period/1e6 for r in rows)
    passed=not fail and offered==len(rows)==900 and not overflow and not misses and not STOP.is_set()
    csvout(out/('sustained_Q%d.csv'%q),rows)
    result={'status':'SUSTAINED_ENCODING_PASS' if passed else 'SUSTAINED_ENCODING_FAIL','quality':q,'target_pairs':900,'offered':offered,'completed':len(rows),'input_duration_s':30,'observed_pairs_per_s':len(rows)/wall,'queue_capacity':4,'queue_peak':peak,'queue_overflow':overflow,'deadline_misses_33_333ms':misses,'end_to_end_ms':desc([r['end_to_end_ms'] for r in rows]),'process_pair_ms':desc([r['pair_process_ms'] for r in rows]),'input_lateness_ms':desc([r['input_lateness_ms'] for r in rows]),'queue_wait_ms':desc([r['queue_wait_ms'] for r in rows]),'cpu_percent_one_core_100':100*(time.process_time()-cpu)/((time.monotonic_ns()-start)/1e9),'errors':fail,'policy':'One encoder worker; 900 fixed absolute deadlines at 30 pairs/s; queue=4 refs to real samples; no image disk writes; PASS requires all completed, no overflow and all scheduled-to-complete delays <=33.333333ms. Repeated source samples preserve original headers; schedule times are only benchmark diagnostics.'}
    save(out/('sustained_Q%d_summary.json'%q),result);print(json.dumps(result),flush=True)
    return result

def projections(out,stats,quality_rows):
    sizes=stats['serialized_bytes'];duration=30.;nonimages=sum(v for k,v in sizes.items() if k not in [LEFT,RIGHT])
    points=sizes['/livox/lidar'];imu=sizes['/livox/imu']+sizes['/zed2i/imu/data_raw'];anchors=sizes['/zed2i/time_anchor'];aux=nonimages-points-imu-anchors
    # Hypothetical sensor_msgs/CompressedImage retains Header, adds format+data
    # length. Other sensor serialized bytes already include their ROS overhead.
    meta=json.loads((out/'sample_metadata.json').read_text());header_lengths=[16+len(e['header']['frame_id'].encode()) for m in meta for e in m['eyes'].values()]
    wrapper_per_image=float(np.mean(header_lengths))+4+len('bgr8; jpeg compressed bgr8'.encode())+4
    rows=[]
    for q in [90,95]:
        vals=[r['jpeg_bytes'] for r in quality_rows if r['quality']==q];mean=float(np.mean(vals));p95=float(np.percentile(vals,95))
        for sec in [30,120,300,600,1200]:
            scale=sec/duration
            r={'quality':q,'duration_s':sec,'stereo_jpeg_payload_bytes_est':mean*60*sec,'mid_pointcloud_serialized_bytes_est':points*scale,'dual_imu_serialized_bytes_est':imu*scale,'anchors_serialized_bytes_est':anchors*scale,'other_diagnostics_serialized_bytes_est':aux*scale,'image_ros_wrapper_bytes_est':wrapper_per_image*60*sec,'container_bytes_est':stats['container_bytes']*scale}
            r['total_bytes_est']=sum(v for k,v in r.items() if k.endswith('_bytes_est'));r['total_GB_est']=r['total_bytes_est']/1e9
            r['jpeg_p95_size_scenario_total_GB_est']=(r['total_bytes_est']+(p95-mean)*60*sec)/1e9
            r['raw_C2_linear_GB_est']=stats['bag_bytes']*scale/1e9;r['reduction_percent_est']=100*(1-r['total_bytes_est']/(stats['bag_bytes']*scale));rows.append(r)
    csvout(out/'jpeg_storage_projection.csv',rows)
    save(out/'storage_model.json',{'basis':'30s requested C2 session including observed startup/shutdown sensor overhead; JPEG forecast uses exactly 30 stereo pairs/s. No compressed bag generated.','other_sensor_serialization':'Each category includes its own serialized ROS headers/field/array overhead; do not add these twice.','container_assumption':'Measured uncompressed C2 bag bytes minus all serialized message bytes, scaled linearly as a proxy; JPEG chunk/index layout will differ.','image_wrapper':'Hypothetical CompressedImage header + format string + byte-array length, no added CameraInfo. Extra sidecar/FS allocation not included.','p95_scenario':'Uses per-image sample p95 size for every image; sensitivity scenario, not statistical confidence bound.','sample_scene_warning':'48 temporal samples of this indoor/occluded scene do not represent all outdoor motion/texture; no linear thermal/runtime guarantee.'})
    return rows

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');args=ap.parse_args()
    cv2.setNumThreads(1);cv2.ocl.setUseOpenCL(False)
    if args.self_test:print(selftest());return 0
    assert cv2.getNumThreads()==1
    if psutil.virtual_memory().available<2*1024**3:raise RuntimeError('Need >=2GiB available memory before test')
    out=ROOT/'runs'/('jpeg_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
    print('BENCHMARK_DIR='+str(out),flush=True)
    for sig in [signal.SIGINT,signal.SIGTERM]:signal.signal(sig,lambda *_:STOP.set())
    original=(SESSION/'data.bag').stat();input_hash={str(p):sha(p) for p in SESSION.iterdir() if p.is_file() and p.suffix!='.bag'}
    monitor=Monitor(out);monitor.start();summary={'status':'FAILED','REALTIME_CAPTURE_PENDING':True,'SLAM_ACCURACY_PENDING':True,'PHYSICAL_SYNC_PENDING':True}
    try:
        save(out/'environment.json',{'opencv':cv2.__version__,'opencv_threads':cv2.getNumThreads(),'encoder':str(pathlib.Path(LIB).resolve()),'encoder_sha256':sha(pathlib.Path(LIB)),'jpeg_quality':[90,95],'subsampling':'TJSAMP_420 explicitly set; verify SOF Y2x2 Cb1x1 Cr1x1','dct':'TJFLAG_ACCURATEDCT','source_colorspace':{k:'UNKNOWN: not recorded in C2' for k in ['colorspace','ycbcr_enc','quantization','xfer_func']},'conversion_reference':'OpenCV4.2 COLOR_YUV2BGR_YUY2, fixed BT.601 limited-range interpretation; reference assumption only, actual sensor colorimetry UNKNOWN.','max_resident_raw_pixels_bytes':48*2*1843200,'rss_abort_bytes':1024**3,'available_abort_bytes':1024**3,'queue_capacity':4,'worker_count':1,'test_seconds_per_quality':30,'input_bag':str(SESSION/'data.bag'),'synthetic_fixture':False,'software_sha256':{p.name:sha(p) for p in ROOT.glob('*.py')}})
        print(selftest(),flush=True)
        samples,metas,stats=load_samples(out,monitor);print('Loaded 48 real pairs; bag accounting complete. Timed encoding starts after loading.',flush=True)
        all_rows=[];memory={};qrows=[];metadata=[];disk={};continuous={}
        for q in [90,95]:
            rows,result=memory_benchmark(samples,q,monitor,out);all_rows+=rows;memory[str(q)]=result;print('MEMORY Q%d '%q+json.dumps(result),flush=True)
        csvout(out/'jpeg_benchmark.csv',all_rows);save(out/'memory_summary.json',memory)
        for q in [90,95]:
            rows,meta,result=quality_and_disk(samples,q,monitor,out);qrows+=rows;metadata+=meta;disk[str(q)]=result;print('QUALITY_DISK Q%d complete'%q,flush=True)
        csvout(out/'jpeg_quality.csv',qrows);save(out/'disk_summary.json',disk)
        save(out/'jpeg_metadata_integrity.json',{'status':'PASS','sample_pairs':48,'jpeg_outputs':len(metadata),'all_420_sof_verified':True,'all_ros_image_header_roundtrips_verified':True,'jpeg_itself_contains_no_ros_header':True,'join_keys':['pair_id','eye','original_header.seq','original_header.stamp_ns','original_raw_sha256'],'results':metadata})
        projections(out,stats,qrows)
        for q in [90,95]:continuous[str(q)]=sustained(samples,q,monitor,out)
        summary.update(status='OFFLINE_BENCHMARK_PASS',memory=memory,disk=disk,sustained=continuous,bag_accounting=stats)
    except Exception as e:
        summary['error']=repr(e);print('FAILED '+repr(e),flush=True)
    finally:
        monitor.close();after=(SESSION/'data.bag').stat()
        summary['input_protection']={'bag_size_mtime_unchanged':(original.st_size,original.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'sidecars_unchanged':all(sha(pathlib.Path(p))==h for p,h in input_hash.items()),'sidecar_sha256':input_hash}
        save(out/'summary.json',summary)
        print('BENCHMARK_DIR='+str(out),flush=True)
    return 0 if summary['status']=='OFFLINE_BENCHMARK_PASS' else 2
if __name__=='__main__':raise SystemExit(main())
