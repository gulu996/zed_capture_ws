#!/usr/bin/env python3
"""One arm per invocation, no retry, unchanged joint monitor/capture pipeline."""
import argparse,datetime,hashlib,json,os,pathlib,re,signal,subprocess,sys,threading,time
import yaml
ROOT=pathlib.Path(__file__).resolve().parent;WS=ROOT.parents[1]
sys.path.insert(0,str(WS/'diagnostics/zed_jpeg_shadow'))
from analyze_c4 import analyze
from analyze_worker import analyze as analyze_worker
def read(p):
    try:return p.read_text().strip()
    except OSError:return 'UNAVAILABLE'
def save(p,obj):
    with p.open('x') as f:json.dump(obj,f,indent=2)
def code_hashes():
    paths=[WS/'devel/lib/zed_capture/zed_capture_node',WS/'devel/lib/libcapture_jpeg_shadow.so',WS/'scripts/session.py',pathlib.Path('/home/jetson/clock_diag/clock_monitor'),pathlib.Path('/home/jetson/clock_diag/joint_test.py'),pathlib.Path('/home/jetson/clock_diag/analyze.py'),ROOT/'run_control.py',ROOT/'analyze_worker.py']
    paths += [WS/('src/zed_capture/config/capture_hd720_c41_'+arm+'.yaml') for arm in ['off','on']]
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
def control_configs():
    paths={arm:WS/('src/zed_capture/config/capture_hd720_c41_'+arm+'.yaml') for arm in ['off','on']}
    cfg={arm:yaml.safe_load(p.read_text()) for arm,p in paths.items()}
    assert cfg['off']['jpeg_shadow_enable'] is False and cfg['on']['jpeg_shadow_enable'] is True
    a=dict(cfg['off']);b=dict(cfg['on']);a.pop('jpeg_shadow_enable');b.pop('jpeg_shadow_enable');assert a==b
    assert a==yaml.safe_load((WS/'src/zed_capture/config/capture_hd720_c2.yaml').read_text())
    return paths,cfg
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--arm',choices=['off','on'],required=True);ap.add_argument('--experiment',required=True);ap.add_argument('--conditions-note',required=True);args=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.experiment):ap.error('experiment: use letters/digits/_/-')
    paths,cfg=control_configs();pair=ROOT/'runs'/args.experiment;out=pair/args.arm
    if out.exists():ap.error('This arm already has an attempt; never overwrite or auto-retry')
    hashes=code_hashes()
    if args.arm=='on':
        if not (pair/'off/arm_result.json').exists():ap.error('Run OFF arm first and wait for completion')
        baseline=json.loads((pair/'off/arm_result.json').read_text());before=json.loads((pair/'off/conditions_before.json').read_text())
        if baseline.get('CAPTURE_RUNTIME')!='CAPTURE_RUNTIME_PASS':ap.error('OFF did not complete normally; review its failure before ON')
        if before['software_sha256']!=hashes:ap.error('Software changed between arms; cannot claim one planned variable')
    out.mkdir(parents=True);print('C41_DIR='+str(out),flush=True)
    def snapshot():
        usb=[]
        for p in pathlib.Path('/sys/bus/usb/devices').glob('*'):
            if read(p/'idVendor')=='2b03':usb.append({k:read(p/k) for k in ['idVendor','idProduct','serial','speed','busnum','devnum']})
        ps=subprocess.run(['ps','-eo','pid,comm,pcpu,pmem'],capture_output=True,text=True,timeout=5)
        return {'wall_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns(),'user_conditions_note':args.conditions_note,'conditions_verification':'USER_DECLARED_NOT_MACHINE_VERIFIED','software_sha256':hashes,'config_path':str(paths[args.arm]),'config':cfg[args.arm],'config_sha256':hashlib.sha256(paths[args.arm].read_bytes()).hexdigest(),'usb':usb,'loadavg':read(pathlib.Path('/proc/loadavg')),'process_names_cpu_memory':ps.stdout,'thermal_raw_mC':{read(p/'type'):read(p/'temp') for p in pathlib.Path('/sys/class/thermal').glob('thermal_zone*')}}
    save(out/'conditions_before.json',snapshot());(out/'capture_config.yaml').write_bytes(paths[args.arm].read_bytes())
    stop=threading.Event();child=None;test_dir=None
    def monitor():
        with (out/'thermal.jsonl').open('x') as f:
            while not stop.is_set():
                e={'monotonic_ns':time.monotonic_ns(),'thermal_raw_mC':{read(p/'type'):read(p/'temp') for p in pathlib.Path('/sys/class/thermal').glob('thermal_zone*')},'cooling_states':{read(p/'type'):read(p/'cur_state') for p in pathlib.Path('/sys/class/thermal').glob('cooling_device*')},'scaling_cur_kHz':{str(p):read(p) for p in pathlib.Path('/sys/devices/system/cpu').glob('cpu[0-9]*/cpufreq/scaling_cur_freq')}}
                f.write(json.dumps(e)+'\n');f.flush();stop.wait(1)
    def interrupt(sig,frame):
        if child and child.poll() is None:child.send_signal(signal.SIGINT)
    signal.signal(signal.SIGINT,interrupt);signal.signal(signal.SIGTERM,interrupt)
    t=threading.Thread(target=monitor);t.start()
    try:
        argv=['/home/jetson/clock_diag/run_joint_test.sh','--config',str(paths[args.arm])];save(out/'command.json',argv)
        child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
        with (out/'terminal.log').open('x') as f:
            for line in child.stdout:
                f.write(line);f.flush();print(line,end='',flush=True)
                if line.startswith('TEST_DIR='):test_dir=pathlib.Path(line.strip().split('=',1)[1])
        code=child.wait()
    finally:stop.set();t.join();save(out/'conditions_after.json',snapshot())
    joint=json.loads((test_dir/'test_result.json').read_text()) if test_dir and (test_dir/'test_result.json').exists() else {}
    session=pathlib.Path(joint['session_path']) if joint.get('session_path') else None
    if args.arm=='on' and session:
        result=analyze(test_dir,out,publish_report=False);trace=analyze_worker(session);save(out/'c41_worker_analysis.json',trace)
        result['C41_WORKER_DIAGNOSTICS']=trace['status']
    else:
        check=json.loads((session/'check_result.json').read_text()) if session and (session/'check_result.json').exists() else {}
        result={'CAPTURE_RUNTIME':joint.get('capture_runtime','PENDING_HARDWARE'),'DATA_INTEGRITY':joint.get('data_integrity','PENDING'),'CLOCK_DIAGNOSTIC':joint.get('clock_diagnostic','PENDING'),'JPEG_SHADOW_COMPLETION':'NOT_ENABLED_CONTROL','streams':check.get('streams'),'raw_integrity_check':check,'session':str(session) if session else None}
    result.update(arm=args.arm,experiment=args.experiment,test_dir=str(test_dir),exit_code=code);save(out/'arm_result.json',result)
    print('C41_RESULT='+str(out/'arm_result.json'),flush=True)
    if args.arm=='on' and (result.get('JPEG_SHADOW_COMPLETION')!='PASS' or result.get('JPEG_SHADOW_QUEUE')!='PASS' or result.get('JPEG_SHADOW_LATENCY')!='PASS' or result.get('C41_WORKER_DIAGNOSTICS')!='SOFTWARE_EVIDENCE_COMPLETE'):return 2
    return code
if __name__=='__main__':raise SystemExit(main())
