#!/usr/bin/env python3
"""Own child processes and exclusive session directory; never kill existing nodes."""
import argparse, datetime, hashlib, json, os, pathlib, shutil, signal, socket, subprocess, sys, time, uuid
import yaml
sys.path.insert(0, "/home/jetson/zed_capture_ws/scripts")
from field_common import identity, stop_requested, atomic, BUILD
from long_recording import extra_resources
from field_policy import validate as long_validate
def long_arguments(cfg,duration):
    long_validate(cfg,duration)
    return ['_long_recording:=true','_minimum_free_gb:='+str(cfg['minimum_free_gb'])]
from capture_environment import capture_environment, check_dynamic_dependencies
from storage_mode import storage_arguments,bag_name
from gnss_config import gnss_arguments,gnss_preflight,software_hashes as gnss_software_hashes,modules as gnss_modules
from jpeg_shadow_config import shadow_arguments,shadow_preflight
WS=pathlib.Path("/home/jetson/zed_capture_ws")
def dump(path,value):
    with open(path,'x') as f: json.dump(value,f,indent=2)
def usb_devices():
    result=[]
    for p in pathlib.Path('/sys/bus/usb/devices').iterdir():
        try:
            if (p/'idVendor').read_text().strip()!='2b03': continue
            row={'sysfs':str(p)}
            for key in ['idVendor','idProduct','serial','product','speed','busnum','devnum']:
                if (p/key).exists(): row[key]=(p/key).read_text().strip()
            row['devnode']='/dev/bus/usb/%03d/%03d'%(int(row['busnum']),int(row['devnum']))
            row['accessible']=os.access(row['devnode'],os.R_OK|os.W_OK)
            result.append(row)
        except OSError: pass
    return result
def preflight(cfg,duration,node_environment=None):
    # Check eager symbol relocation before any ROS master/driver is started.
    node_environment=capture_environment() if node_environment is None else node_environment
    dynamic=check_dynamic_dependencies(BUILD/'lib/zed_capture/zed_capture_node',node_environment)
    errors=['Capture dynamic dependencies: '+e for e in dynamic['errors']];warnings=[];devices=usb_devices();videos=[]
    storage_arguments(cfg,30)
    jpeg_cfg=dict(cfg)
    if cfg.get("storage_mode")=="jpeg_files":jpeg_cfg["jpeg_shadow_enable"]=True
    shadow=shadow_preflight(jpeg_cfg,30,node_environment)
    errors.extend(shadow['errors'])
    relocation=subprocess.run(['/usr/bin/ldd','-r',str(BUILD/'lib/libcapture_jpeg_shadow.so')],capture_output=True,text=True,env=node_environment)
    relocation_text=relocation.stdout+relocation.stderr
    if relocation.returncode or any(term in relocation_text.lower() for term in ('undefined symbol','not found','relocation error')):errors.append('Field JPEG plugin relocation failed: '+relocation_text)
    shadow['field_plugin']=str(BUILD/'lib/libcapture_jpeg_shadow.so')
    if long_validate(cfg,duration):
        symbols=subprocess.run(['/usr/bin/nm','-D','--defined-only',str(BUILD/'lib/libcapture_jpeg_shadow.so')],capture_output=True,text=True)
        if symbols.returncode or not any(line.split()[-1:] == ['create_jpeg_files_incremental'] for line in symbols.stdout.splitlines()):errors.append('C5-G incremental JPEG factory missing; rebuild required')
    gnss=gnss_preflight(cfg,30);errors.extend(gnss['errors'])
    for p in pathlib.Path('/sys/class/video4linux').glob('video*'):
        if 'ZED' in (p/'name').read_text():
            node='/dev/'+p.name;videos.append({'node':node,'accessible':os.access(node,os.R_OK|os.W_OK)})
    video_usb=[d for d in devices if d['idProduct']=='f880'];hid=[d for d in devices if d['idProduct']=='f881' and d.get('serial')==str(cfg['serial'])]
    if not video_usb: errors.append('ZED 2i USB video device not found')
    elif not all(float(d.get('speed','0'))>=5000 for d in video_usb): errors.append('ZED USB3 speed is below 5000 Mbit/s')
    if not any(d['accessible'] for d in videos): errors.append('No accessible ZED /dev/video* node; device sandbox or Unix permissions')
    if not hid: errors.append('Selected ZED HID serial not found')
    elif not hid[0]['accessible']: errors.append('ZED HID USB node inaccessible; device sandbox or Unix permissions')
    if not (BUILD/'lib/zed_capture/zed_capture_node').is_file(): errors.append('Capture executable not built')
    if not pathlib.Path(cfg['anchor_path']).is_file(): warnings.append('timeshare_imu is absent; raw capture allowed, SYNC_PENDING')
    w,h=(1920,1080) if cfg['resolution']=='HD1080' else (1280,720)
    estimate=w*h*4*30*(30 if duration==0 else min(duration,30))
    root=pathlib.Path(cfg['output_root']).expanduser().resolve();probe=root
    while not probe.exists(): probe=probe.parent
    free=shutil.disk_usage(probe).free
    if free<estimate*1.15+cfg['minimum_free_gb']*1e9: errors.append('Insufficient initial disk headroom plus 10GB reserve')
    try:
        sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM);sock.close()
    except OSError as e: errors.append('ROS TCP socket unavailable: '+str(e))
    return {'status':'BLOCKED' if errors else 'READY_FOR_HARDWARE_TEST','errors':errors,'warnings':warnings,'dynamic_dependencies':dynamic,'jpeg_shadow':shadow,'gnss':gnss,'usb':devices,'video_nodes':videos,'requested_duration_seconds':duration,'continuous':duration==0,'disk_estimate_kind':'conservative raw bound for up to 30s initial headroom; full duration not guaranteed, 1Hz reserve guard safely stops before disk exhaustion','estimated_image_bytes':estimate,'free_bytes':free,'sync_status':'SYNC_PENDING'}
