#!/usr/bin/env python3
"""Receive-only GNSS audit; no ROS master, fusion, PPS or receiver commands.
Legacy parser reused unchanged. Independent modem setup follows exclusive_serial.py,
with TIOCEXCL acquired BEFORE changing line settings. Evidence is not PPS timing.
"""
import argparse, collections, dataclasses, errno, fcntl, hashlib, json, math, os
import pathlib, select, signal, struct, subprocess, termios, time, tty, uuid
from gnss_serial_driver.parser import GnssParser
from gnss_serial_driver.exclusive_serial import BAUD
PORT='/dev/serial/by-id/usb-STMicroelectronics_STM32_Virtual_ComPort_5CF253593333-if00'
ROOT=pathlib.Path(__file__).resolve().parent

def clock_sample():
    before=time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    mono=time.monotonic_ns(); real=time.time_ns()
    after=time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    return dict(raw_before_ns=before,monotonic_ns=mono,realtime_ns=real,
                raw_after_ns=after,raw_bracket_ns=after-before)

def clean(obj):
    if isinstance(obj,float) and not math.isfinite(obj): return None
    if isinstance(obj,dict):return {k:clean(v) for k,v in obj.items()}
    if isinstance(obj,list):return [clean(v) for v in obj]
    return obj

def emit(stream,value):
    stream.write(json.dumps(clean(value),ensure_ascii=False,allow_nan=False)+'\n')

def identity(port):
    p=pathlib.Path(port)
    if not p.exists():raise RuntimeError('DEVICE_NODE_UNAVAILABLE: '+port)
    node=p.resolve();sys=pathlib.Path('/sys/class/tty')/node.name/'device'
    for parent in [sys.resolve()]+list(sys.resolve().parents):
        if (parent/'idVendor').exists():
            info={k:(parent/k).read_text().strip() for k in ['idVendor','idProduct','serial']}
            if info!={'idVendor':'0483','idProduct':'5740','serial':'5CF253593333'}:
                raise RuntimeError('DEVICE_IDENTITY_MISMATCH '+repr(info))
            return dict(info,node=str(node),sysfs=str(parent))
    raise RuntimeError('USB_IDENTITY_UNAVAILABLE')

