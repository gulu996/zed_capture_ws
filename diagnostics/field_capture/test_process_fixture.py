#!/usr/bin/env python3
"""SYNTHETIC subprocess lifecycle fixture. No devices, sockets or real capture."""
import json,os,pathlib,signal,subprocess,sys,time
from field_common import atomic,boot_id,load,stop_requested
P=pathlib.Path

def capture(p,scenario):
    import rosbag
    from std_msgs.msg import String
    import rospy
    stopped=[False]
    signal.signal(signal.SIGINT,lambda *_:stopped.__setitem__(0,True))
    (p/'gnss').mkdir();atomic(p/'session.json',dict(session_id=p.name,boot_id=boot_id(),synthetic_fixture=True,config={'gnss_enable':True}))
    atomic(p/'control.json',{'manager_pid':os.getpid(),'start_ticks':'SYNTHETIC_NOT_A_REAL_CONTROLLER'})
    atomic(p/'field_runner_status.json',{'stage':'CAPTURE_PROCESS_RUNNING','synthetic':True})
    start=time.monotonic_ns()
    with (p/'capture_metrics.jsonl').open('x') as f:
        f.write(json.dumps({'monotonic_ns':start,'input_watchdog':{'capture_start_monotonic_ns':start,'evaluation_monotonic_ns':start},'pairs_written':1,'lidar_written':1,'livox_imu_written':1})+'\n')
    # 300 virtual seconds are NOT 300 seconds of sensor acquisition.
    deadline=time.monotonic()+(.8 if scenario=='auto300' else 30)
    with rosbag.Bag(str(p/'sensors.bag.active'),'w') as bag:
        bag.write('/SYNTHETIC/lifecycle',String('NO_HARDWARE'),rospy.Time(123,456))
        while time.monotonic()<deadline and not stopped[0] and not stop_requested(p):time.sleep(.02)
        atomic(p/'field_node_status.json',{'stage':'GNSS_HANDSHAKE','capture_end_monotonic_ns':time.monotonic_ns(),'synthetic':True})
        atomic(p/'field_runner_status.json',{'stage':'FINALIZING','synthetic':True})
        time.sleep(.4)
    os.rename(p/'sensors.bag.active',p/'sensors.bag')
    (p/'gnss/serial_raw.bin').write_bytes(b'SYNTHETIC_NO_FIX\r\n')
    atomic(p/'gnss/summary.json',{'session':p.name,'boot_id':boot_id(),'status':'RAW_RECEPTION_RECORDED','errors':[],
        'raw_bytes':len(b'SYNTHETIC_NO_FIX\r\n'),'position_quality':'NO_FIX','synthetic':True})
    (p/'gnss/done').write_text('0 0 0 0 0 0\n');(p/'gnss/ack').write_text('SYNTHETIC\n')
    atomic(p/'gnss_writer_summary.json',{'complete':True,'topics':{}})
    atomic(p/'jpeg_files_summary.json',{'final_synced':True,'workers_joined':True,'sync_error':'','failed':False,'completed':0})
    atomic(p/'capture_summary.json',{'bag_finalized':True,'failed':False})
    atomic(p/'manager_result.json',{'returncode':0,'interrupted':stopped[0] or stop_requested(p)})
    return 0

def monitor(p):
    stop=[False];signal.signal(signal.SIGINT,lambda *_:stop.__setitem__(0,True))
    (p/'clock_samples.csv').write_text('SYNTHETIC,NO_HARDWARE\n')
    while not stop[0]:time.sleep(.02)
    atomic(p/'clock_monitor_summary.json',{'synthetic_fixture':True});return 0

def manager(p,scenario):
    import field_capture as f
    f.RUNTIME=p.parent/'runtime';f.RUNTIME.mkdir(exist_ok=True)
    class Fake(f.Backend):
        pre_seconds=.2;post_seconds=.2
        def prepare(self,p,d):
            if scenario=='init_stop':time.sleep(.8)
            if scenario=='disk_full':raise RuntimeError('SYNTHETIC_DISK_RESERVE_REACHED')
            (p/'clock').mkdir()
        def spawn_monitor(self,p,fd):return self.spawn([sys.executable,'-B',__file__,'monitor',str(p/'clock')],p/'clock/monitor.log',fd)
        def spawn_capture(self,p,d,fd):return self.spawn([sys.executable,'-B',__file__,'capture',str(p),scenario],p/'capture_terminal.log',fd)
        def finish_clock(self,p):return {'CLOCK_DIAGNOSTIC':'SYNTHETIC_NOT_VALIDATED'}
    fd=os.open(str(f.RUNTIME/'fixture.lock'),os.O_CREAT|os.O_RDWR,0o600)
    return f.run_manager(p,300,fd,Fake())

if __name__=='__main__':
    mode=sys.argv[1];p=P(sys.argv[2])
    sys.exit(capture(p,sys.argv[3]) if mode=='capture' else monitor(p) if mode=='monitor' else manager(p,sys.argv[3]))
