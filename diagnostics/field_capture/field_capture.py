#!/usr/bin/env python3
"""C5-I field orchestration: explicit duration or continuous; strict checks stay manual."""
import argparse
import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid
import yaml
from field_common import (HERE,WS,ROOT,RUNTIME,BUILD,TERMINAL,atomic,load,identity,process,
    boot_id,manager_alive,request_stop,stop_requested,tail_json,FrameCounter,
    finalized_evidence,verify_frozen)

CONFIG=HERE/'capture_hd720_c5i.yaml'
CLOCK=Path('/home/jetson/clock_diag')
sys.path.insert(0,str(WS/'scripts'))

def validate_duration(value):
    if value is None: return 0.0
    if not math.isfinite(value) or value<0: raise ValueError('Duration must be finite and nonnegative; omit for continuous')
    return value

def selected(session_id=None):
    if session_id:
        if Path(session_id).name!=session_id or session_id in ('.','..'): raise ValueError('invalid session ID')
        p=ROOT/session_id
    else:
        m=load(RUNTIME/'current.json');p=Path(m['session_dir'])
    if p.resolve().parent!=ROOT.resolve(): raise ValueError('session outside configured data root')
    identity(p)
    return p

def view(p):
    m=identity(p); s=load(p/'capture_status.json',{})
    if s and (s.get('session_id')!=m['session_id'] or s.get('token')!=m['token']):
        raise ValueError('status identity mismatch')
    age=(time.monotonic_ns()-s.get('heartbeat_monotonic_ns',0))/1e9 if m['boot_id']==boot_id() else None
    s=dict(s,session_dir=str(p),manager_alive=manager_alive(m),heartbeat_age_seconds=age)
    if s.get('state') not in TERMINAL:
        if not s['manager_alive']: s['reported_state']=s.get('state');s['state']='MANAGER_LOST / UNKNOWN'
        elif age is None or age>5: s['reported_state']=s.get('state');s['state']='STALE / UNKNOWN'
    return s

def display(s):
    c=s.get('sensor_counters',{});q=s.get('queues',{})
    elapsed=s.get('elapsed_seconds');elapsed='WAITING_FOR_CAPTURE_START' if elapsed is None else ('%.1f s'%elapsed)
    print('\nC5-I-A FIELD CAPTURE | '+s.get('session_id','UNKNOWN')+' | '+s.get('state','UNKNOWN')+
        '\nElapsed: '+elapsed+' / '+('CONTINUOUS' if s.get('duration_seconds')==0 else str(s.get('duration_seconds'))+' s')+' (initialization excluded)'+
        '\nJPEG saved / terminal-index encoded: '+str(c.get('jpeg_written'))+' / '+str(c.get('jpeg_encoded_observed'))+
        '\nMID LiDAR / IMU: '+str(c.get('lidar_written'))+' / '+str(c.get('livox_imu_written'))+
        '\nGNSS bytes / ROS written: '+str(c.get('gnss_raw_bytes'))+' / '+str(c.get('gnss_ros_written'))+
        '\nDisk free GB: '+str(round(s['disk_free_bytes']/1e9,2) if s.get('disk_free_bytes') is not None else None)+
        '\nQueues: '+json.dumps(q)+'\nWriter: '+s.get('bag_writer','UNKNOWN')+
        '\nHeartbeat age: '+str(s.get('heartbeat_age_seconds','live'))+' | Error: '+str(s.get('last_error'))+
        '\nData: '+s.get('session_dir','UNKNOWN')+'\nFULL_STRICT_CHECK=PENDING',flush=True)

