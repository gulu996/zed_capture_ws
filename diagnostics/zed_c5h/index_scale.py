"""SYNTHETIC ROS index allocation only; not a 20-minute sensor/bag test."""
import json,pathlib,resource,time,sys
import genpy
from rosbag.bag import _IndexEntry200
out=pathlib.Path(sys.argv[1]);entries=[];points=[];start=time.monotonic();unit=528576
for i in range(unit*4):
 entries.append(_IndexEntry200(genpy.Time(1792320930+i//1800,(i%1800)*555555),(i//4000)*8388608+4096,(i%4000)*100))
 if (i+1)%unit==0:
  rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
  points.append({'records':i+1,'peak_rss_kib':rss,'seconds':time.monotonic()-start})
  if rss>1024*1024:raise RuntimeError('SYNTHETIC index stress reached 1GiB safety limit')
result={'kind':'SYNTHETIC_ROSBAG_INDEX_OBJECTS','not_full_bag_or_hardware_test':True,'points':points,'nominal_20min_record_projection':unit*4,'configured_record_budget':2500000}
out.open('x').write(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