def open_checked(port):
    # fuser detects existing non-cooperating readers; locks prevent further opens.
    x=subprocess.run(['fuser',str(pathlib.Path(port).resolve())],capture_output=True,text=True)
    if x.returncode!=1 or x.stdout.strip():raise RuntimeError('SERIAL_BUSY_OR_OWNERSHIP_UNKNOWN: '+x.stdout+x.stderr)
    fd=os.open(port,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.ioctl(fd,termios.TIOCEXCL)
        tty.setraw(fd)
        a=termios.tcgetattr(fd);a[4]=a[5]=BAUD[921600]
        a[2]&=~getattr(termios,'CRTSCTS',0)
        a[6][termios.VMIN]=0;a[6][termios.VTIME]=1
        termios.tcsetattr(fd,termios.TCSANOW,a)
        bits=struct.unpack('I',fcntl.ioctl(fd,termios.TIOCMGET,struct.pack('I',0)))[0]
        bits=(bits|termios.TIOCM_DTR)&~termios.TIOCM_RTS
        fcntl.ioctl(fd,termios.TIOCMSET,struct.pack('I',bits))
        actual=termios.tcgetattr(fd)
        bits=struct.unpack('I',fcntl.ioctl(fd,termios.TIOCMGET,struct.pack('I',0)))[0]
        if actual[4]!=BAUD[921600] or actual[5]!=BAUD[921600] or not bits&termios.TIOCM_DTR or bits&termios.TIOCM_RTS:
            raise RuntimeError('SERIAL_SETTINGS_READBACK_MISMATCH')
        return fd,dict(baud=921600,dtr=True,rts=False,readback_verified=True,exclusive='flock+TIOCEXCL')
    except BaseException:
        os.close(fd);raise

class Decoder:
    def __init__(self,stream):
        self.stream=stream;self.parser=GnssParser();self.buf=bytearray();self.overflow=False
        self.offset=0;self.start=0;self.line=0;self.counts=collections.Counter()
        self.sources=collections.Counter();self.quality=collections.Counter();self.last_utc={}
    def discontinuity(self,reason):
        if self.buf or self.overflow:
            emit(self.stream,dict(event='INCOMPLETE_LINE',reason=reason,byte_begin=self.start,byte_end=self.offset))
            self.counts['incomplete_lines']+=1
        self.buf.clear();self.overflow=False;self.start=self.offset;self.parser=GnssParser()
    def feed(self,data,chunk_id,clock):
        for b in data:
            self.offset+=1
            if b in (10,13):
                if self.buf and not self.overflow:self.record(bytes(self.buf),chunk_id,clock,self.start,self.offset)
                self.buf.clear();self.overflow=False;self.start=self.offset
            elif not self.overflow:
                if len(self.buf)>=8192:
                    self.buf.clear();self.overflow=True;self.counts['oversize_lines']+=1
                    emit(self.stream,dict(event='OVERSIZE_LINE',byte_begin=self.start,chunk_id=chunk_id))
                else:self.buf.append(b)
    def record(self,data,chunk,clock,begin,end):
        self.line+=1;line=data.decode('ascii',errors='replace').strip()
        self.counts['lines']+=1
        try:parsed=self.parser.parse(line);error=None
        except Exception as e:parsed=[];error=repr(e);self.counts['parser_exceptions']+=1
        if not parsed:self.counts['no_parsed_records']+=1
        out=[]
        for p in parsed:
            value=dataclasses.asdict(p);self.sources[p.source]+=1;self.quality[p.source+':'+str(p.quality)]+=1
            # Do not equate the legacy bool with verified AGRICA/JSON checksums.
            checksum='UNKNOWN_NOT_VERIFIED_BY_LEGACY' if p.source in ('AGRICA','LEGACY_IMUGNSS_JSON') else ('PASS' if p.checksum_valid else 'FAIL')
            self.counts['checksum_'+checksum]+=1;self.counts['parse_reason_'+p.reject_reason]+=1
            self.counts['position_valid']+=int(p.position_valid)
            if p.utc_valid:
                prev=self.last_utc.get(p.source)
                if prev is not None:
                    self.counts['utc_backwards_'+p.source]+=int(p.utc_ns<prev)
                    self.counts['utc_duplicate_'+p.source]+=int(p.utc_ns==prev)
                self.last_utc[p.source]=p.utc_ns
            value.update(checksum_audit=checksum,utc_semantics='legacy parser result; original text preserved; not a receive timestamp',
                         mapping_valid=False,mapping_version=0,mapping_uncertainty_ns=None,physical_sync='PENDING')
            out.append(value)
        emit(self.stream,dict(line_id=self.line,chunk_id=chunk,byte_begin=begin,byte_end=end,
            raw_line_hex=data.hex(),receive_clocks=clock,parsed=out,parser_exception=error,
            receive_semantics='clocks sampled after os.read returning the line terminator; not PPS/first byte/measurement epoch'))

def run(duration,port):
    if os.geteuid()==0:raise RuntimeError('Do not run as root')
    if not 1<=duration<=60:raise ValueError('duration must be 1..60 seconds')
    out=ROOT/'runs'/('independent_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True,exist_ok=False)
    print('GNSS_DIR='+str(out),flush=True)
    stop=[False]
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.__setitem__(0,True))
    summary=dict(status='PENDING',synthetic=False,port=port,requested_duration_s=duration,
                 mapping_status='UNMAPPED',mapping_version=0,mapping_uncertainty_ns=None,
                 physical_sync='PENDING',reconnects=0,errors=[],boot_id=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    fd=None;decoder=None;streams=[]
    try:
        summary['identity']=identity(port)
        raw=(out/'serial_raw.bin').open('xb');lines=(out/'lines.jsonl').open('x');chunks=(out/'chunks.jsonl').open('x');streams=[raw,lines,chunks]
        decoder=Decoder(lines);fd,summary['settings']=open_checked(port)
        end=time.monotonic()+duration;chunk_id=0;last=None;lastreal=None
        summary['host_clock_backwards']=0;summary['realtime_backwards']=0
        while not stop[0] and time.monotonic()<end:
            if not select.select([fd],[],[],min(.2,max(0,end-time.monotonic())))[0]:continue
            before=time.monotonic_ns()
            try:
                data=os.read(fd,4096)
                if not data:raise OSError(errno.ENODEV,'serial EOF/disconnected')
            except BlockingIOError:continue
            except OSError as e:
                summary['errors'].append(repr(e));emit(chunks,dict(event='DISCONNECT',clock=clock_sample(),error=repr(e)))
                decoder.discontinuity('DISCONNECT');os.close(fd);fd=None
                if summary['reconnects']>=2:raise RuntimeError('RECONNECT_LIMIT')
                time.sleep(1);summary['identity']=identity(port);fd,summary['settings']=open_checked(port);summary['reconnects']+=1
                emit(chunks,dict(event='RECONNECTED',clock=clock_sample()));continue
            clock=clock_sample();chunk_id+=1;offset=raw.tell();raw.write(data)
            emit(chunks,dict(chunk_id=chunk_id,byte_offset=offset,byte_count=len(data),read_before_monotonic_ns=before,receive_clocks=clock))
            if last is not None:summary['host_clock_backwards']+=int(clock['monotonic_ns']<last)
            if lastreal is not None:summary['realtime_backwards']+=int(clock['realtime_ns']<lastreal)
            last=clock['monotonic_ns'];lastreal=clock['realtime_ns']
            decoder.feed(data,chunk_id,clock)
        decoder.discontinuity('END_OF_TEST')
        summary.update(chunks=chunk_id,raw_bytes=raw.tell(),interrupted=stop[0],counts=dict(decoder.counts),
                       protocol_distribution=dict(decoder.sources),legacy_quality_distribution=dict(decoder.quality))
        summary['status']='RAW_RECEPTION_OBSERVED' if chunk_id and not stop[0] else 'FAIL_OR_INTERRUPTED'
        summary['protocol_acceptance']='REVIEW_REQUIRED; raw reception is not checksum/RTK/time acceptance'
    except Exception as e:
        summary['status']='BLOCKED_OR_FAILED';summary['errors'].append(repr(e))
        if decoder:summary['counts']=dict(decoder.counts)
    finally:
        if fd is not None:os.close(fd)
        for stream in streams:stream.flush();os.fsync(stream.fileno());stream.close()
        with (out/'summary.json').open('x') as f:json.dump(summary,f,indent=2)
    print(json.dumps(summary,indent=2));return 0 if summary['status']=='RAW_RECEPTION_OBSERVED' else 2

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--duration',type=float,default=15);args=a.parse_args()
    raise SystemExit(run(args.duration,PORT))