def wait_status(p,stop_on_ctrl_c=False,until_end=False,timeout=None):
    begin=time.monotonic()
    while True:
        try:
            s=view(p);display(s)
            if s.get('state') in TERMINAL:
                f=load(p/'capture_finalization.json',{})
                print(json.dumps(f,indent=2),flush=True)
                return 0 if s['state'] in ('FINALIZED','CANCELLED_BEFORE_CAPTURE') else 2
            if not s.get('manager_alive'): return 2
            if timeout and time.monotonic()-begin>=timeout:
                print('STOP_WAIT_TIMEOUT: no forced kill. Inspect stage, owned_children, heartbeats and field.log.',flush=True)
                print(json.dumps(load(p/'field_runner_status.json',{}),indent=2));return 2
            if not until_end:return 0
            time.sleep(1)
        except KeyboardInterrupt:
            if not stop_on_ctrl_c: return 0
            print(request_stop(p,'FOREGROUND_CTRL_C'),flush=True)
            stop_on_ctrl_c=False
            print('Waiting for safe finalization; another Ctrl+C exits observation only. Manager continues.',flush=True)
        except (BrokenPipeError,OSError) as e:
            # Observer output/SSH loss never requests capture stop.
            if isinstance(e,BrokenPipeError):return 0
            raise

class Progress:
    def __init__(self,p):self.p=p;self.counter=FrameCounter();self.capture_start=None;self.last_elapsed=None
    def read(self):
        p=self.p;metrics=tail_json(p/'capture_metrics.jsonl');jpeg=tail_json(p/'jpeg_progress.jsonl')
        cp=tail_json(p/'c5g_checkpoints.jsonl');self.counter.update(p/'frames.csv')
        start=metrics.get('input_watchdog',{}).get('capture_start_monotonic_ns')
        if start is not None:self.capture_start=start
        # Elapsed is the latest producer observation, not time spent in finalization.
        if start is not None:self.last_elapsed=max(0,(metrics['input_watchdog']['evaluation_monotonic_ns']-start)/1e9)
        node=load(p/'field_node_status.json',{})
        if start is not None and node.get('capture_end_monotonic_ns',0)>=start:
            self.last_elapsed=(node['capture_end_monotonic_ns']-start)/1e9
        stats={k:metrics.get(k) for k in ('pairs_written','lidar_written','livox_imu_written','zed_imu_written')}
        raw=p/'gnss/serial_raw.bin';stats.update(gnss_raw_bytes=raw.stat().st_size if raw.exists() else None,
            gnss_ros_written=sum(t['written'] for t in cp.get('gnss',{}).get('topics',{}).values()) if 'gnss' in cp else None,
            jpeg_encoded_observed=self.counter.encoded,jpeg_written=self.counter.written,
            jpeg_terminal_errors=self.counter.errors)
        if (p/'manager_result.json').exists():
            final=load(p/'capture_summary.json',{});jfinal=load(p/'jpeg_files_summary.json',{})
            stats.update({k:final[k] for k in ('pairs_written','lidar_written','livox_imu_written','zed_imu_written') if k in final})
            if 'completed' in jfinal:stats['jpeg_written']=jfinal['completed']
            gw=load(p/'gnss_writer_summary.json',{})
            if 'topics' in gw:stats['gnss_ros_written']=sum(t['written'] for t in gw['topics'].values())
        queues={k:jpeg.get(k) for k in ('encode_queue','encode_queue_peak','write_queue','write_queue_peak')}
        queues.update(bag_bytes=metrics.get('queue_bytes'),bag_peak_bytes=metrics.get('queue_peak_bytes'),bag_overflows=metrics.get('queue_overflows'))
        recording_error=None
        for name in ('failure.txt','startup_error.txt','jpeg_shadow_failure.txt'):
            try:
                with (p/name).open() as stream:recording_error=stream.read(4096)
                if recording_error:break
            except FileNotFoundError:pass
        return dict(elapsed_seconds=self.last_elapsed,capture_start_monotonic_ns=self.capture_start,
            recording_error=recording_error,
            sensor_counters=stats,queues=queues,disk_free_bytes=shutil.disk_usage(p).free,
            observations={'metrics_monotonic_ns':metrics.get('monotonic_ns'),
                'jpeg_progress_monotonic_ns':jpeg.get('monotonic_ns'),'gnss_counts_monotonic_ns':cp.get('end_ns'),
                'index_backlog':self.counter.backlog,
                'counter_semantics':'Encoded count = observed terminal index rows, excludes in-flight tasks; GNSS written checkpoint every 5s; unknown is null'},
            finalization_stage=node.get('stage','UNKNOWN'),
            bag_writer='OPEN' if any(p.glob('*.bag.active')) else ('CLOSED' if (p/'sensors.bag').exists() else 'NOT_OPEN'))