def start_ticks(pid): return pathlib.Path('/proc/%d/stat'%pid).read_text().split(') ',1)[1].split()[19]
def resource_sample(pids,session):
    row={'monotonic_ns':time.monotonic_ns(),'realtime_ns':time.time_ns(),'pids':{},'system_cpu_ticks':[int(v) for v in pathlib.Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]}
    # Include roslaunch/roscore descendants, not only their launcher PIDs.
    family=set(pids);parents={}
    for proc in pathlib.Path('/proc').iterdir():
        if proc.name.isdigit():
            try:parents[int(proc.name)]=int((proc/'stat').read_text().split(') ',1)[1].split()[1])
            except (OSError,ValueError):pass
    for _ in range(16):
        extended=family|{pid for pid,parent in parents.items() if parent in family}
        if extended==family:break
        family=extended
    for pid in family:
        try:
            fields=pathlib.Path('/proc/%d/stat'%pid).read_text().split(') ',1)[1].split()
            io=dict(line.split(': ',1) for line in pathlib.Path('/proc/%d/io'%pid).read_text().splitlines())
            row['pids'][str(pid)]={'cpu_ticks':int(fields[11])+int(fields[12]),'rss_bytes':int(fields[21])*os.sysconf('SC_PAGE_SIZE'),'write_bytes':int(io['write_bytes']),'syscw':int(io['syscw'])}
        except OSError: pass
    row['clock_ticks_per_second']=os.sysconf('SC_CLK_TCK')
    row['meminfo_kb']={line.split(':')[0]:int(line.split()[1]) for line in pathlib.Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:','MemFree:','Dirty:','Writeback:','SwapFree:'))}
    for p in ['/sys/devices/gpu.0/load','/sys/devices/platform/17000000.ga10b/load']:
        try: row['gpu_load_raw_0_to_1000']=int(pathlib.Path(p).read_text());break
        except OSError: pass
    row['bag_bytes']=sum(p.stat().st_size for pattern in ('*.bag','*.bag.active') for p in session.glob(pattern))
    return row
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--field-session-dir',required=True);ap.add_argument('--config',default=str(WS/'src/zed_capture/config/capture.yaml'));ap.add_argument('--duration',type=float,default=0);ap.add_argument('--preflight',action='store_true');ap.add_argument('--validated-short-session');ap.add_argument('--livox-mode',choices=['auto','reuse']);args=ap.parse_args()
    field_session=pathlib.Path(args.field_session_dir).resolve(strict=True)
    field_identity=identity(field_session)
    config_path=pathlib.Path(args.config).expanduser().resolve(strict=True)
    config_bytes=config_path.read_bytes();cfg=yaml.safe_load(config_bytes)
    if args.livox_mode: cfg['livox_mode']=args.livox_mode
    long_validate(cfg,args.duration)
    if cfg['resolution'] not in ['HD1080','HD720'] or cfg['fps']!=30: ap.error('supported modes: HD1080/30 and explicit HD720/30')
    try:storage_args=storage_arguments(cfg,30);shadow_args=shadow_arguments(cfg,30);gnss_args=gnss_arguments(cfg,30)
    except ValueError as e:ap.error(str(e))
    if args.duration>30 and not long_validate(cfg,args.duration):
        if not args.validated_short_session: ap.error('Run and check 30 seconds first; then pass --validated-short-session PATH')
        previous=pathlib.Path(args.validated_short_session)
        check=json.loads((previous/'check_result.json').read_text());old=json.loads((previous/'session.json').read_text())
        if check.get('capture_integrity')!='PASS' or check.get('synthetic_fixture') or old['config']!=cfg or old.get('duration_requested_s',0)<30 or check.get('streams',{}).get('/zed2i/left/image_raw',{}).get('duration_s',0)<27: ap.error('30-second short session must pass integrity checks with the same configuration; synthetic data is not accepted')
    node_environment=capture_environment()
    if shadow_args or cfg.get("storage_mode")=="jpeg_files":
        # C3-equivalent single-thread numeric libraries, capture child only.
        node_environment.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    result=preflight(cfg,args.duration,node_environment);print(json.dumps(result,indent=2),flush=True)
    if args.preflight:return 0 if not result['errors'] else 2
    if result['errors']:return 2
    # Imported only after device/socket checks. No ROS node is started during preflight.
    import rosgraph
    socket.setdefaulttimeout(3)
    master=rosgraph.Master('/zed_capture_session')
    children=[];handles=[];node=None;gnss_child=None;interrupted=False;stop_sent=False
    root=pathlib.Path(cfg['output_root']).expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
    session=field_session
    if session.parent!=root or (session/'session.json').exists():raise RuntimeError('field session root/exclusivity mismatch')
    print('SESSION='+str(session),flush=True)
    if long_validate(cfg,args.duration):print('C5-I PLAN duration='+('CONTINUOUS' if args.duration==0 else str(args.duration)+'s')+' mode=jpeg_files directory='+str(session)+' free_bytes='+str(shutil.disk_usage(session).free),flush=True)
    def spawn(argv,name,environment=None):
        log=open(session/(name+'.log'),'x');handles.append(log)
        child=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=environment,pass_fds=(int(os.environ['C5I_LOCK_FD']),));children.append(child);return child
    def interrupt(signum,frame):
        nonlocal interrupted,stop_sent
        interrupted=True
        if node and node.poll() is None and not stop_sent:
            stop_sent=True
            # A second request during known finalization must not interrupt fsync.
            phase_path=session/'field_node_status.json'
            try:phase=json.loads(phase_path.read_text()).get('stage')
            except (OSError,ValueError):phase=None
            if phase not in ('STOPPING_PRODUCERS','GNSS_HANDSHAKE','DRAIN_BAG_WRITER','DRAIN_JPEG_AND_SYNC','CLOSE_AND_SYNC_BAG_SIDECARS','NODE_FINALIZED'):
                node.send_signal(signal.SIGINT)
    def stop_check():
        if stop_requested(session):interrupt(None,None)
        return interrupted
    def stage(name):
        # A status-write failure must never abort queue drain or receiver cleanup.
        owned=[]
        for child in children:
            if child.poll() is None:
                try:owned.append({'pid':child.pid,'start_ticks':start_ticks(child.pid),'returncode':None})
                except OSError:pass  # child exited between poll and proc read
        try:atomic(session/'field_runner_status.json',{'stage':name,'monotonic_ns':time.monotonic_ns(),'owned_children':owned})
        except OSError as e:
            try:print('FIELD_RUNNER_STATUS_UNAVAILABLE: '+str(e),file=sys.stderr,flush=True)
            except OSError:pass
    signal.signal(signal.SIGINT,interrupt);signal.signal(signal.SIGTERM,interrupt)
    dump(session/'control.json',{'manager_pid':os.getpid(),'start_ticks':start_ticks(os.getpid()),'session':str(session)})
    code=2
    try:
        stage('INITIALIZING')
        if stop_check():raise RuntimeError('Stopped before ROS startup')
        try:master.getPid()
        except Exception:
            spawn(['roscore'],'roscore')
            for _ in range(50):
                time.sleep(.2)
                if stop_check():raise RuntimeError('Stopped during ROS startup')
                try:master.getPid();break
                except Exception:pass
            else:raise RuntimeError('ROS master not available')
        pubs,subs,services=master.getSystemState();pubdict=dict(pubs);nodes={n for _,ns in pubs+subs+services for n in ns}
        if any('fastlivo' in n.lower() or 'fast_livo' in n.lower() or n.rsplit('/',1)[-1].lower()=='lasermapping' for n in nodes):raise RuntimeError('FAST-LIVO appears active; leave existing process untouched and stop collection startup')
        if any(t.startswith('/zed2i/') and ns for t,ns in pubs):raise RuntimeError('Existing /zed2i publisher detected; refusing duplicate capture')
        if dict(master.getPublishedTopics('/')).get('/livox/lidar') not in [None,'livox_ros_driver2/CustomMsg']:raise RuntimeError('Existing Livox pointcloud type is not CustomMsg')
        if cfg.get('gnss_enable',False):
            if any(any(key in n.lower() for key in ('gnss_adapter','rtk_fixed_lag_backend','gnss_fault_injector')) for n in nodes):raise RuntimeError('Existing GNSS fusion/adapter node detected; recording-only session refuses to feed it')
            core,_=gnss_modules()
            if any(pubdict.get(t[0]) for t in core.TOPICS):raise RuntimeError('Existing GNSS publisher; refusing second receiver process')
        has_lidar=bool(pubdict.get('/livox/lidar'));has_imu=bool(pubdict.get('/livox/imu'))
        if has_lidar!=has_imu:raise RuntimeError('Only one Livox topic is present; refusing to start a duplicate driver')
        rosparams=subprocess.run(['rosparam','get','/use_sim_time'],capture_output=True,text=True)
        if rosparams.returncode==0 and rosparams.stdout.strip().lower()=='true':raise RuntimeError('use_sim_time is enabled; do not change it automatically')
        manifest={'session_id':session.name,'created_realtime_ns':time.time_ns(),'created_monotonic_ns':time.monotonic_ns(),'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'config':cfg,'duration_requested_s':args.duration,'preflight':result,'sync_status':'SYNC_PENDING','physical_sync_verified':False,'calibration':{'intrinsics':None,'lidar_camera_extrinsics':None},'recording':'C++ rosbag API, explicit topic whitelist, uncompressed','image_header_clock':'original V4L2 buffer clock; flags in VideoStamp','zed_imu_header_clock':'device_ticks * 78125 / 2 ns (floor)','livox_headers':'unchanged','bag_record_clock':'host CLOCK_REALTIME at acquisition/ROS reception; not exposure time','software_manifest_sha256':hashlib.sha256((WS/'evidence/software_manifest.json').read_bytes()).hexdigest(),'livox_reused':has_lidar}
        manifest.update(field_mode='C5-I-B',continuous=args.duration==0,bag_segment_limit_bytes=536870912,bag_segment_message_limit=250000,field_manager_identity=field_identity,full_strict_check='PENDING')
        manifest.update(config_path=str(config_path),config_sha256=hashlib.sha256(config_bytes).hexdigest())
        manifest.update(storage_mode=cfg.get('storage_mode','raw_bag'),sensor_bag=bag_name(cfg))
        if cfg.get('storage_mode')=='jpeg_files':manifest['recording']='C5F JPEG files + sensors.bag; no image pixels in bag'
        dump(session/'session.json',manifest)
        dump(session/'capture_loader.json',{'scope':'zed_capture_node only; master/Livox inherit manager environment','inherited_ld_library_path':os.environ.get('LD_LIBRARY_PATH'),'capture_ld_library_path':node_environment['LD_LIBRARY_PATH'],'check':result['dynamic_dependencies']})
        with (session/'capture.yaml').open('xb') as f:f.write(config_bytes)
        shutil.copy2(WS/'evidence/software_manifest.json',session/'software_manifest.json')
        for src,name in [('/home/jetson/catkin_ws/src/livox_ros_driver2/config/MID360_config.json','livox_config.json'),('/home/jetson/catkin_ws/src/livox_ros_driver2/include/livox_ros_driver2/imu_time_anchor.h','livox_anchor_protocol.h')]:shutil.copy2(src,session/name)
        if cfg.get('gnss_enable',False):dump(session/'gnss_software.json',gnss_software_hashes())
        if not has_lidar:
            if cfg['livox_mode']=='reuse':raise RuntimeError('No existing Livox publisher; reuse mode does not launch a driver')
            if stop_check():raise RuntimeError('Stopped before sensor startup')
            spawn(['roslaunch','livox_ros_driver2','msg_MID360.launch','rviz_enable:=false','rosbag_enable:=false','xfer_format:=1','imu_anchor_enable:=true','imu_timeshare_path:='+cfg['anchor_path']],'livox')
            time.sleep(2)
        if stop_check():raise RuntimeError('Stopped before camera startup')
        # Explicit false also clears a stale private ROS parameter left by C4.
        node_command=[str(BUILD/'lib/zed_capture/zed_capture_node'),'_session_dir:='+str(session),'_resolution:='+cfg['resolution'],'_serial:='+str(cfg['serial']),'_video_id:='+str(cfg['video_id']),'_duration:='+str(args.duration),'_queue_mb:='+str(cfg['queue_mb']),'_anchor_path:='+cfg['anchor_path']]+(shadow_args or ['_jpeg_shadow_enable:=false'])+storage_args+gnss_args+long_arguments(cfg,args.duration)
        dump(session/'capture_command.json',{'argv':node_command,'jpeg_shadow_enable':bool(shadow_args)})
        if shadow_args or cfg.get("storage_mode")=="jpeg_files":
            shadow_files=[BUILD/'lib/zed_capture/zed_capture_node',BUILD/'lib/libcapture_jpeg_shadow.so',WS/'src/zed_capture/src/jpeg_shadow.cpp',WS/'src/zed_capture/include/zed_capture/jpeg_shadow_worker.hpp',WS/'src/zed_capture/include/zed_capture/jpeg_shadow.hpp',WS/'src/zed_capture/include/zed_capture/jpeg_files.hpp',WS/'scripts/session.py',WS/'src/zed_capture/src/capture_node.cpp']
            dump(session/'jpeg_shadow_software.json',{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in shadow_files})
            if cfg.get('storage_mode')=='jpeg_files':
                current=shadow_files+[WS/'scripts/storage_mode.py',WS/'scripts/jpeg_file_check.py',WS/'scripts/check_recording.py']+list((WS/'diagnostics/zed_jpeg_c5f').glob('*.py'))
                dump(session/'c5f_software.json',{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in current})
                if long_validate(cfg,args.duration):
                    files=current+[WS/'src/zed_capture/include/zed_capture/long_recording.hpp',WS/'scripts/long_recording.py',WS/'scripts/gnss_config.py',WS/'diagnostics/gnss_r2/gnss_receiver.py',pathlib.Path('/home/jetson/clock_diag/joint_test.py')]
                    dump(session/'c5g_software.json',{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
        if cfg.get('gnss_enable',False):
            gnss_env=dict(os.environ);gnss_env['PYTHONDONTWRITEBYTECODE']='1'
            gnss_child=spawn([sys.executable,str(pathlib.Path(__file__).resolve().parent/'gnss_field.py'),'--session',str(session)],'gnss_receiver',environment=gnss_env)
        node=spawn(node_command,'capture',environment=node_environment)
        stop_check()
        with open(session/'resources.jsonl','x') as resources:
            while node.poll() is None:
                stop_check()
                stage('FINALIZING' if interrupted or (session/'gnss/stop').exists() else 'CAPTURE_PROCESS_RUNNING')
                if gnss_child and gnss_child.poll() is not None and not (session/'gnss/ack').exists():
                    interrupt(None,None);raise RuntimeError('GNSS receiver exited before shutdown acknowledgement')
                row=resource_sample([p.pid for p in children],session)
                if long_validate(cfg,args.duration):row.update(extra_resources(session))
                resources.write(json.dumps(row)+'\n');resources.flush();time.sleep(1)
        code=node.returncode
        if gnss_child:
            try:gnss_code=gnss_child.wait(timeout=15)
            except subprocess.TimeoutExpired:gnss_code=2
            if gnss_code:code=2
    except Exception as e:
        print('BLOCKED/FAILED: '+str(e),file=sys.stderr)
        with open(session/'startup_error.txt','x') as f:f.write(str(e)+'\n')
    finally:
        stage('FINALIZING')
        # The node owns the GNSS stop/done/ack handshake and queue drains.
        # Never proceed to stop its receiver/master while it is still finalizing.
        if node and node.poll() is None:
            interrupt(None,None)
            while node.poll() is None:
                stage('WAIT_CAPTURE_FINALIZATION')
                time.sleep(1)
        if gnss_child and gnss_child.poll() is None:
            # Startup failure without a node still preserves the receiver's raw close path.
            if node is None:
                (session/'gnss/stop').touch(exist_ok=True)
            while gnss_child.poll() is None:
                stage('WAIT_GNSS_EXIT')
                time.sleep(1)
        for child in reversed(children):
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                while child.poll() is None:
                    stage('WAIT_OWNED_ROS_EXIT')
                    time.sleep(1)
        for f in handles:f.close()
        dump(session/'manager_result.json',{'returncode':code,'interrupted':interrupted,'sync_status':'SYNC_PENDING'})
    stage('CHILDREN_EXITED')
    # FULL_STRICT_CHECK is exclusively the separate check_capture.sh command.
    print('SESSION='+str(session),flush=True)
    return code
if __name__=='__main__':sys.exit(main())
