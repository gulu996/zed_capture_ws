#!/usr/bin/env python3
"""Exactly one existing joint test; adds read-only thermal logging + C5F report."""
import datetime,json,pathlib,signal,subprocess,threading,time,uuid
from analyze_c5f import analyze
ROOT=pathlib.Path(__file__).resolve().parent
def read(p):
    try:return p.read_text().strip()
    except OSError:return 'UNAVAILABLE'
def main():
    out=ROOT/'runs'/('c5f_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
    print('C5F_DIR='+str(out),flush=True);stop=threading.Event();joint=None;test_dir=None
    def thermal():
        with (out/'thermal.jsonl').open('x') as f:
            while not stop.is_set():
                r={'monotonic_ns':time.monotonic_ns(),'thermal_raw_mC':{read(p/'type'):read(p/'temp') for p in pathlib.Path('/sys/class/thermal').glob('thermal_zone*')},'cooling_states':{read(p/'type'):read(p/'cur_state') for p in pathlib.Path('/sys/class/thermal').glob('cooling_device*')},'scaling_cur_kHz':{str(p):read(p) for p in pathlib.Path('/sys/devices/system/cpu').glob('cpu[0-9]*/cpufreq/scaling_cur_freq')}}
                f.write(json.dumps(r)+'\n');f.flush();stop.wait(1)
    def interrupt(sig,frame):
        if joint and joint.poll() is None:joint.send_signal(signal.SIGINT)
    signal.signal(signal.SIGINT,interrupt);signal.signal(signal.SIGTERM,interrupt)
    t=threading.Thread(target=thermal);t.start()
    try:
        argv=['/home/jetson/clock_diag/run_joint_test.sh','--config','/home/jetson/zed_capture_ws/src/zed_capture/config/capture_hd720_c5f.yaml']
        with (out/'command.json').open('x') as f:json.dump(argv,f)
        joint=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
        with (out/'terminal.log').open('x') as f:
            for line in joint.stdout:
                f.write(line);f.flush();print(line,end='',flush=True)
                if line.startswith('TEST_DIR='):test_dir=pathlib.Path(line.strip().split('=',1)[1])
        code=joint.wait()
    finally:stop.set();t.join()
    if test_dir:
        result=analyze(test_dir,out,publish_report=True)
        if not (out/'c5f_result.json').exists():
            with (out/'c5f_result.json').open('x') as f:json.dump(result,f,indent=2)
        print('C5F_RESULT='+str(out/'c5f_result.json'),flush=True)
        for k in ['CAPTURE_RUNTIME','JPEG_FILE_STORAGE','SLAM_REQUIRED_DATA_STATUS','CLOCK_DIAGNOSTIC','DATA_INTEGRITY','L2B_MAPPING','PHYSICAL_SYNC']:print(k+'='+str(result.get(k,'PENDING')))
    else:print('No joint test directory; inspect terminal.log. No retry.');return 2
    return code if result.get('JPEG_FILE_STORAGE')=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