class Backend:
    """Injectable at software-test call site; no public mock capture CLI."""
    pre_seconds=15;post_seconds=15
    def prepare(self,p,duration):
        verify_frozen()
        build=load(BUILD/'manifest.json')
        for name,h in build['sha256'].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=h:raise RuntimeError('Candidate build changed: '+name)
        sys.path.insert(0,str(CLOCK))
        import joint_test,session_field
        cfg=yaml.safe_load(CONFIG.read_bytes())
        original=yaml.safe_load((WS/'src/zed_capture/config/capture_hd720_c5g.yaml').read_bytes())
        if cfg!=original:raise ValueError('Field config must retain frozen C5-G sensor parameters')
        # Reuse hardware checks with unchanged sensor policy at 30s planning horizon;
        # full requested duration remains separate and disk reserve is continuous.
        probe=joint_test.hardware_check(cfg,True,30)
        candidate_probe=session_field.preflight(cfg,duration)
        probe['field_runtime_preflight']=candidate_probe
        probe['errors']+=candidate_probe['errors']
        from capture_environment import capture_environment,check_dynamic_dependencies
        probe['field_candidate_dependencies']=check_dynamic_dependencies(BUILD/'lib/zed_capture/zed_capture_node',capture_environment())
        probe['errors']+=probe['field_candidate_dependencies']['errors']
        # Detect visible users of actual video/HID/serial identities without opening devices.
        probe['device_occupancy']=device_occupancy(cfg)
        probe['errors']+=probe['device_occupancy']['errors']
        atomic(p/'field_preflight.json',probe,True)
        if probe['errors']:raise RuntimeError('Preflight blocked: '+repr(probe['errors']))
        shutil.copy2(CONFIG,p/'field_config.yaml')
        atomic(p/'field_software.json',{'frozen':verify_frozen(),'candidate':build,
            'field_sources':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in HERE.glob('*.py')}},True)
        (p/'clock').mkdir()
        joint_test.timesync_snapshot(p/'clock/timesync_before.txt')
    def spawn_monitor(self,p,fd):
        return self.spawn([str(CLOCK/'clock_monitor'),str(p/'clock'),'0'],p/'clock/monitor.log',fd)
    def monitor_ready(self,p):
        f=p/'clock/clock_samples.csv'
        if f.exists() and f.stat().st_size:
            if not (p/'clock/three_clock.csv').exists():os.link(f,p/'clock/three_clock.csv')
            return True
        return False
    def spawn_capture(self,p,duration,fd):
        return self.spawn([sys.executable,'-B',str(HERE/'session_field.py'),'--field-session-dir',str(p),
            '--config',str(CONFIG),'--duration',str(duration)],p/'capture_terminal.log',fd)
    def spawn(self,argv,log,fd):
        env=dict(os.environ,C5I_LOCK_FD=str(fd),PYTHONDONTWRITEBYTECODE='1')
        with log.open('x') as f:
            return subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,
                env=env,start_new_session=True,pass_fds=(fd,))
    def finish_clock(self,p):
        sys.path.insert(0,str(CLOCK));import joint_test
        joint_test.timesync_snapshot(p/'clock/timesync_after.txt')
        # Preserve raw evidence and unchanged monitor summary. Offline clock calculations
        # are explicitly separate too; they are NOT replaced by a fabricated PASS.
        return {'summary':load(p/'clock/clock_monitor_summary.json',{}),'CLOCK_DIAGNOSTIC':'PENDING_OFFLINE_ANALYSIS'}

