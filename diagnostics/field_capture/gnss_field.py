#!/usr/bin/env python3
"""One exclusive receive-only serial process; no bag writer, no fusion/mapping.
Raw bytes and chunk metadata are persisted before parsing/publishing. A bounded
ROS transport is reconciled against production writer counts during shutdown.
"""
import argparse,fcntl,hashlib,json,os,pathlib,select,signal,struct,subprocess,sys,termios,time,tty
sys.path.insert(0,'/home/jetson/zed_capture_ws/diagnostics/gnss_r2')
from gnss_r2_core import PORT,TOPICS,Stream,emit,message_types,messages

def clock_sample():
    before=time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    mono=time.monotonic_ns();real=time.time_ns();after=time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    return dict(raw_before_ns=before,monotonic_ns=mono,realtime_ns=real,raw_after_ns=after,raw_bracket_ns=after-before)

def identity(port):
    p=pathlib.Path(port)
    if not p.exists():raise RuntimeError('GNSS device unavailable (sandbox/permissions/disconnected): '+port)
    node=p.resolve();entry=(pathlib.Path('/sys/class/tty')/node.name/'device').resolve()
    for parent in (entry,*entry.parents):
        if (parent/'idVendor').exists():
            result={k:(parent/k).read_text().strip() for k in ('idVendor','idProduct','serial')}
            if result!={'idVendor':'0483','idProduct':'5740','serial':'5CF253593333'}:raise RuntimeError('GNSS USB identity mismatch: '+repr(result))
            return dict(result,node=str(node),sysfs=str(parent))
    raise RuntimeError('GNSS USB identity unavailable')

def open_checked(port):
    before=identity(port)
    check=subprocess.run(['fuser',before['node']],capture_output=True,text=True)
    if check.returncode!=1 or check.stdout.strip():raise RuntimeError('GNSS serial busy or ownership unknown: '+check.stdout+check.stderr)
    fd=os.open(port,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK|os.O_CLOEXEC)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.ioctl(fd,termios.TIOCEXCL)
        # TCSANOW avoids tty.setraw default TCSAFLUSH, which would discard input.
        tty.setraw(fd,termios.TCSANOW);a=termios.tcgetattr(fd);a[4]=a[5]=termios.B921600
        a[2]&=~getattr(termios,'CRTSCTS',0);a[6][termios.VMIN]=0;a[6][termios.VTIME]=0
        termios.tcsetattr(fd,termios.TCSANOW,a)
        bits=struct.unpack('I',fcntl.ioctl(fd,termios.TIOCMGET,struct.pack('I',0)))[0]
        fcntl.ioctl(fd,termios.TIOCMSET,struct.pack('I',(bits|termios.TIOCM_DTR)&~termios.TIOCM_RTS))
        a=termios.tcgetattr(fd);bits=struct.unpack('I',fcntl.ioctl(fd,termios.TIOCMGET,struct.pack('I',0)))[0]
        if a[4]!=termios.B921600 or a[5]!=termios.B921600 or not bits&termios.TIOCM_DTR or bits&termios.TIOCM_RTS:raise RuntimeError('GNSS serial readback mismatch')
        if identity(port)!=before:raise RuntimeError('GNSS identity changed during open')
        return fd,before
    except BaseException:os.close(fd);raise

def write_all(f,data):
    view=memoryview(data)
    while view:
        n=f.write(view)
        if not n:raise OSError('GNSS raw short write/no progress')
        view=view[n:]

