#!/usr/bin/env python3
"""Read-only independent arithmetic for the single completed A/B experiment.

Only creates a new review directory; never writes into input runs or reads bags.
"""
import collections
import csv
import hashlib
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parent
A = pathlib.Path('/home/jetson/zed_capture_data/20261017_144432_c0112f6c')
B = ROOT / 'runs/probe_20261017_152106_349a1c1e'
OUT = ROOT / 'evidence/review_20261017_152106'

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def read(p):
    with p.open() as f:
        return [{k: int(v) for k, v in r.items()} for r in csv.DictReader(f)]

def desc(v):
    s = sorted(v)
    def percentile(q):
        x = (len(s)-1)*q
        i = int(x)
        return s[i]+(s[min(i+1, len(s)-1)]-s[i])*(x-i)
    return dict(min=min(s), median=statistics.median(s), p95=percentile(.95),
                p99=percentile(.99), max=max(s))

def summarize(p):
    rows = read(p / 'video_io_events.csv')
    frames = [r for r in rows if r['pair_id'] > 0]
    ts = [r['v4l2_sec']*10**9+r['v4l2_usec']*1000 for r in frames]
    intervals = [y-x for x,y in zip(ts, ts[1:])]
    seq = [(y['sequence']-x['sequence']) & 0xffffffff for x,y in zip(frames,frames[1:])]
    keys = ['select_before_ns','select_after_ns','dq_before_ns','dq_ioctl_start_ns',
            'dq_after_ns','callback_end_ns','qbuf_before_ns','qbuf_ioctl_start_ns',
            'qbuf_end_ns','iteration_end_ns']
    wall = rows[-1]['iteration_end_ns']-rows[0]['select_before_ns']
    return {
        'events':len(rows), 'frames':len(frames), 'first_last_sequence':[frames[0]['sequence'],frames[-1]['sequence']],
        'video_span_s':(ts[-1]-ts[0])/1e9, 'fps':(len(frames)-1)*1e9/(ts[-1]-ts[0]),
        'interval_ms':desc([v/1e6 for v in intervals]), 'long_intervals':sum(v>50000000 for v in intervals),
        'timestamp_nonincreasing':sum(v<=0 for v in intervals),
        'driver_sequence_missing':sum(v-1 for v in seq if 1<v<0x80000000),
        'sequence_duplicate':seq.count(0), 'sequence_backward_or_reset':sum(v>=0x80000000 for v in seq),
        'event_ids_contiguous':[r['event_id'] for r in rows]==list(range(1,len(rows)+1)),
        'pair_ids_contiguous':[r['pair_id'] for r in frames]==list(range(1,len(frames)+1)),
        'recorded_intervals_match_raw':all(r['successful_frame_interval_ns']==dt for r,dt in zip(frames[1:],intervals)),
        'stage_order_errors':sum(any(r[x]>r[y] for x,y in zip(keys,keys[1:])) for r in frames),
        'select_timeout_event_ids':[r['event_id'] for r in rows if r['select_result']==0],
        'first_frame_event_id':frames[0]['event_id'],
        'select_errors':sum(r['select_result']<0 for r in rows),
        'dq_eagain':sum(r['dq_called'] and r['dq_result']<0 and r['dq_errno']==11 for r in rows),
        'dq_other_errors':sum(r['dq_called'] and r['dq_result']<0 and r['dq_errno']!=11 for r in rows),
        'qbuf_errors':sum(r['qbuf_called'] and r['qbuf_result']!=0 for r in rows),
        'flags':sorted({r['flags'] for r in frames}),
        'buffer_index_counts':dict(collections.Counter(r['buffer_index'] for r in frames)),
        'loop_cpu_percent_single_core':100*sum(r['iteration_cpu_ns'] for r in rows)/wall,
        'select_wait_ms':desc([(r['select_after_ns']-r['select_before_ns'])/1e6 for r in frames]),
        'qbuf_to_next_select_us':desc([(y['select_before_ns']-x['qbuf_end_ns'])/1e3 for x,y in zip(frames,frames[1:])]),
        'dq_ioctl_us':desc([(r['dq_after_ns']-r['dq_ioctl_start_ns'])/1e3 for r in frames]),
        'qbuf_ioctl_us':desc([(r['qbuf_end_ns']-r['qbuf_ioctl_start_ns'])/1e3 for r in frames]),
        'callback_wall_us':desc([(r['callback_end_ns']-r['dq_after_ns'])/1e3 for r in frames]),
        'callback_cpu_us':desc([r['callback_cpu_ns']/1e3 for r in frames]),
        'payload_metadata_invalid':sum(r.get('bytesused',8294400)!=8294400 or (r['flags'] & 64)!=0 for r in frames),
    }

if __name__ == '__main__':
    OUT.mkdir(exist_ok=False)
    inputs = [p for p in B.iterdir() if p.is_file()] + [A/'video_io_events.csv']
    before_hash = {str(p):sha(p) for p in inputs}
    load = lambda name: json.loads((B/name).read_text())
    before,after = load('before_system.json'),load('after_system.json')
    duration = (after['monotonic_ns']-before['monotonic_ns'])/1e9
    def vm(d): return {r.split()[0]:int(r.split()[1]) for r in d['vmstat'].splitlines()}
    v0,v1 = vm(before),vm(after)
    c0,c1 = [list(map(int,d['stat'].splitlines()[0].split()[1:9])) for d in (before,after)]
    dc = [b-a for a,b in zip(c0,c1)]
    def disk(d): return next(list(map(int,r.split()[3:])) for r in d['diskstats'].splitlines() if r.split()[2]=='nvme0n1')
    d0,d1 = disk(before),disk(after)
    a,b = summarize(A),summarize(B)
    auto = load('comparison.json')
    report = {'A_source':str(A),'B_source':str(B),'A':a,'B':b,
        'auto_summary_matches':{key:all(auto[key][k]==v[k] for k in ['frames','events','long_intervals','driver_sequence_missing','fps','video_span_s','interval_ms']) for key,v in [('A',a),('B',b)]},
        'system_snapshot_window_s':duration,
        'system_cpu_percent_all_cores':100*(sum(dc)-dc[3]-dc[4])/sum(dc),
        'system_iowait_percent':100*dc[4]/sum(dc),
        'nvme_total_written_bytes':(d1[6]-d0[6])*512,
        'nvme_average_write_MBps':(d1[6]-d0[6])*512/duration/1e6,
        'vmstat_deltas':{k:v1[k]-v for k,v in v0.items() if k.startswith(('pgscan','pgsteal','allocstall','pswp','pgmajfault','oom_kill'))},
        'kernel_log_unchanged':load('before_kernel.json')==load('after_kernel.json'),
        'usb_tree_unchanged':load('before_usb_tree.json')==load('after_usb_tree.json'),
        'v4l2_settings_unchanged':load('v4l2_before.json')==load('v4l2_after.json'),
        'software_hash_matches_now':{p:sha(pathlib.Path(p))==h for p,h in load('software.json').items()},
        'build_hash_matches_now':{p:sha(pathlib.Path(p))==h for p,h in load('build_manifest.json')['files'].items()},
        'original_inputs_unchanged':all(sha(pathlib.Path(p))==h for p,h in before_hash.items()),
        'input_sha256':before_hash,
        'limits':['No pixel bytes inspected/saved.','No new hardware run.','Snapshot averages cannot resolve transient stalls.','One B run is not an isolated disk-only intervention.']}
    assert report['original_inputs_unchanged']
    (OUT/'independent_review.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'},indent=2))