def device_occupancy(cfg):
    """Read proc fd links; never chmod/open/claim/reset hardware."""
    candidates=[]
    for p in Path('/sys/class/video4linux').glob('video*'):
        try:
            if 'ZED' in (p/'name').read_text():candidates.append(Path('/dev')/p.name)
        except OSError:pass
    for p in Path('/sys/bus/usb/devices').iterdir():
        try:
            if (p/'idVendor').read_text().strip()=='2b03':
                candidates.append(Path('/dev/bus/usb/%03d/%03d'%(int((p/'busnum').read_text()),int((p/'devnum').read_text()))))
        except (OSError,ValueError):pass
    if cfg.get('gnss_enable'):candidates.append(Path(cfg['gnss_port']))
    targets={str(p.resolve()) for p in candidates};busy=[];denied=0
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
        try:
            for fd in (proc/'fd').iterdir():
                try:
                    target=os.readlink(fd)
                    if target in targets:busy.append({'pid':int(proc.name),'fd':fd.name,'target':target})
                except FileNotFoundError:pass
        except FileNotFoundError:pass
        except PermissionError:denied+=1
    return {'busy':busy,'permission_denied_processes':denied,'errors':['Device already open: '+repr(busy)] if busy else [],
            'visibility':'proc namespace only; GNSS also uses existing exclusive_serial at actual open, V4L2 errors remain fatal'}

