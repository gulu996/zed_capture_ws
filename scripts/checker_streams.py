"""Streaming equivalents of the existing strict offline checks; same thresholds."""
import collections,csv,hashlib,json,pathlib,statistics
import numpy as np
from checker_store import Store,Index,Numbers,stats,equal

def json_rows(p):
 with pathlib.Path(p).open() as f:
  while True:
   line=f.readline(1048577)
   if not line:break
   if len(line)>1048576:raise ValueError('FULL_STRICT JSONL row memory budget exceeded')
   if line.strip():yield json.loads(line)
def csv_rows(p,integer=False):
 with pathlib.Path(p).open() as f:
  for r in csv.DictReader(f):
   if None in r or any(v is None for v in r.values()):raise ValueError('incomplete CSV row: '+pathlib.Path(p).name)
   yield {k:(ord(v) if v in ('\x00','\x01') else int(v)) for k,v in r.items()} if integer else r

def decode_eye(args):
 from jpeg_file_check import sof,cv2
 session,r,pair,eye=args
 expected=f'camera/{eye}/{(pair-1)//1000:06d}/{pair:012d}.jpg'
 if r[eye+'_path']!=expected:raise ValueError('unsafe/unexpected image path')
 p=(session/expected).resolve()
 if session.resolve() not in p.parents:raise ValueError('path escapes session')
 data=p.read_bytes()
 if len(data)!=int(r[eye+'_bytes']) or not data.endswith(b'\xff\xd9'):raise ValueError('truncated JPEG '+str(pair))
 info=sof(data)
 if not info['is_420'] or (info['width'],info['height'])!=(1280,720):raise ValueError('JPEG SOF mismatch')
 image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
 if image is None or image.shape!=(720,1280,3):raise ValueError('JPEG decode failed')
 del image
 seq=int(r[eye+'_seq']);ns=int(r[eye+'_sec'])*10**9+int(r[eye+'_nsec'])
 if seq!=int(r['sequence']) or ns!=int(r['raw_ns']):raise ValueError('Header changed')
 if not r[eye+'_frame_id']:raise ValueError('missing frame_id')
 return eye,(seq,ns),hashlib.sha256(data).hexdigest()

def file_audit(session,store):
 from jpeg_file_check import sof,cv2
 from concurrent.futures import ThreadPoolExecutor
 pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='full_jpeg')
 session=pathlib.Path(session);errors=[];keys={k:store.seq() for k in ('left','right')};rows=store.seq();verified=store.seq()
 try:
  meta=Index(store);seen=Index(store);paths=Index(store);observed=Index(store)
  for r in csv_rows(session/'frames.csv'):rows.append(r)
  for r in csv_rows(session/'video_timestamps.csv'):meta.put(int(r['pair_id']),r)
  for r in rows:
   pair=int(r['pair_id']);m=meta.get(pair)
   if not seen.add(pair):raise ValueError('duplicate pair_id')
   if not m:raise ValueError('index pair absent in raw video sidecar')
   if any(r[k]!=m[k] for k in ['raw_ns','sequence','flags','timestamp_type','timestamp_source']):raise ValueError('index raw metadata mismatch')
   if int(r['raw_ns'])!=int(r['v4l2_sec'])*10**9+int(r['v4l2_usec'])*1000:raise ValueError('raw integer timestamp mismatch')
   if r['clock_domain']!='CLOCK_MONOTONIC' or int(r['timestamp_type'])!=8192:raise ValueError('unverified timestamp domain')
   if (int(r['width']),int(r['height']),int(r['quality']),r['subsampling'])!=(1280,720,95,'420'):raise ValueError('mode mismatch')
   if r.get('encoding_status')!='ENCODED_420' or r.get('write_status')!=r['status']:errors.append('encoding/write status mismatch for '+str(pair))
   if r['status']!='WRITTEN' or r['left_ok']!='1' or r['right_ok']!='1':errors.append('incomplete pair '+str(pair)+': '+r['status']);continue
   item={'pair_id':pair,'raw_ns':int(r['raw_ns'])}
   # Exactly two in-flight JPEG decodes, never an unbounded executor.map queue.
   futures=[pool.submit(decode_eye,(session,r,pair,eye)) for eye in ['left','right']]
   for future in futures:
    eye,key,digest=future.result();item[eye+'_sha256']=digest;keys[eye].append(key)
   verified.append(item)
  for r in rows:
   for eye in ['left','right']:
    if r[eye+'_path']:paths.add(r[eye+'_path'])
  for p in (session/'camera').rglob('*.jpg'):observed.add(str(p.relative_to(session)))
  if not paths.same_keys(observed):errors.append('index/file path set differs (partial/orphan files retained)')
  if not seen.same_keys(meta):errors.append('frames index/video pair set differs')
  s=json.loads((session/'jpeg_files_summary.json').read_text())
  if s['failed'] or not s['final_synced'] or not s['workers_joined']:errors.append('JPEG pipeline failed or not durably finalized')
  if s['inputs']!=len(rows) or s['completed']!=len(verified):errors.append('JPEG summary count mismatch')
 except Exception as e:errors.append(str(e))
 finally:pool.shutdown(wait=True)
 return {'status':'PASS' if not errors and rows else 'FAIL','errors':errors,'keys':keys,'frames':rows,'verified':verified,'note':'WRITTEN means both files closed; durable acceptance additionally requires final_synced; power loss can lose unsynced batch.'}

