"""C5-I-A metadata only. Never substitutes for sensor evidence or strict checks."""
import csv
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

HERE = Path(__file__).resolve().parent
WS = HERE.parents[1]
ROOT = Path('/home/jetson/zed_capture_data')
RUNTIME = HERE / 'runtime'
BUILD = HERE / 'build_continuous_v3'
TERMINAL = {'FINALIZED', 'FAILED', 'CANCELLED_BEFORE_CAPTURE'}

def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()

def process(pid):
    p = Path('/proc') / str(int(pid))
    fields = (p/'stat').read_text().split(') ', 1)[1].split()
    return {'start_ticks': fields[19], 'state': fields[0],
            'argv': (p/'cmdline').read_bytes().split(b'\0')}

def atomic(path, value, durable=False):
    path = Path(path)
    tmp = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('x') as f:
            json.dump(value, f, indent=2, allow_nan=False)
            f.write('\n'); f.flush()
            if durable: os.fsync(f.fileno())
        os.replace(tmp, path)
        if durable:
            fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
    finally:
        if tmp.exists(): tmp.unlink()  # only our uncommitted temporary file

def load(path, default=None):
    try:
        p=Path(path)
        if p.stat().st_size > 1024*1024: raise ValueError('metadata exceeds 1 MiB: '+str(p))
        return json.loads(p.read_text())
    except FileNotFoundError:
        if default is not None: return default
        raise

def identity(session):
    session = Path(session).resolve(strict=True)
    m = load(session/'field_identity.json')
    if m['session_id'] != session.name or m['session_dir'] != str(session):
        raise ValueError('session identity/path mismatch')
    if len(m['token']) != 32 or not all(c in '0123456789abcdef' for c in m['token']):
        raise ValueError('invalid control token')
    return m