def run_manager(p,duration,lockfd,backend=None):
    backend=backend or Backend();m=identity(p)
    m.update(manager_pid=os.getpid(),manager_start_ticks=process(os.getpid())['start_ticks'],
        process_group_id=os.getpgrp(),boot_id=boot_id(),log_path=str(p/'field.log'))
    atomic(p/'field_identity.json',m,True);atomic(RUNTIME/'current.json',m,True)
    progress=Progress(p);monitor=capture=None;error=None;requested=[False];monitor_stopped=False
    state='PREFLIGHT';last_status={};end=None;status_failure=False
    def sigstop(sig,frame):requested[0]=True
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    signal.signal(signal.SIGINT,sigstop);signal.signal(signal.SIGTERM,sigstop)
    def stopping():
        if requested[0] and not stop_requested(p):request_stop(p,'MANAGER_SIGNAL')
        return stop_requested(p)
    def publish(phase):
        nonlocal last_status
        observation=progress.read()
        last_status=dict(m,state=phase,duration_seconds=duration,heartbeat_monotonic_ns=time.monotonic_ns(),
            heartbeat_realtime_ns=time.time_ns(),last_error=error or observation['recording_error'],**observation)
        atomic(p/'capture_status.json',last_status)
    try:
        publish(state)
        if not stopping():backend.prepare(p,duration)
        if not stopping():
            state='CLOCK_PRE_ROLL';publish(state);monitor=backend.spawn_monitor(p,lockfd)
            begin=time.monotonic()
            while not backend.monitor_ready(p):
                if monitor.poll() is not None or time.monotonic()-begin>5:raise RuntimeError('Clock monitor readiness failed')
                if stopping():break
                time.sleep(.05)
            begin=time.monotonic()
            while not stopping() and time.monotonic()-begin<backend.pre_seconds:
                if monitor.poll() is not None:raise RuntimeError('Clock monitor exited in pre-roll')
                publish(state);time.sleep(.5)
        if not stopping():
            state='INITIALIZING';publish(state);capture=backend.spawn_capture(p,duration,lockfd)
            while capture.poll() is None:
                stopping()
                if monitor.poll() is not None:raise RuntimeError('Clock monitor exited during capture')
                runner=load(p/'field_runner_status.json',{})
                if stop_requested(p) or runner.get('stage') in ('FINALIZING','WAIT_CAPTURE_FINALIZATION','WAIT_GNSS_EXIT','WAIT_OWNED_ROS_EXIT'):
                    state='FINALIZING'
                elif progress.capture_start is not None:state='RECORDING'
                publish(state);time.sleep(1)
            end=time.monotonic();state='FINALIZING';publish(state)
    except Exception as e:
        error=repr(e);print('FIELD ERROR:',error,flush=True)
        # Always let the owned receiver/node perform normal finalization.
        if capture and capture.poll() is None:
            try:request_stop(p,'MANAGER_ERROR')
            except Exception as stop_error:print('STOP REQUEST ERROR:',repr(stop_error),flush=True)
            # Owned and unreaped child: safe even if full disk prevents request-file creation.
            # Its handler forwards one graceful signal; before handler installation no
            # sensors have been started. Never signal arbitrary metadata PIDs.
            capture.send_signal(signal.SIGINT)
    finally:
        while capture and capture.poll() is None:
            try:publish('FINALIZING')
            except Exception as e:print('STATUS WRITE FAILED:',repr(e),flush=True);status_failure=True
            time.sleep(1)  # intentionally no escalation; stop command may time out honestly
        if capture:end=time.monotonic()
        if monitor and monitor.poll() is None:
            until=time.monotonic()+backend.post_seconds
            while time.monotonic()<until:
                try:publish('CLOCK_POST_ROLL')
                except Exception as e:print('STATUS WRITE FAILED:',repr(e),flush=True);status_failure=True
                time.sleep(.5)
            monitor.send_signal(signal.SIGINT);monitor_stopped=True
            while monitor.poll() is None:
                try:publish('WAIT_CLOCK_FINALIZATION')
                except Exception:status_failure=True
                time.sleep(.5)
        try:
            clock=backend.finish_clock(p) if monitor else {'CLOCK_DIAGNOSTIC':'NOT_STARTED'}
            if monitor and (monitor.returncode!=0 or not monitor_stopped):error=error or 'CLOCK_MONITOR_FAILED'
            if capture:
                final=finalized_evidence(p,yaml.safe_load(CONFIG.read_text()).get('gnss_enable',False))
                manager_result=load(p/'manager_result.json',{})
                runtime=(capture.returncode==0 and manager_result.get('returncode')==0
                    and final['capture_failed'] is False and final['jpeg_failed'] is False)
                state='FINALIZED' if final['FINALIZATION_STATUS']=='FINALIZED' and runtime and not error and not status_failure else 'FAILED'
                final['CAPTURE_RUNTIME']='PASS' if runtime else 'FAIL'
                final['capture_process_returncode']=capture.returncode
            else:
                state='CANCELLED_BEFORE_CAPTURE' if stopping() and not error else 'FAILED'
                final={'CAPTURE_RUNTIME':'NOT_STARTED','FINALIZATION_STATUS':'NO_CAPTURE_STARTED',
                    'BAG_FINALIZED':False,'JPEG_FINAL_SYNCED':False,'GNSS_FINAL_SYNCED':False}
            final.update(session_id=p.name,session_dir=str(p),token=m['token'],boot_id=m['boot_id'],state=state,
                error=error,clock=clock,FULL_STRICT_CHECK='PENDING',DATA_INTEGRITY='PENDING',
                stop_requested=stop_requested(p),manager_children_exited=True,PHYSICAL_SYNC='PENDING',L2B_MAPPING='PENDING')
            # Sync only small closing evidence. Producers already synced all data/indexes.
            for name in ('capture_summary.json','manager_result.json','session.json','gnss_writer_summary.json'):
                f=p/name
                if f.exists():
                    with f.open('rb') as stream:os.fsync(stream.fileno())
            atomic(p/'capture_finalization.json',final,True);publish(state)
            print(json.dumps(final,indent=2),flush=True)
        except Exception as e:
            print('FINALIZATION EVIDENCE FAILED:',repr(e),flush=True)
            try:
                error=repr(e)
                atomic(p/'capture_finalization.json',dict(session_id=p.name,session_dir=str(p),token=m['token'],boot_id=m['boot_id'],
                    state='FAILED',CAPTURE_RUNTIME='FAIL',FINALIZATION_STATUS='UNCONFIRMED',BAG_FINALIZED=False,
                    JPEG_FINAL_SYNCED=False,GNSS_FINAL_SYNCED=False,FULL_STRICT_CHECK='PENDING',DATA_INTEGRITY='PENDING',
                    PHYSICAL_SYNC='PENDING',error=error,manager_children_exited=True),True)
                publish('FAILED')
            except Exception:pass
            return 2
    return 0 if state in ('FINALIZED','CANCELLED_BEFORE_CAPTURE') else 2

