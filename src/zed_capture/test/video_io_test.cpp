// SYNTHETIC: exercise the actual acquisition loop without opening a device.
#include "videocapture.hpp"
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <cassert>
#include <cerrno>
#include <cstdarg>
#include <iostream>
#include <vector>
struct Step {int ready,select_error,dq_error,q_error; unsigned seq;};
static std::vector<Step> steps;static size_t current;
extern "C" int __wrap_select(int nfds,fd_set*,fd_set*,fd_set*,timeval* tv){
 assert(nfds==43 && tv->tv_sec==0 && tv->tv_usec==100000);
 assert(current<steps.size());auto s=steps[current++];errno=s.select_error;return s.ready;
}
extern "C" int __wrap_ioctl(int fd,unsigned long request,...){
 if(fd!=42){errno=ENODEV;return -1;}
 va_list ap;va_start(ap,request);auto b=va_arg(ap,v4l2_buffer*);va_end(ap);
 auto s=steps.at(current-1);
 if(request==VIDIOC_DQBUF){
  if(s.dq_error){errno=s.dq_error;return -1;}
  b->index=0;b->sequence=s.seq;b->timestamp.tv_sec=99;b->timestamp.tv_usec=100+s.seq;
  b->flags=V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC;b->bytesused=8;b->length=8;return 0;
 }
 assert(request==VIDIOC_QBUF);errno=s.q_error;return s.q_error?-1:0;
}
namespace sl_oc { namespace video {
struct CaptureLoopTestAccess {
 static std::vector<CaptureTiming> run(std::vector<Step> input,unsigned expected_frames){
  steps=input;current=0;VideoParams params;params.verbose=sl_oc::VERBOSITY::NONE;VideoCapture camera(params);
  unsigned char bytes[]={0,1,2,3,4,5,6,7};UVCBuffer buffer{bytes,8};unsigned count=0;
  camera.mFileDesc=42;camera.mBufCount=1;camera.mBuffers=&buffer;
  camera.mLastFrame.width=4;camera.mLastFrame.height=1;camera.mLastFrame.stride=8;
  std::vector<CaptureTiming> events;
  camera.setFrameCallback([&](const Frame& f){
   ++count;assert(f.frame_id==count && f.payload_valid && f.bytesused==8);
   assert(f.v4l2_sec==99 && f.v4l2_usec==100+f.sequence);
   for(int i=0;i<8;++i)assert(f.data[i]==i);
  });
  camera.setTimingCallback([&](const CaptureTiming& t){events.push_back(t);});
  camera.mStopCapture=false;camera.grabThreadFunc();
  camera.mFileDesc=-1;camera.mBuffers=nullptr;camera.mBufCount=0;
  assert(count==expected_frames && events.size()==input.size());
  for(size_t i=0;i<events.size();++i){assert(events[i].event_id==i+1);assert(events[i].iteration_end_ns>=events[i].poll_after_ns);}
  return events;
 }
};}}
int main(){
 using sl_oc::video::CaptureLoopTestAccess;
 auto e=CaptureLoopTestAccess::run({{0,0,0,0,0},{-1,EINTR,0,0,0},{1,0,EAGAIN,0,0},{1,0,EINTR,0,0},{1,0,0,0,12},{1,0,0,EIO,15}},2);
 assert(e[0].select_timeouts==1 && !e[0].dq_called && !e[0].qbuf_called);
 assert(e[1].select_errno==EINTR && e[1].select_errors==1 && !e[1].dq_called);
 assert(e[2].dq_eagain==1 && e[2].dq_errno==EAGAIN && !e[2].qbuf_called);
 assert(e[3].dq_errors==1 && e[3].dq_errno==EINTR);
 assert(e[4].sequence==12 && e[4].qbuf_result==0 && e[4].buffer_valid);
 assert(e[5].sequence==15 && e[5].successful_frame_interval_ns==3000 && e[5].qbuf_errors==1 && e[5].qbuf_errno==EIO);
 auto s=CaptureLoopTestAccess::run({{-1,EBADF,0,0,0}},0);assert(s[0].select_errno==EBADF);
 auto d=CaptureLoopTestAccess::run({{1,0,EIO,0,0}},0);assert(d[0].dq_errno==EIO && !d[0].qbuf_called);
 std::cout<<"SYNTHETIC PASS: actual V4L2 loop timeout/EINTR/EAGAIN/fatal errors, complete event IDs, original payload/sequence/timestamp\n";
}
