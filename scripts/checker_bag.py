"""Strict fixed-layout Livox decode without millions of Python point objects.
Every array byte is accounted for. No point filtering or cloud sampling.
All other types keep genpy deserialization. Not part of the acquisition driver.
"""
import codecs,struct
import numpy as np
DT=np.dtype([('offset_time','<u4'),('x','<f4'),('y','<f4'),('z','<f4'),('reflectivity','u1'),('tag','u1'),('line','u1')])
class Points:
 def __init__(self,view):self.view=view
 def __len__(self):return len(self.view)
 def __bool__(self):return len(self.view)>0

def cloud_decode(data,cls,md5):
 from livox_ros_driver2.msg import CustomMsg,CustomPoint
 if cls._md5sum!=md5 or md5!=CustomMsg._md5sum or cls._slot_types!=CustomMsg._slot_types or CustomPoint._slot_types!=['uint32','float32','float32','float32','uint8','uint8','uint8']:
  raise ValueError('Livox datatype/MD5/layout mismatch')
 m=cls();codecs.lookup_error('rosmsg').msg_type=m._type
 seq,sec,nsec,n=struct.unpack_from('<4I',data,0);off=16+n
 m.header.seq=seq;m.header.stamp.secs=sec;m.header.stamp.nsecs=nsec;m.header.frame_id=data[16:off].decode('utf-8','rosmsg')
 m.timebase,m.point_num,m.lidar_id=struct.unpack_from('<QIB',data,off);m.rsvd=data[off+13:off+16];count=struct.unpack_from('<I',data,off+16)[0];off+=20
 if len(data)<off+count*19:raise ValueError('Livox point array underfill')
 # genpy allows trailing bytes. Preserve that behavior; all declared points are decoded.
 m.points=Points(np.frombuffer(data,dtype=DT,count=count,offset=off));return m

def messages(bag):
 for topic,raw,stamp in bag.read_messages(raw=True):
  datatype,data,md5,position,cls=raw
  if datatype=='livox_ros_driver2/CustomMsg':m=cloud_decode(data,cls,md5)
  else:m=cls().deserialize(data)
  yield topic,m,stamp

MAX_INDEX_RECORDS=2500000
MAX_CONNECTIONS=1024
MAX_CHUNKS=8192

def index_budget(bag,previous_records=0):
 """Use compact chunk counts BEFORE rosbag loads per-message Python indexes.
 rosbag remains O(N) within this explicit finite budget, not constant-memory.
 """
 n=bag.get_message_count()
 if n+previous_records>MAX_INDEX_RECORDS or len(bag._connections)>MAX_CONNECTIONS or len(bag._chunks)>MAX_CHUNKS:
  raise ValueError('FULL_STRICT ROS bag index memory budget exceeded; not a data PASS')
 return n+previous_records
