"""SYNTHETIC repeated sidecars: not a new hardware/20-minute validation."""
import json,pathlib,resource,sys,time
from unittest.mock import patch
W=pathlib.Path('/home/jetson/zed_capture_ws');sys.path.insert(0,str(W/'scripts'))
from checker_store import Store,dump
from checker_streams import csv_rows
import checker_io
factor=int(sys.argv[1]);out=pathlib.Path(sys.argv[2]);out.mkdir();source=pathlib.Path('/home/jetson/zed_capture_data/20261018_185527_61ca19f8');summary=json.loads((source/'capture_summary.json').read_text());nv=summary['video_io_events_written'];nh=summary['hid_io_events_written'];pairs=summary['pairs_written']
summary['video_io_events_written']*=factor;summary['hid_io_events_written']*=factor
(out/'capture_summary.json').write_text(json.dumps(summary));(out/'SYNTHETIC.json').write_text(json.dumps({'kind':'REPEATED_HISTORICAL_SIDECARS','repetitions':factor,'source':str(source),'clock_values':'original repeated; reset diagnostics deliberately preserved','no_bag_or_image_copy':True}))
def repeated(path,integer=False):
 for repeat in range(factor):
  for r in csv_rows(source/path.name,integer):
   for k,step in [('event_id',nv),('read_id',nh),('sample_id',nh),('pair_id',pairs)]:
    if k in r and int(r[k]):r[k]=int(r[k])+step*repeat if integer else str(int(r[k])+step*repeat)
   yield r
start=time.monotonic();store=Store(out)
with patch('checker_io.csv_rows',side_effect=repeated):result=checker_io.audit(out,store)
with (out/'result.json').open('x') as f:dump(result,f)
metrics={'kind':'SYNTHETIC_REPLAY','factor':factor,'seconds':time.monotonic()-start,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'video_events':result['video']['events'],'hid_events':result['hid']['events'],'gap_events':len(result['video']['gap_events']),'status':result['status'],'errors':result['errors'],'scratch_bytes':store.path.stat().st_size,'result_bytes':(out/'result.json').stat().st_size}
assert metrics['video_events']==nv*factor and metrics['hid_events']==nh*factor
assert metrics['gap_events']==12*factor+factor-1
assert not result['errors'],result['errors']
store.close();(out/'profile.json').write_text(json.dumps(metrics,indent=2));print(json.dumps(metrics,indent=2))
