#!/usr/bin/env python3
"""One ordinary-user, metadata-only test. Never stop another process."""
import sys
sys.dont_write_bytecode=True
import argparse,datetime,fcntl,json,os,pathlib,re,signal,subprocess,time,uuid
ROOT=pathlib.Path(__file__).resolve().parent;WS=ROOT.parents[1]
sys.path.insert(0,str(WS/'scripts'))
from capture_environment import capture_environment
from analyze import comparison,MODES

def save(path,obj):
    with pathlib.Path(path).open('x') as f:json.dump(obj,f,indent=2)
def probe_dependencies():
    # Linker --as-needed omits HIDAPI/libusb: this executable uses only V4L2.
    # Do not reuse the production node's requirement that libusb be present.
    command=['/usr/bin/ldd','-r',str(ROOT/'build/zed_v4l2_probe')];env=capture_environment();errors=[]
    for key in ['LD_PRELOAD','LD_AUDIT']:
        if env.get(key):errors.append(key+' is nonempty; isolation needs review')
    try:
        p=subprocess.run(command,text=True,capture_output=True,env=env,timeout=20)
        if p.returncode:errors.append('ldd -r returned '+str(p.returncode))
        errors.extend(l for l in (p.stdout+p.stderr).splitlines() if re.search(r'undefined symbol|not found|relocation error|cannot open shared object',l,re.I))
        return {'command':command,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'errors':errors,'status':'FAIL' if errors else 'SOFTWARE_TESTED'}
    except (OSError,subprocess.TimeoutExpired) as e:return {'command':command,'errors':[str(e)],'status':'FAIL'}
def processes(devices,proc=pathlib.Path('/proc')):
    busy=[];ambient=[];unreadable=[];myself=os.getpid()
    names={'zed_capture_node','start_capture.sh','session.py','run_joint_test.sh','joint_test.py','rosbag','record','zed_v4l2_probe'}
    for p in proc.iterdir():
        if not p.name.isdigit() or int(p.name)==myself:continue
        try:args=[s.decode(errors='replace') for s in (p/'cmdline').read_bytes().split(b'\0') if s]
        except (OSError,PermissionError):continue
        if not args:continue
        known=any(pathlib.Path(a).name in names for a in args[:3])
        if known:busy.append({'pid':int(p.name),'reason':'capture/record process exists','args':args})
        if any('livox' in a.lower() for a in args[:3]):ambient.append({'pid':int(p.name),'args':args,'note':'not stopped; potential ambient load'})
        try:
            for fd in (p/'fd').iterdir():
                try:target=os.path.realpath(os.readlink(fd))
                except OSError:continue
                if target in devices:busy.append({'pid':int(p.name),'reason':'ZED video node already open','fd':str(fd),'target':target})
        except PermissionError:unreadable.append(int(p.name))
        except FileNotFoundError:pass
    return {'busy':busy,'ambient_livox':ambient,'inaccessible_fd_tables':unreadable,
            'scope':'Readable process/fd tables only; kernel V4L2 EBUSY remains authoritative. No process is killed.'}

def preflight():
    r={'errors':[],'warnings':[],'devices':[],'status':'LOW_LOAD_HARDWARE_PENDING'}
    if os.geteuid()==0:r['errors'].append('Refusing root; use ordinary jetson SSH')
    for v in pathlib.Path('/sys/class/video4linux').glob('video*'):
        for p in v.resolve().parents:
            try:
                if (p/'idVendor').read_text().strip()=='2b03' and (p/'idProduct').read_text().strip()=='f880':
                    r['devices'].append({'node':'/dev/'+v.name,'sysfs':str(p),'index':int((v/'index').read_text()),'speed':(p/'speed').read_text().strip(),'serial':(p/'serial').read_text().strip(),'accessible':os.access('/dev/'+v.name,os.R_OK|os.W_OK)});break
            except (OSError,ValueError):pass
    candidates=[d for d in r['devices'] if d['index']==0]
    if len(candidates)!=1:r['errors'].append('Expected exactly one identity-matched ZED video capture interface (index 0)')
    else:
        r['selected']=candidates[0]
        if not candidates[0]['accessible']:r['errors'].append('Identity-matched /dev/video node inaccessible: sandbox or Unix permissions; no device open attempted')
        if float(candidates[0]['speed'])<5000:r['errors'].append('SuperSpeed >=5000 Mb/s not verified; refuse altered link baseline')
    r['processes']=processes([d['node'] for d in r['devices']])
    if r['processes']['busy']:r['errors'].append('Existing capture or video owner detected; refusing to interfere')
    if r['processes']['ambient_livox']:r['warnings'].append('Existing Livox remains active; total system load is not fully controlled')
    r['dynamic_dependencies']=probe_dependencies()
    r['errors']+=r['dynamic_dependencies']['errors']
    import hashlib
    try:
        manifest=json.loads((ROOT/'build/build_manifest.json').read_text())
        changed=[name for name,digest in manifest['files'].items() if hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest()!=digest]
        r['build_manifest_changed_inputs']=changed
        if changed:r['errors'].append('Probe inputs differ from build manifest; rebuild the independent probe before testing')
    except (OSError,ValueError,KeyError) as e:r['errors'].append('Build manifest unavailable: '+str(e))
    r['free_bytes']=os.statvfs(ROOT).f_bavail*os.statvfs(ROOT).f_frsize
    if r['free_bytes']<100*1024*1024:r['errors'].append('Less than 100 MiB free for metadata/logs')
    if not r['errors']:r['status']='READY_FOR_ONE_LOW_LOAD_RUN'
    return r

