"""FULL_STRICT runner; retains all evidence in a streamed JSON result."""
import functools,json,pathlib,resource,time
from checker_store import Store,dump
import checker_strict as strict

def run(session,output_dir):
 output_dir=pathlib.Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
 path=output_dir/'check_result.json'
 if path.exists():path=output_dir/('check_result_%d.json'%time.time_ns())
 stage={};wrapped=[]
 def instrument(obj,key):
  original=getattr(obj,key)
  @functools.wraps(original)
  def call(*a,**kw):
   start=time.monotonic()
   try:return original(*a,**kw)
   finally:stage[key]=stage.get(key,0)+time.monotonic()-start
  setattr(obj,key,call);wrapped.append((obj,key,original))
 import checker_streams
 for obj,key in [(checker_streams,'file_audit'),(strict,'audit_io'),(strict,'timing_evidence'),(strict,'assess_anchor_coverage'),(strict,'resources')]:instrument(obj,key)
 original_messages=strict.messages;bag_seconds=[0.];records=[0]
 def messages(bag):
  it=original_messages(bag)
  while True:
   b=time.monotonic()
   try:item=next(it)
   except StopIteration:bag_seconds[0]+=time.monotonic()-b;break
   bag_seconds[0]+=time.monotonic()-b;records[0]+=1;yield item
 strict.messages=messages
 begin=time.monotonic();io0=pathlib.Path('/proc/self/io').read_text();store=Store(output_dir);failure=None
 try:
  result=strict.check(session,store);check_s=time.monotonic()-begin
  with path.open('x') as f:dump(result,f);f.write('\n')
  status=result['capture_integrity'];errors=result['errors'];counts=result['counts']
 except Exception as exc:
  # A budget, parse or I/O failure cannot be interpreted as strict success.
  failure=repr(exc);status='FAIL';errors=['FULL_STRICT_CHECK aborted: '+failure];counts={};check_s=time.monotonic()-begin
  if not path.exists():
   with path.open('x') as f:json.dump({'capture_integrity':'FAIL','errors':errors,'full_strict_completed':False},f)
 finally:
  strict.messages=original_messages
  for obj,key,original in wrapped:setattr(obj,key,original)
  db_bytes=store.path.stat().st_size if store.path.exists() else 0
  store.close()
 profile={'check_mode':'FULL_STRICT_CHECK','full_strict_completed':failure is None,'failure':failure,'source_session':str(pathlib.Path(session).resolve()),'check_seconds':check_s,'total_seconds':time.monotonic()-begin,'stages_seconds':stage,'bag_read_decode_seconds':bag_seconds[0],'bag_records':records[0],'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'proc_io_before':io0,'proc_io_after':pathlib.Path('/proc/self/io').read_text(),'result_bytes':path.stat().st_size,'scratch_database_bytes_before_cleanup':db_bytes,'sqlite_cache_mib':4,'numeric_values_limit_per_series':2000000,'hardware_capture_started':False}
 with path.with_suffix('.profile.json').open('x') as f:json.dump(profile,f,indent=2)
 return {'check_mode':'FULL_STRICT_CHECK','capture_integrity':status,'full_strict_completed':failure is None,'errors':errors,'counts':counts,'result_path':str(path),'profile_path':str(path.with_suffix('.profile.json'))}
