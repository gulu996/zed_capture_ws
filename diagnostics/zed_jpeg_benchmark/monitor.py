"""Bounded-rate read-only telemetry; no clocks, governors or permissions changed."""
import json,pathlib,threading,time
import psutil
P=pathlib.Path
def read(path):
    try:return P(path).read_text().strip()
    except OSError:return 'UNAVAILABLE'
class Monitor:
    def __init__(self,out):
        self.phase='startup';self.stop_event=threading.Event();self.rows=[];self.proc=psutil.Process()
        self.thermal=[(p,read(p/'type')) for p in P('/sys/class/thermal').glob('thermal_zone*')]
        self.cooling=[(p,read(p/'type')) for p in P('/sys/class/thermal').glob('cooling_device*')]
        self.freq=list(P('/sys/devices/system/cpu').glob('cpu[0-9]*/cpufreq/scaling_cur_freq'))
        self.power=[]
        for d in P('/sys/class/hwmon').glob('*'):
            if read(d/'name')=='ina3221':self.power=list(d.glob('in*_input'))+list(d.glob('curr*_input'))
        self.out=out;self.thread=threading.Thread(target=self.loop,daemon=True)
    def loop(self):
        self.proc.cpu_percent()
        with (self.out/'resources.jsonl').open('x') as f:
            while not self.stop_event.is_set():
                row={'monotonic_ns':time.monotonic_ns(),'phase':self.phase,'rss_bytes':self.proc.memory_info().rss,'cpu_percent_one_core_100':self.proc.cpu_percent(),
                     'available_bytes':psutil.virtual_memory().available,'thermal_raw_mC':{name:read(p/'temp') for p,name in self.thermal},
                     'cooling_states':{name:read(p/'cur_state') for p,name in self.cooling},'scaling_cur_kHz':{str(p):read(p) for p in self.freq},'ina3221_raw':{str(p):read(p) for p in self.power}}
                self.rows.append(row);f.write(json.dumps(row)+'\n');f.flush()
                if len(self.rows)>=900:self.stop_event.set();break
                self.stop_event.wait(1)
    def start(self):self.thread.start()
    def close(self):self.stop_event.set();self.thread.join(timeout=3)
    def guard(self):
        if self.proc.memory_info().rss>1024**3 or psutil.virtual_memory().available<1024**3:raise RuntimeError('Memory safety budget exceeded; no retry')
