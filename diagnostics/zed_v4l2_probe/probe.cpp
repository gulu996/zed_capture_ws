// Metadata-only diagnostic. Links the unchanged production Open Capture archive.
#include "videocapture.hpp"
#include "native_mode.hpp"
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <atomic>
#include <cassert>
#include <csignal>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace sl_oc { namespace video {
// The existing friend declaration permits read-only access without editing
// production headers, or reimplementing acquisition/lifecycle syscalls.
struct CaptureLoopTestAccess {static int fd(VideoCapture& c){return c.mFileDesc;}};
}}
using sl_oc::video::Frame;using sl_oc::video::CaptureTiming;
static volatile sig_atomic_t stop_signal=0;
static void stop(int s){stop_signal=s;}
static uint64_t mono(){timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t))throw std::runtime_error("clock_gettime failed");return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec;}
struct Row {CaptureTiming t;uint32_t bytesused=0,length=0,stride=0;uint16_t width=0,height=0;bool payload_valid=false;};
struct Collector {
 std::vector<Row> rows;size_t used=0;Frame pending{};
 std::atomic<uint64_t> first{0},last{0};std::atomic<bool> overflow{false},fatal{false};
 explicit Collector(size_t capacity=4096):rows(capacity){}
 void frame(const Frame& f){pending=f;pending.data=nullptr;last=f.dq_after_ns;if(!first.load())first=f.dq_after_ns;}
 void timing(const CaptureTiming& t){
  if(used==rows.size()){overflow=true;return;}
  auto& r=rows[used++];r.t=t;
  if(t.pair_id){r.bytesused=pending.bytesused;r.length=pending.buffer_length;r.stride=pending.stride;r.width=pending.width;r.height=pending.height;r.payload_valid=pending.payload_valid;
   if(pending.frame_id!=t.pair_id)fatal=true;}
  if((t.select_result<0 && t.select_errno!=EINTR)||(t.dq_called && t.dq_result<0 && t.dq_errno!=EAGAIN && t.dq_errno!=EINTR)||(t.qbuf_called && t.qbuf_result!=0)||(t.dq_called && t.dq_result==0 && !t.buffer_valid))fatal=true;
 }
};
static std::ofstream create(const std::string& path){
 int fd=open(path.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);if(fd<0)throw std::runtime_error("refusing missing/unwritable/existing output: "+path);close(fd);
 std::ofstream f(path);f.exceptions(std::ios::failbit|std::ios::badbit);return f;
}
static void save(const Collector& c,const std::string& out){
 auto f=create(out+"/video_io_events.csv");
 f<<"event_id,pair_id,select_before_ns,select_after_ns,select_result,select_errno,dq_called,dq_result,dq_errno,dq_before_ns,dq_ioctl_start_ns,dq_after_ns,buffer_valid,buffer_index,sequence,v4l2_sec,v4l2_usec,flags,successful_frame_interval_ns,callback_end_ns,callback_cpu_ns,qbuf_called,qbuf_result,qbuf_errno,qbuf_before_ns,qbuf_ioctl_start_ns,qbuf_end_ns,iteration_end_ns,iteration_cpu_ns,select_timeouts,select_errors,dq_eagain,dq_errors,qbuf_errors,bytesused,buffer_length,stride,width,height,payload_valid\n";
 for(size_t i=0;i<c.used;++i){auto& r=c.rows[i];auto& t=r.t;
  f<<t.event_id<<','<<t.pair_id<<','<<t.poll_before_ns<<','<<t.poll_after_ns<<','<<t.select_result<<','<<t.select_errno<<','<<int(t.dq_called)<<','<<t.dq_result<<','<<t.dq_errno<<','<<t.dq_before_ns<<','<<t.dq_ioctl_start_ns<<','<<t.dq_after_ns<<','<<int(t.buffer_valid)<<','<<t.buffer_index<<','<<t.sequence<<','<<t.raw_sec<<','<<t.raw_usec<<','<<t.flags<<','<<t.successful_frame_interval_ns<<','<<t.callback_end_ns<<','<<t.callback_cpu_ns<<','<<int(t.qbuf_called)<<','<<t.qbuf_result<<','<<t.qbuf_errno<<','<<t.qbuf_before_ns<<','<<t.qbuf_ioctl_start_ns<<','<<t.qbuf_end_ns<<','<<t.iteration_end_ns<<','<<t.iteration_cpu_ns<<','<<t.select_timeouts<<','<<t.select_errors<<','<<t.dq_eagain<<','<<t.dq_errors<<','<<t.qbuf_errors<<','<<r.bytesused<<','<<r.length<<','<<r.stride<<','<<r.width<<','<<r.height<<','<<r.payload_valid<<'\n';
 }f.close();int fd=open((out+"/video_io_events.csv").c_str(),O_RDONLY|O_CLOEXEC);if(fd<0||fsync(fd)){if(fd>=0)close(fd);throw std::runtime_error("metadata fsync failed");}close(fd);
}
static bool snapshot(int fd,const std::string& path,const NativeMode& mode){
 auto f=create(path);v4l2_format fmt{};fmt.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
 int fmt_result=ioctl(fd,VIDIOC_G_FMT,&fmt),fmt_errno=fmt_result<0?errno:0;
 v4l2_streamparm parm{};parm.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;int pr=ioctl(fd,VIDIOC_G_PARM,&parm),pe=pr<0?errno:0;
 f<<"{\"format_result\":"<<fmt_result<<",\"format_errno\":"<<fmt_errno<<",\"width\":"<<fmt.fmt.pix.width<<",\"height\":"<<fmt.fmt.pix.height<<",\"fourcc\":"<<fmt.fmt.pix.pixelformat<<",\"stride\":"<<fmt.fmt.pix.bytesperline<<",\"sizeimage\":"<<fmt.fmt.pix.sizeimage<<",\"parm_result\":"<<pr<<",\"parm_errno\":"<<pe<<",\"interval_numerator\":"<<parm.parm.capture.timeperframe.numerator<<",\"interval_denominator\":"<<parm.parm.capture.timeperframe.denominator<<",\"controls\":[";
 bool first=true;for(auto id:{V4L2_CID_EXPOSURE_AUTO,V4L2_CID_EXPOSURE_ABSOLUTE,V4L2_CID_GAIN,V4L2_CID_AUTO_WHITE_BALANCE}){
  v4l2_control c{};c.id=id;int r=ioctl(fd,VIDIOC_G_CTRL,&c),e=r<0?errno:0;if(!first)f<<',';first=false;f<<"{\"id\":"<<id<<",\"result\":"<<r<<",\"errno\":"<<e<<",\"value\":"<<c.value<<'}';
 }f<<"]}\n";
 f.close();return fmt_result==0 && pr==0 && mode.matches(fmt,parm);
}
static int selftest(){
 Collector c(2);Frame f;f.data=reinterpret_cast<uint8_t*>(1);f.frame_id=1;f.bytesused=8294400;f.buffer_length=8294400;f.width=3840;f.height=1080;f.stride=7680;f.dq_after_ns=100;f.payload_valid=true;
 c.frame(f);assert(c.pending.data==nullptr && c.first==100);
 CaptureTiming t;t.event_id=1;t.pair_id=1;t.dq_called=true;t.buffer_valid=true;t.select_result=1;t.sequence=23;t.raw_sec=123;t.raw_usec=456;t.flags=0x12001;c.timing(t);
 assert(c.used==1 && c.rows[0].bytesused==8294400 && c.rows[0].t.sequence==23 && c.rows[0].t.raw_usec==456 && !c.fatal);
 t.pair_id=0;t.dq_called=false;t.event_id=2;t.select_result=0;c.timing(t);assert(c.rows[1].bytesused==0);c.timing(t);assert(c.overflow && c.used==2);
 Collector errors; t.select_result=1;t.dq_called=true;t.dq_result=-1;t.dq_errno=EAGAIN;errors.timing(t);assert(!errors.fatal);t.dq_errno=EIO;errors.timing(t);assert(errors.fatal);
 std::cout<<"SYNTHETIC PASS: no pixel dereference, exact raw metadata, bounded overflow, timeout/EAGAIN/error handling; capacity bytes="<<4096*sizeof(Row)<<'\n';return 0;
}
int main(int argc,char** argv){
 if(argc==2 && std::string(argv[1])=="--self-test")return selftest();
 if((argc!=3 && argc!=4) || getuid()==0 || !getenv("ZED_LOW_LOAD_PREFLIGHT")){std::cerr<<"Use run_probe.sh as ordinary jetson user; preflight required\n";return 2;}
 NativeMode mode=NativeMode::parse("HD1080");
 try{if(argc==4)mode=NativeMode::parse(argv[3]);}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
 const std::string dev=argv[1],out=argv[2];Collector collector;int guard=-1,rc=2;bool completed=false;unsigned buffers=0;uint64_t started=mono(),ended=started;
 bool enumerated=false,negotiated=false,after_verified=false;
 std::signal(SIGINT,stop);std::signal(SIGTERM,stop);
 try{
  guard=open(dev.c_str(),O_RDWR|O_NONBLOCK|O_CLOEXEC);if(guard<0 || flock(guard,LOCK_EX|LOCK_NB))throw std::runtime_error("device unavailable or probe lock busy");
  v4l2_capability cap{};if(ioctl(guard,VIDIOC_QUERYCAP,&cap))throw std::runtime_error("QUERYCAP failed");
  auto caps=cap.capabilities&V4L2_CAP_DEVICE_CAPS?cap.device_caps:cap.capabilities;
  if(!(caps&V4L2_CAP_VIDEO_CAPTURE)||!(caps&V4L2_CAP_STREAMING))throw std::runtime_error("not a streaming video capture node");
  snapshot(guard,out+"/v4l2_before.json",mode);
  {auto f=create(out+"/v4l2_enumeration.json");enumerated=enumerateNative(mode,f,[&](unsigned long req,void* arg){return ioctl(guard,req,arg);});f.close();}
  if(mode.name=="HD720" && !enumerated)throw std::runtime_error("Native YUYV HD720/30 not verified by actual device enumeration; no fallback");
  sl_oc::video::VideoParams params;params.res=mode.name=="HD720"?sl_oc::video::RESOLUTION::HD720:sl_oc::video::RESOLUTION::HD1080;params.fps=sl_oc::video::FPS::FPS_30;params.verbose=sl_oc::VERBOSITY::NONE;
  auto camera=std::unique_ptr<sl_oc::video::VideoCapture>(new sl_oc::video::VideoCapture(params));
  camera->setFrameCallback([&](const Frame& f){collector.frame(f);});camera->setTimingCallback([&](const CaptureTiming& t){collector.timing(t);});
  if(dev.substr(0,10)!="/dev/video")throw std::runtime_error("unexpected video node");
  if(!camera->initializeVideo(std::stoi(dev.substr(10))))throw std::runtime_error("Open Capture initialization refused/failed (including EBUSY); no retries");
  buffers=camera->getBufferCount();int width=0,height=0;camera->getFrameSize(width,height);
  int fd=sl_oc::video::CaptureLoopTestAccess::fd(*camera);
  negotiated=snapshot(fd,out+"/v4l2_negotiated.json",mode);
  if(buffers!=4 || width!=int(mode.width) || height!=int(mode.height) || !negotiated)throw std::runtime_error("actual G_FMT/G_PARM/buffers differ from requested native YUYV mode/30fps/4 buffers; no fallback");
  // No console, file writes, image copies or ROS operations inside this window.
  started=mono();while(!stop_signal && !collector.overflow && !collector.fatal){
   uint64_t n=mono(),first=collector.first.load();
   if(first && n-first>=30000000000ULL){completed=true;break;}
   if(!first && n-started>=10000000000ULL)throw std::runtime_error("no first frame within 10s; no retry");
   if(first && n-collector.last.load()>3000000000ULL)throw std::runtime_error("video stalled for 3s");
   usleep(10000);
  }
  camera.reset();ended=mono();after_verified=snapshot(guard,out+"/v4l2_after.json",mode);
  rc=completed&&!collector.overflow&&!collector.fatal&&after_verified?0:2;
 }catch(const std::exception& e){ended=mono();std::cerr<<e.what()<<'\n';}
 if(guard>=0)close(guard);
 try{
  save(collector,out);auto f=create(out+"/probe_end.json");
  f<<"{\"resolution_mode\":\""<<mode.name<<"\",\"mode_enumerated\":"<<(enumerated?"true":"false")<<",\"negotiated_verified\":"<<(negotiated?"true":"false")<<",\"after_settings_verified\":"<<(after_verified?"true":"false")<<",\"completed_duration\":"<<(completed?"true":"false")<<",\"returncode\":"<<rc<<",\"signal\":"<<stop_signal<<",\"overflow\":"<<(collector.overflow?"true":"false")<<",\"fatal_io\":"<<(collector.fatal?"true":"false")<<",\"buffers\":"<<buffers<<",\"record_capacity\":4096,\"metadata_storage_bytes\":"<<4096*sizeof(Row)<<",\"events_saved\":"<<collector.used<<",\"start_ns\":"<<started<<",\"end_ns\":"<<ended<<",\"images_written\":0,\"synthetic\":false}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
 return rc;
}