def snapshot(out,label):
    commands={'usb_tree':['lsusb','-t'],'kernel':['journalctl','-k','-b','--no-pager','-o','short-monotonic']}
    for name,cmd in commands.items():
        try:
            p=subprocess.run(cmd,text=True,capture_output=True,timeout=15);save(out/(label+'_'+name+'.json'),{'command':cmd,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        except (OSError,subprocess.TimeoutExpired) as e:save(out/(label+'_'+name+'.json'),{'status':'UNAVAILABLE','error':str(e)})
    save(out/(label+'_system.json'),{'monotonic_ns':time.monotonic_ns(),'realtime_ns':time.time_ns(),'meminfo':pathlib.Path('/proc/meminfo').read_text(),'vmstat':pathlib.Path('/proc/vmstat').read_text(),'diskstats':pathlib.Path('/proc/diskstats').read_text(),'stat':pathlib.Path('/proc/stat').read_text(),'loadavg':pathlib.Path('/proc/loadavg').read_text()})

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--preflight-only',action='store_true')
    ap.add_argument('--resolution',choices=list(MODES),default='HD1080',help='Native camera mode; default HD1080; no resizing or pixel conversion')
    args=ap.parse_args();width,height=MODES[args.resolution]
    out=ROOT/'runs'/('probe_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir()
    print('PROBE_DIR='+str(out),flush=True)
    # Prevent concurrent probes; this advisory lock does not replace V4L2 ownership.
    lock=(ROOT/'runs/.probe.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:save(out/'result.json',{'status':'REFUSED','reason':'another probe holds lock'});return 2
    r=preflight();r.update(requested_resolution=args.resolution,requested_size=[width,height]);save(out/'preflight.json',r)
    if r['errors'] or args.preflight_only:
        result={'status':r['status'],'errors':r['errors'],'hardware_run_started':False,'resolution_mode':args.resolution}
        if args.resolution=='HD720':result.update(NATIVE_720P_SUPPORTED='PENDING_HARDWARE',LOW_LOAD_720P_RUNTIME='PENDING_HARDWARE',LOW_LOAD_720P_CONTINUITY='PENDING_HARDWARE',JPEG_REALTIME_PENDING=True)
        save(out/'result.json',result);print(json.dumps(result,indent=2));return 2 if r['errors'] else 0
    # Read-only logs before/after; no wrapper polling/writes during streaming.
    snapshot(out,'before')
    second=processes([d['node'] for d in r['devices']]);save(out/'ownership_recheck.json',second)
    if second['busy']:save(out/'result.json',{'status':'REFUSED','reason':'ownership changed during preflight'});return 2
    env=capture_environment();env['ZED_LOW_LOAD_PREFLIGHT']='1'
    import hashlib
    files=[ROOT/'probe.cpp',ROOT/'native_mode.hpp',ROOT/'run.py',ROOT/'analyze.py',ROOT/'build/zed_v4l2_probe',WS/'devel/lib/libcapture_oc.a',WS/'devel/lib/libcapture_hidapi.a']
    save(out/'software.json',{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    save(out/'build_manifest.json',json.loads((ROOT/'build/build_manifest.json').read_text()))
    protected=[WS/'devel/lib/libcapture_oc.a',WS/'devel/lib/libcapture_hidapi.a',WS/'devel/lib/zed_capture/zed_capture_node',WS/'src/zed_capture/config/capture.yaml',WS/'scripts/start_capture.sh']
    protection={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    save(out/'formal_before.json',protection)
    save(out/'session.json',{'duration_s':30,'start_definition':'first returned frame; at most 10s initial wait','resolution_mode':args.resolution,'resolution':[width,height],'per_eye_resolution':[width//2,height],'pixel_format':'YUYV','fps':30,'mmap_buffers':4,'native_output':True,'image_resize':False,'timestamp_policy':'raw V4L2 integer sec/usec and flags; MONOTONIC expected, not exposure-center verified','calibration_status':'UNVERIFIED_FOR_SELECTED_MODE','image_data_saved':False,'hardware_run_started':True,'comparison_A':str(__import__('analyze').BASE),'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'ambient_load':second['ambient_livox'],'device':r['selected']})
    with (out/'probe.log').open('x') as log:
        child=subprocess.Popen([str(ROOT/'build/zed_v4l2_probe'),r['selected']['node'],str(out),args.resolution],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        def interrupt(sig,frame):
            if child.poll() is None:child.send_signal(sig)
        signal.signal(signal.SIGINT,interrupt);signal.signal(signal.SIGTERM,interrupt)
        code=child.wait()
    snapshot(out,'after')
    unchanged=all(hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==h for p,h in protection.items())
    save(out/'formal_after.json',{'matches_before':unchanged,'scope':list(protection)})
    result={'status':'LOW_LOAD_RUNTIME_FAIL','returncode':code,'hardware_run_started':True,'resolution_mode':args.resolution,'FORMAL_CAPTURE_UNCHANGED':'VERIFIED' if unchanged else 'FAIL'}
    if args.resolution=='HD720':result.update(NATIVE_720P_SUPPORTED='UNVERIFIED',LOW_LOAD_720P_RUNTIME='FAIL',LOW_LOAD_720P_CONTINUITY='UNVERIFIED',JPEG_REALTIME_PENDING=True)
    try:
        c=comparison(out);result.update(status='LOW_LOAD_RUNTIME_'+c['low_load_runtime'],observed_continuity=c['observed_continuity'],frames=c['B']['frames'],fps=c['B']['fps'],long_intervals=c['B']['long_intervals'],driver_sequence_missing=c['B']['driver_sequence_missing'])
        if args.resolution=='HD720':
            result.update({k:c[k] for k in ['NATIVE_720P_SUPPORTED','LOW_LOAD_720P_RUNTIME','LOW_LOAD_720P_CONTINUITY','JPEG_REALTIME_PENDING']})
            result.update(max_interval_ms=c['B']['interval_ms']['max'] if c['B']['interval_ms'] else None,
                select_timeouts=c['B']['select_timeouts'],startup_select_timeouts=c['B']['startup_select_timeouts'],dq_eagain=c['B']['dq_eagain'],dq_other_errors=c['B']['dq_other_errors'],qbuf_errors=c['B']['qbuf_errors'],loop_cpu_percent_one_core_100=c['B']['loop_cpu_percent_one_core_100'],usb_speed_Mbps=r['selected']['speed'])
    except Exception as e:result['analysis_error']=str(e)
    if code!=0:
        result['status']='LOW_LOAD_RUNTIME_FAIL'
        if args.resolution=='HD720':result['LOW_LOAD_720P_RUNTIME']='FAIL'
    save(out/'result.json',result);print(json.dumps(result,indent=2));print('PROBE_DIR='+str(out))
    if args.resolution=='HD720':
        with (out/'zed_native_720p_validation.md').open('x') as report:
            report.write('# Native 720P single-run validation\n\nSession: `'+str(out)+'`\n\n```json\n'+json.dumps(result,indent=2)+'\n```\n\n')
            report.write('Evidence: v4l2_enumeration.json (ENUM_FMT, YUYV ENUM_FRAMESIZES, target ENUM_FRAMEINTERVALS), v4l2_negotiated.json (G_FMT/G_PARM after setting), v4l2_before/after.json, video_io_events.csv, comparison.json, probe_end.json, before/after system and USB snapshots. Missing files indicate the stage was not reached.\n\n')
            report.write('No pixel data saved or JPEG encoded. Full image-content quality, stereo splitting, IMU, L2-B and physical synchronization are not validated by this probe. HD720 intrinsics must be checked separately. Historical A uses HD1080 and joint recording; it is not a same-resolution load control. No C2 or JPEG test is automatically started.\n')
    return 0 if code==0 and result['status']=='LOW_LOAD_RUNTIME_PASS' else 2
if __name__=='__main__':raise SystemExit(main())