def launch(duration,detach):
    duration=validate_duration(duration);verify_frozen()
    RUNTIME.mkdir(exist_ok=True)
    fd=os.open(str(RUNTIME/'hardware.lock'),os.O_CREAT|os.O_RDWR,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('An existing field manager/owned child holds the hardware lease; refusing duplicate startup')
        # If metadata claims a live manager even with no lease, stop to investigate.
        old=load(RUNTIME/'current.json',{})
        if old and manager_alive(old):raise RuntimeError('Existing live manager; refusing duplicate startup')
        name=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
        ROOT.mkdir(exist_ok=True);p=ROOT/name;p.mkdir(mode=0o750)
        atomic(p/'field_identity.json',dict(session_id=name,session_dir=str(p),token=uuid.uuid4().hex,
            boot_id=boot_id(),manager_pid=None,manager_start_ticks=None),True)
        # Publish the recovery path before starting an independent manager.
        # Even a detached-child startup/observer failure must leave a visible ID.
        print('SESSION='+str(p),flush=True)
        with (p/'field.log').open('x') as log:
            manager=subprocess.Popen([sys.executable,'-B',str(HERE/'field_capture.py'),'_manager',str(p),
                '--duration',str(duration),'--lock-fd',str(fd)],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                start_new_session=True,pass_fds=(fd,))
        for _ in range(100):
            if manager_alive(identity(p)) and (p/'capture_status.json').exists():break
            if manager.poll() is not None:raise RuntimeError('Manager exited at startup: '+str(p/'field.log'))
            time.sleep(.05)
        else:raise RuntimeError('Manager startup not confirmed; inspect '+str(p)+'; no automatic retry')
    finally:os.close(fd)
    if detach:
        print('Detached manager running. SSH loss/Ctrl+C in observer does not stop capture. Use stop_capture.sh.',flush=True);return 0
    print('Following: Ctrl+C requests graceful stop. SSH SIGHUP only disconnects observer.',flush=True)
    signal.signal(signal.SIGHUP,lambda *_:sys.exit(0))
    return wait_status(p,True,True)

def main():
    ap=argparse.ArgumentParser(description=__doc__);sp=ap.add_subparsers(dest='command',required=True)
    a=sp.add_parser('start');a.add_argument('--duration',type=float);a.add_argument('--detach',action='store_true')
    for name in ('status','stop'):
        a=sp.add_parser(name);a.add_argument('--session')
        if name=='status':a.add_argument('--follow',action='store_true');a.add_argument('--json',action='store_true')
        else:a.add_argument('--timeout',type=float,default=120)
    a=sp.add_parser('_manager');a.add_argument('directory');a.add_argument('--duration',type=float,required=True);a.add_argument('--lock-fd',type=int,required=True)
    args=ap.parse_args()
    if args.command=='start':return launch(args.duration,args.detach)
    if args.command=='_manager':
        args.duration=validate_duration(args.duration)
        actual=os.fstat(args.lock_fd);expected=(RUNTIME/'hardware.lock').stat()
        if (actual.st_dev,actual.st_ino)!=(expected.st_dev,expected.st_ino):raise ValueError('invalid inherited hardware lease')
        fcntl.flock(args.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        p=Path(args.directory).resolve(strict=True)
        if p.parent!=ROOT.resolve() or identity(p).get('manager_pid') is not None or (p/'capture_status.json').exists():
            raise ValueError('manager requires a newly reserved, unused field session')
        return run_manager(p,args.duration,args.lock_fd)
    p=selected(args.session)
    if args.command=='status':
        if args.json:print(json.dumps(view(p),indent=2));return 0
        return wait_status(p,False,args.follow)
    if not math.isfinite(args.timeout) or args.timeout<=0:raise ValueError('timeout must be finite and positive')
    print(request_stop(p),flush=True)
    return wait_status(p,False,True,args.timeout)

if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,RuntimeError,OSError,KeyError) as exc:
        print('REFUSED/FAILED:',str(exc),file=sys.stderr);sys.exit(2)