def resources(session):
 p=session/'resources.jsonl'
 if not p.exists():return {'status':'PENDING'}
 peak_cpu=0.;peak_rss=0;peak_write=0.;peak_dirty=0;system_cpu=None;gpu=None;previous={};first=None;old=None;n=0
 for row in json_rows(p):
  n+=1
  if first is None:first=row
  cpu=0;rss=0;write=0
  for pid,v in row['pids'].items():
   rss+=v['rss_bytes']
   if pid in previous:
    prev,t=previous[pid];dt=(row['monotonic_ns']-t)/1e9
    if dt>0:cpu+=(v['cpu_ticks']-prev['cpu_ticks'])/row['clock_ticks_per_second']/dt*100;write+=(v['write_bytes']-prev['write_bytes'])/dt/1e6
   previous[pid]=(v,row['monotonic_ns'])
  # Number of owned processes is small; fail closed rather than unbounded churn.
  if len(previous)>4096:raise ValueError('resource PID budget exceeded')
  peak_cpu=max(peak_cpu,cpu);peak_rss=max(peak_rss,rss);peak_write=max(peak_write,write);peak_dirty=max(peak_dirty,row.get('meminfo_kb',{}).get('Dirty',0))
  if old and 'system_cpu_ticks' in old and 'system_cpu_ticks' in row:
   d=[b-a for a,b in zip(old['system_cpu_ticks'],row['system_cpu_ticks'])]
   if sum(d)>0:system_cpu=max(system_cpu if system_cpu is not None else -float('inf'),100*(1-(d[3]+d[4])/sum(d)))
  if 'gpu_load_raw_0_to_1000' in row:gpu=max(gpu if gpu is not None else -float('inf'),row['gpu_load_raw_0_to_1000']/10)
  old=row
 if n<2:return {'status':'PENDING'}
 dt=(old['monotonic_ns']-first['monotonic_ns'])/1e9
 return {'status':'OBSERVED','children_peak_cpu_percent_one_core_100':peak_cpu,'children_peak_rss_mb':peak_rss/1e6,'system_peak_cpu_percent':system_cpu,'gpu_peak_load_percent':gpu,'peak_block_write_MBps':peak_write,'bag_growth_MBps':(old['bag_bytes']-first['bag_bytes'])/1e6/dt,'peak_dirty_mb':peak_dirty/1024,'note':'block writes may lag due to page cache; capture node fsyncs the closed bag; reused Livox process is not included in owned-child CPU figures'}