def manager_alive(m):
    if m.get('boot_id') != boot_id(): return False
    # Reservation is persisted before Popen. Until the child publishes its
    # identity these two fields are deliberately null, not a usable PID.
    pid = m.get('manager_pid')
    ticks = m.get('manager_start_ticks')
    if type(pid) is not int or pid <= 0: return False
    if not isinstance(ticks, (str, int)) or isinstance(ticks, bool) or not str(ticks).isdigit(): return False
    try:
        p = process(pid)
        return (p['state'] != 'Z' and p['start_ticks'] == str(m['manager_start_ticks'])
                and str(HERE/'field_capture.py').encode() in p['argv']
                and b'_manager' in p['argv'] and m['session_dir'].encode() in p['argv'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError): return False

def stop_requested(session):
    r = load(Path(session)/'field_stop_request.json', {})
    if not r: return False
    m = identity(session)
    if any(r.get(k) != m[k] for k in ('session_id', 'token', 'boot_id')):
        raise ValueError('stop request identity mismatch')
    return True

def request_stop(session, reason='USER_STOP'):
    session = Path(session); m = identity(session)
    s = load(session/'capture_status.json', {})
    if s.get('state') in TERMINAL:
        return 'ALREADY_'+s['state']
    if not manager_alive(m):
        raise RuntimeError('MANAGER_LOST_OR_PID_REUSED: no signal sent; inspect owned processes and data')
    if stop_requested(session): return 'STOP_ALREADY_REQUESTED'
    atomic(session/'field_stop_request.json', {
        **{k:m[k] for k in ('session_id','token','boot_id')},
        'requested_monotonic_ns':time.monotonic_ns(), 'reason':reason}, True)
    return 'STOP_REQUESTED'

def tail_json(path, budget=65536):
    """Bounded tail of complete small JSONL rows; never scan full history."""
    try:
        with Path(path).open('rb') as f:
            end=f.seek(0,2); start=max(0,end-budget); f.seek(start); data=f.read(budget)
        rows=data.split(b'\n')[:-1]
        if start: rows=rows[1:]
        for row in reversed(rows):
            if row: return json.loads(row)
    except FileNotFoundError: pass
    return {}

class FrameCounter:
    """Incremental index observation, bounded 256 KiB per tick, 64 KiB line limit.
    Counts refer to terminal index rows; in-flight encodes are deliberately unknown.
    """
    def __init__(self):
        self.offset=0; self.pending=b''; self.header=None
        self.encoded=self.written=self.errors=self.rows=0
        self.backlog=False
    def update(self, path):
        try:
            with Path(path).open('rb') as f:
                if f.seek(0,2)<self.offset: raise ValueError('frames.csv shrank')
                f.seek(self.offset); chunk=f.read(262144); self.offset+=len(chunk)
                self.backlog=f.read(1)!=b''
        except FileNotFoundError: return
        rows=(self.pending+chunk).split(b'\n'); self.pending=rows.pop()
        if len(self.pending)>65536: raise ValueError('frames.csv oversized partial row')
        for line in rows:
            if len(line)>65536: raise ValueError('frames.csv oversized row')
            values=next(csv.reader([line.decode()]))
            if self.header is None: self.header=values; continue
            if len(values)!=len(self.header): raise ValueError('frames.csv malformed row')
            r=dict(zip(self.header,values)); self.rows+=1
            self.encoded+=int(r['encoding_status']=='ENCODED_420')
            self.written+=int(r['status']=='WRITTEN' and r['left_ok']=='1' and r['right_ok']=='1')
            self.errors+=int(r['status']!='WRITTEN')

def finalized_evidence(session, gnss_enabled=True):
    """Cheap close/sync attestation, NOT validation of contents or SHA256."""
    p=Path(session); m=load(p/'session.json'); c=load(p/'capture_summary.json',{})
    j=load(p/'jpeg_files_summary.json',{}); g=load(p/'gnss/summary.json',{}) if gnss_enabled else {}
    gw=load(p/'gnss_writer_summary.json',{}) if gnss_enabled else {}
    if m.get('session_id')!=p.name: raise ValueError('manifest identity mismatch')
    bag = c.get('bag_finalized') is True and (p/'sensors.bag').is_file() and not any(p.glob('*.active'))
    if (p/'bag_segments.jsonl').exists():
        from segment_check import attest
        bag = bag and attest(p)['closed']
    jpeg = j.get('final_synced') is True and j.get('workers_joined') is True and not j.get('sync_error')
    gnss = not gnss_enabled or (g.get('session')==p.name and g.get('boot_id')==m.get('boot_id')
        and g.get('status')=='RAW_RECEPTION_RECORDED' and not g.get('errors')
        and gw.get('complete') is True and (p/'gnss/done').is_file() and (p/'gnss/ack').is_file()
        and (p/'gnss/serial_raw.bin').stat().st_size==g.get('raw_bytes'))
    return {'BAG_FINALIZED':bool(bag), 'JPEG_FINAL_SYNCED':bool(jpeg),
            'GNSS_FINAL_SYNCED':bool(gnss) if gnss_enabled else 'NOT_ENABLED',
            'FINALIZATION_STATUS':'FINALIZED' if bag and jpeg and gnss else 'FAILED',
            'capture_failed':c.get('failed'), 'jpeg_failed':j.get('failed'),
            'GNSS_MEASUREMENT_MAPPING':'PENDING', 'PHYSICAL_SYNC':'PENDING',
            'FULL_STRICT_CHECK':'PENDING','DATA_INTEGRITY':'PENDING',
            'method':'producer final-close reports and file presence/size; no full data inspection'}

def verify_frozen():
    baseline=Path((HERE/'baseline_path.txt').read_text().strip())
    hashes=load(baseline/'hashes_before.json')
    changed=[name for name,h in hashes.items() if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=h]
    if changed: raise RuntimeError('Frozen baseline changed; refuse unreviewed field launch: '+repr(changed))
    return hashes