class Evidence:
    def __init__(self,out,session_id,epoch,publish,sync_period=0):
        self.out=out;out.mkdir(exist_ok=False);self.session_id=session_id;self.epoch=epoch;self.publish=publish
        self.raw=(out/'serial_raw.bin').open('xb',buffering=0)
        self.chunks=(out/'chunks.jsonl').open('x');self.lines=(out/'lines.jsonl').open('x');self.times=(out/'time_observations.jsonl').open('x');self.publication_events=(out/'publication_events.jsonl').open('x')
        self.stream=Stream(self.record);self.chunk_id=0;self.bytes=0;self.digest=hashlib.sha256();self.published=[0]*5;self.publication_errors=[0]*5;self.serialization_errors=[0]*5
        self.clock_errors=0;self.last_clock=None;self.serial_open=True
        self.sync_period=sync_period;self.last_sync=time.monotonic();self.sync_count=0
        self.sync_log=(out/'sync_checkpoints.jsonl').open('x') if sync_period else None
    def checkpoint(self):
        before=time.monotonic_ns()
        for f in (self.raw,self.chunks,self.lines,self.times,self.publication_events):f.flush();os.fsync(f.fileno())
        emit(self.sync_log,dict(monotonic_ns=time.monotonic_ns(),sync_begin_ns=before,raw_bytes=self.bytes,
            chunks=self.chunk_id,published={t[0]:n for t,n in zip(TOPICS,self.published)},raw_sha256_prefix=self.digest.hexdigest()))
        self.sync_log.flush();os.fsync(self.sync_log.fileno());self.sync_count+=1;self.last_sync=time.monotonic()
    def record(self,row):
        row.update(session_id=self.session_id,writer_epoch=self.epoch,serial_open=self.serial_open)
        emit(self.lines,row)
        emit(self.times,dict(
            source_sequence=row['source_sequence'],record_sequence=row['record_sequence'],receive_clocks=row['receive_clocks'],
            utc_measurement_ns=row['parsed']['utc_measurement_ns'],utc_candidate_ns=row['parsed']['utc_candidate_ns'],
            utc_valid=row['parsed']['utc_valid'],raw_time_fields=row['parsed']['time_fields'],
            utc_delta_ns=row['utc_delta_ns'],measurement_to_mid_mapping='PENDING',local_measurement_time_valid=False,
            valid_for_fusion=False,mapping_version=0,mapping_uncertainty_ns=None))
        for index,msg in messages(row,self.session_id,self.epoch):
            try:self.publish(index,msg);self.published[index]+=1
            except Exception as error:
                self.publication_errors[index]+=1
                self.serialization_errors[index]+=int('serializ' in type(error).__name__.lower())
                emit(self.publication_events,dict(topic=TOPICS[index][0],source_sequence=row['source_sequence'],record_sequence=row['record_sequence'],error=repr(error),exception_type=type(error).__name__))
                raise
    def feed(self,data,clock,read_before=None):
        if len(data)>4096:raise ValueError('read chunk exceeds 4096-byte bound')
        write_all(self.raw,data);self.digest.update(data);self.chunk_id+=1
        emit(self.chunks,dict(chunk_id=self.chunk_id,byte_offset=self.bytes,byte_count=len(data),
            read_before_monotonic_ns=read_before,receive_clocks=clock))
        self.bytes+=len(data)
        if self.last_clock:
            self.clock_errors+=int(clock['monotonic_ns']<self.last_clock['monotonic_ns'] or clock['raw_before_ns']<self.last_clock['raw_before_ns'])
        self.last_clock=clock
        # Flush these small records before potentially failing parser/publisher.
        self.chunks.flush();self.stream.feed(data,self.chunk_id,clock)
        if self.sync_log and time.monotonic()-self.last_sync>=self.sync_period:self.checkpoint()
    def close(self,reason):
        error=None
        try:self.stream.finish(reason)
        except Exception as e:error=e
        if self.sync_log:
            try:self.checkpoint()
            except Exception as e:error=error or e
        for f in (self.raw,self.chunks,self.lines,self.times,self.publication_events)+((self.sync_log,) if self.sync_log else ()):
            try:f.flush();os.fsync(f.fileno());f.close()
            except Exception as e:error=error or e
        if error:raise error
    def summary(self):
        return dict(raw_bytes=self.bytes,raw_sha256=self.digest.hexdigest(),chunks=self.chunk_id,
            published={t[0]:n for t,n in zip(TOPICS,self.published)},
            publication_errors={t[0]:n for t,n in zip(TOPICS,self.publication_errors)},
            serialization_errors={t[0]:n for t,n in zip(TOPICS,self.serialization_errors)},counts=dict(self.stream.counts),
            protocols=dict(self.stream.protocols),quality=dict(self.stream.quality),host_clock_errors=self.clock_errors,
            parse_reason_distribution=dict(self.stream.parse_reasons),time_reason_distribution=dict(self.stream.time_reasons),
            mapping_status='PENDING',mapping_version=0,mapping_uncertainty_ns=None,physical_sync='PENDING')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--session',required=True);args=ap.parse_args()
    session=pathlib.Path(args.session).resolve(strict=True);manifest=json.loads((session/'session.json').read_text())
    if not manifest['config'].get('gnss_enable',False):raise RuntimeError('GNSS not explicitly enabled')
    if os.geteuid()==0:raise RuntimeError('Do not run capture as root')
    import rospy
    rospy.init_node('gnss_r2_'+session.name,anonymous=False,disable_signals=True)
    publishers=[rospy.Publisher(t[0],m,queue_size=128) for t,m in zip(TOPICS,message_types())]
    stop=[False]
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.__setitem__(0,True))
    session_id=int.from_bytes(hashlib.sha256(session.name.encode()).digest()[:8],'big');epoch=time.monotonic_ns()
    sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
    from field_policy import validate as long_validate,guard_seconds
    duration=manifest.get('duration_requested_s',30)
    long_mode=long_validate(manifest['config'],duration)
    evidence=Evidence(session/'gnss',session_id,epoch,lambda i,m:publishers[i].publish(m),sync_period=5 if long_mode else 0)
    summary=dict(session=session.name,boot_id=manifest['boot_id'],session_id=session_id,writer_epoch=epoch,
        synthetic=bool(manifest.get('synthetic_fixture',False)),baud=921600,dtr=True,rts=False,errors=[],serial_opened=False,
        raw_ros_header_clock='HOST_REALTIME_RECEPTION',pvt_local_header='INVALID_ZERO',
        uncertainty='UNKNOWN; zero numeric ROS fields require invalid flags; not zero uncertainty')
    fd=None
    try:
        deadline=time.monotonic()+15
        while not all(p.get_num_connections() for p in publishers):
            if stop[0] or rospy.is_shutdown() or time.monotonic()>deadline:raise RuntimeError('GNSS writer subscriber readiness timeout')
            time.sleep(.02)
        fd,summary['identity']=open_checked(PORT);summary['serial_opened']=True
        last=time.monotonic();deadline=last+guard_seconds(manifest['config'],duration)
        while not (session/'gnss/stop').exists():
            if stop[0] or rospy.is_shutdown():raise RuntimeError('GNSS interrupted before recording stop handshake')
            if time.monotonic()>deadline:raise RuntimeError('GNSS session exceeded duration-specific bounded guard')
            if time.monotonic()-last>3:raise RuntimeError('GNSS serial has no bytes for 3 seconds')
            if not select.select([fd],[],[],.05)[0]:continue
            before=time.monotonic_ns()
            try:data=os.read(fd,4096)
            except BlockingIOError:continue
            if not data:raise RuntimeError('GNSS serial disconnected/EOF')
            evidence.feed(data,clock_sample(),before);last=time.monotonic()
    except Exception as e:summary['errors'].append(repr(e))
    finally:
        if fd is not None:os.close(fd)
        evidence.serial_open=False
        try:evidence.close('DISCONNECT_OR_ERROR' if summary['errors'] else 'SESSION_END')
        except Exception as e:summary['errors'].append('persistence/finalization: '+repr(e))
        summary.update(evidence.summary());summary['status']='FAIL' if summary['errors'] or not evidence.bytes else 'RAW_RECEPTION_RECORDED'
        try:
            with (session/'gnss/summary.json').open('x') as f:json.dump(summary,f,indent=2);f.flush();os.fsync(f.fileno())
            with (session/'gnss/done.tmp').open('x') as f:
                f.write(('1' if summary['status']=='FAIL' else '0')+' '+' '.join(map(str,evidence.published))+'\n');f.flush();os.fsync(f.fileno())
            os.rename(session/'gnss/done.tmp',session/'gnss/done')
            dfd=os.open(str(session/'gnss'),os.O_RDONLY|os.O_DIRECTORY);os.fsync(dfd);os.close(dfd)
        except Exception as e:print('GNSS finalization failed: '+repr(e),file=sys.stderr);return 2
    # Keep publishers alive until subscriber confirms all queued sends arrived.
    deadline=time.monotonic()+12
    while not (session/'gnss/ack').exists() and time.monotonic()<deadline and not rospy.is_shutdown():time.sleep(.02)
    if not (session/'gnss/ack').exists():print('GNSS acknowledgement missing',file=sys.stderr);return 2
    return 0 if summary['status']!='FAIL' else 2
if __name__=='__main__':sys.exit(main())