def timing_evidence(session):
 session=pathlib.Path(session);p=session/'video_timing.csv'
 if not p.exists():return {'status':'NOT_RECORDED_IN_ORIGINAL_SESSION'}
 fields={'select_wait_ms':('poll_after_ns','poll_before_ns'),'dq_to_callback_end_ms':('callback_end_ns','dq_after_ns'),'callback_end_to_qbuf_ms':('qbuf_end_ns','callback_end_ns')};a={k:Numbers('d') for k in list(fields)+['callback_cpu_ms','callback_wall_minus_cpu_ms']};n=0;bad=0
 for r in csv_rows(p,True):
  n+=1;bad+=r['qbuf_result']!=0
  for k,(end,begin) in fields.items():a[k].append((r[end]-r[begin])/1e6)
  a['callback_cpu_ms'].append(r['callback_cpu_ns']/1e6);a['callback_wall_minus_cpu_ms'].append(max(0,r['callback_end_ns']-r['dq_after_ns']-r['callback_cpu_ns'])/1e6)
 result={'status':'OBSERVED','timing_rows':n,'qbuf_errors':bad,**{k:stats(v) for k,v in a.items()},'note':'wall-minus-thread-CPU includes blocking/preemption and instrumentation boundaries; select wait is not pure scheduler latency'}
 fields={'copy_ms':('copied_ns','copy_begin_ns'),'writer_queue_wait_ms':('writer_begin_ns','copied_ns'),'writer_video_job_ms':('writer_end_ns','writer_begin_ns')};a={k:Numbers('d') for k in fields};first=True;available={}
 for r in csv_rows(session/'video_timestamps.csv',True):
  if first:available={k:e in r for k,(e,b) in fields.items()};first=False
  for k,(end,begin) in fields.items():
   if available[k]:a[k].append((r[end]-r[begin])/1e6)
 for k in fields:result[k]=stats(a[k]) if available.get(k) else None
 last=None
 for last in json_rows(session/'capture_metrics.jsonl'):pass
 if last is not None:result['last_poll_statistics']={k:v for k,v in last.items() if k.startswith('anchor_')}
 return result

def assess_anchor_coverage(v,a,store):
 name=store.name();db=store.db;db.execute('CREATE TABLE '+name+'(host INTEGER PRIMARY KEY, epoch TEXT, source INTEGER)');prev=None;bad=False
 for r in a:
  if r.get('validity')!='HOST_ARRIVAL_ANCHOR':continue
  h=r['host_monotonic_ns'];bad|=prev is not None and h<=prev;prev=h
  db.execute('INSERT OR REPLACE INTO '+name+' VALUES (?,?,?)',(h,str(r['writer_epoch']),r['clock_source']))
 uncovered=store.seq();counts=collections.Counter();brackets=Numbers('d')
 if bad:
  for r in v:uncovered.append({'pair_id':r['pair_id'],'raw_ns':r['raw_ns'],'assessment':'ANCHOR_HOST_TIME_NOT_INCREASING'})
  return {'status':'PENDING','input_coverage_counts':{'ANCHOR_HOST_TIME_NOT_INCREASING':len(v)},'candidate_bracket_span_ms':None,'uncovered_frames':uncovered,'note':'Segment/reset handling belongs to L2-B; no bisect or mapping on unsorted host times.'}
 for row in v:
  lo=db.execute('SELECT host,epoch,source FROM '+name+' WHERE host<=? ORDER BY host DESC LIMIT 1',(row['raw_ns'],)).fetchone();hi=db.execute('SELECT host,epoch,source FROM '+name+' WHERE host>? ORDER BY host LIMIT 1',(row['raw_ns'],)).fetchone();reason='CANDIDATE_BRACKET_ONLY'
  if row['timestamp_type']!=8192:reason='UNKNOWN_VIDEO_CLOCK'
  elif lo is None:reason='BEFORE_FIRST_VALID_ANCHOR'
  elif hi is None:reason='AFTER_LAST_VALID_ANCHOR'
  elif hi[1:]!=lo[1:]:reason='ANCHOR_DOMAIN_CHANGE'
  elif hi[0]-lo[0]>100000000:reason='ANCHOR_BRACKET_OVER_100MS'
  else:brackets.append((hi[0]-lo[0])/1e6)
  counts[reason]+=1
  if reason!='CANDIDATE_BRACKET_ONLY':uncovered.append({'pair_id':row['pair_id'],'raw_ns':row['raw_ns'],'assessment':reason})
 return {'status':'PENDING','input_coverage_counts':dict(counts),'candidate_bracket_span_ms':stats(brackets),'uncovered_frames':uncovered,'note':'Bracketing is an input coverage test, not L2-B execution, physical sync, or validated interpolation error; 100ms uses current anchor freshness policy.'}
