"""Explicit local libturbojpeg 4:2:0; no OpenCV JPEG defaults."""
import ctypes as C
import time
import numpy as np
import cv2

LIB='/lib/aarch64-linux-gnu/libturbojpeg.so.0'
class Encoder:
    def __init__(self):
        self.lib=C.CDLL(LIB)
        self.lib.tjInitCompress.restype=C.c_void_p
        self.lib.tjCompress2.argtypes=[C.c_void_p,C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_int,C.POINTER(C.c_void_p),C.POINTER(C.c_ulong),C.c_int,C.c_int,C.c_int]
        self.lib.tjCompress2.restype=C.c_int
        self.lib.tjFree.argtypes=[C.c_void_p];self.lib.tjDestroy.argtypes=[C.c_void_p]
        self.handle=self.lib.tjInitCompress()
        if not self.handle:raise RuntimeError('tjInitCompress failed')
    def encode(self,bgr,quality):
        assert bgr.dtype==np.uint8 and bgr.ndim==3 and bgr.shape[2]==3 and bgr.flags.c_contiguous
        ptr=C.c_void_p();length=C.c_ulong()
        begin=time.perf_counter_ns()
        # TJPF_BGR=1, TJSAMP_420=2, TJFLAG_ACCURATEDCT=4096 (installed header).
        status=self.lib.tjCompress2(self.handle,bgr.ctypes.data,bgr.shape[1],bgr.strides[0],bgr.shape[0],1,C.byref(ptr),C.byref(length),2,quality,4096)
        coded=time.perf_counter_ns()
        try:
            if status:raise RuntimeError('tjCompress2 failed: '+str(status))
            data=C.string_at(ptr,length.value)
        finally:
            if ptr:self.lib.tjFree(ptr)
        return data,coded-begin,time.perf_counter_ns()-coded
    def close(self):
        if self.handle:self.lib.tjDestroy(self.handle);self.handle=None

def sof(data):
    if data[:2]!=b'\xff\xd8':raise ValueError('not JPEG')
    pos=2
    while pos<len(data):
        if data[pos]!=255:raise ValueError('bad marker')
        while data[pos]==255:pos+=1
        marker=data[pos];pos+=1
        if marker in [0xd9,0xda]:break
        length=int.from_bytes(data[pos:pos+2],'big');payload=data[pos+2:pos+length]
        if marker in [0xc0,0xc1,0xc2]:
            h=int.from_bytes(payload[1:3],'big');w=int.from_bytes(payload[3:5],'big');n=payload[5]
            components=[{'id':payload[6+i*3],'h':payload[7+i*3]>>4,'v':payload[7+i*3]&15} for i in range(n)]
            return {'width':w,'height':h,'components':components,'is_420':n==3 and [(x['h'],x['v']) for x in components]==[(2,2),(1,1),(1,1)]}
        if length<2:raise ValueError('invalid JPEG segment')
        pos+=length
    raise ValueError('SOF absent')

def convert(raw):
    return cv2.cvtColor(np.frombuffer(raw,dtype=np.uint8).reshape(720,1280,2),cv2.COLOR_YUV2BGR_YUY2)

def selftest():
    cv2.setNumThreads(1)
    # Explicit SYNTHETIC limited-range reference black/white, not sensor data.
    raw=np.zeros((2,4,2),np.uint8);raw[:,:,1]=128;raw[:,0:2,0]=16;raw[:,2:,0]=235
    bgr=cv2.cvtColor(raw,cv2.COLOR_YUV2BGR_YUY2)
    assert np.all(bgr[:,:2]==0) and np.all(bgr[:,2:]==255)
    encoder=Encoder()
    try:
        for q in [90,95]:
            data,_,_=encoder.encode(np.tile(bgr,(8,4,1)),q)
            assert sof(data)['is_420']
            decoded=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
            assert decoded.shape==(16,16,3)
    finally:encoder.close()
    return 'SYNTHETIC_PASS: YUYV reference, explicit Q90/Q95 420 SOF and decode'
