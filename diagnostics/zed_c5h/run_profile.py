import sys,pathlib,time,json,resource,os,functools
W=pathlib.Path('/home/jetson/zed_capture_ws');O=pathlib.Path(sys.argv[1]);mode=sys.argv[2];S=pathlib.Path(sys.argv[3]);dest=O/("bench_"+mode);dest.mkdir()
sys.path[:0]=[str(O/'before/scripts' if mode=='before' else W/'scripts'),str(W/'diagnostics/zed_jpeg_benchmark'),str(W/'diagnostics/gnss_r2')]
import check_recording as cr, jpeg_file_check as jf,gnss_recording_check as gn
stages={}
def wrap(obj,name):
 orig=getattr(obj,name)
 @functools.wraps(orig)
 def run(*a,**kw):
  start=time.monotonic()
  try:return orig(*a,**kw)
  finally:stages[name]=stages.get(name,0)+time.monotonic()-start
 setattr(obj,name,run)
for obj,name in [(jf,'file_audit'),(gn,'check_gnss'),(cr,'audit_io'),(cr,'timing_evidence'),(cr,'assess_anchor_coverage'),(cr,'resources')]:wrap(obj,name)
import rosbag
orig=rosbag.Bag.read_messages
calls=[]
def reading(self,*a,**kw):
 it=orig(self,*a,**kw);seconds=0;count=0
 try:
  while True:
   start=time.monotonic()
   try:item=next(it)
   except StopIteration:seconds+=time.monotonic()-start;break
   seconds+=time.monotonic()-start;count+=1;yield item
 finally:calls.append({'records':count,'iterator_seconds':seconds})
rosbag.Bag.read_messages=reading
io0=pathlib.Path('/proc/self/io').read_text();start=time.monotonic();result=cr.check(S);checkseconds=time.monotonic()-start
with (dest/'result.json').open('x') as f:json.dump(result,f,indent=2)
metrics={'check_seconds':checkseconds,'total_seconds':time.monotonic()-start,'stages_seconds':stages,'bag_iterators':calls,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'proc_io_before':io0,'proc_io_after':pathlib.Path('/proc/self/io').read_text(),'result_bytes':(dest/'result.json').stat().st_size,'source':str(cr.__file__),'hardware':False}
(dest/'profile.json').write_text(json.dumps(metrics,indent=2));print(json.dumps(metrics,indent=2))
