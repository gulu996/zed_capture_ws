#include <ros/ros.h>
#include <rosbag/bag.h>
#include <sensor_msgs/Image.h>
#include <sensor_msgs/Imu.h>
#include <std_msgs/String.h>
#include <topic_tools/shape_shifter.h>
#include <zed_capture/VideoStamp.h>
#include <zed_capture/ImuStamp.h>
#include <zed_capture/TimeAnchor.h>
#include "zed_capture/core.hpp"
#include "zed_capture/input_watchdog.hpp"
#include "zed_capture/imu_time_segments.hpp"
#include "zed_capture/jpeg_shadow.hpp"
#include "zed_capture/recording_queue.hpp"
#include "zed_capture/gnss_ingress.hpp"
#include "zed_capture/long_recording.hpp"
#include <sys/statvfs.h>
#include <dlfcn.h>
#include <sys/ioctl.h>
#include "videocapture.hpp"
#include "sensorcapture.hpp"
#include <linux/videodev2.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <atomic>
#include <condition_variable>
#include <deque>
#include <fstream>
#include <functional>
#include <iomanip>
#include <memory>
#include <mutex>
#include <thread>
#include <cmath>
#include <boost/make_shared.hpp>
using capture::now;
static ros::Time stamp(uint64_t ns){ros::Time t;t.fromNSec(ns);return t;}
using Job=capture::RecordingJob;
class Recorder {
 ros::NodeHandle nh,pnh{"~"};rosbag::Bag bag;
 std::string dir,anchor_path,resolution;int serial,video_id;double duration;size_t capacity;
 bool long_recording=false;double minimum_free_gb=10;uint64_t last_checkpoint=0,last_disk_check=0;
 void checkpoint(){
  const auto begin=now(CLOCK_MONOTONIC);
  for(auto* f:{&frames,&hid,&anchors,&metrics,&video_timing,&poll_events,&imu_validity,&video_io,&hid_io})f->flush();
  for(auto name:{"sensors.bag.active","video_timestamps.csv","zed_imu_raw.csv","anchors.jsonl","capture_metrics.jsonl","video_timing.csv","anchor_poll_events.csv","zed_imu_time_validity.csv","video_io_events.csv","hid_io_events.csv"}){
   int fd=open((dir+"/"+name).c_str(),O_RDONLY|O_CLOEXEC);if(fd<0)throw std::runtime_error("checkpoint open failed");
   int rc=fdatasync(fd);int saved=errno;close(fd);if(rc)throw std::runtime_error("checkpoint fdatasync: "+std::string(strerror(saved)));
  }
  std::ofstream log;log.exceptions(std::ios::badbit|std::ios::failbit);log.open(dir+"/c5g_checkpoints.jsonl",std::ios::app);
  auto g=gnss?gnss->json():"null";if(!g.empty()&&g.back()=='\n')g.pop_back();
  log<<"{\"begin_ns\":"<<begin<<",\"end_ns\":"<<now(CLOCK_MONOTONIC)<<",\"pairs\":"<<pairs<<",\"anchors\":"<<anchor_count<<",\"gnss\":"<<g<<",\"bag_open_chunk_may_be_unsynced\":true}\n";log.close();
 }
 std::mutex mutex;std::condition_variable cond;std::deque<Job> queue;size_t queued=0,peak=0;
 bool closed=false;std::atomic<bool> failed{false},done{false};std::string failure;
 std::thread writer,anchor_thread;std::ofstream frames,hid,anchors,metrics,video_timing,poll_events,imu_validity,video_io,hid_io;
 ros::Publisher left_pub,right_pub,imu_pub,video_meta_pub,imu_meta_pub,anchor_pub,diag_pub,imu_validity_pub;
 ros::Subscriber lidar_sub,livox_imu_sub,livox_diag_sub;
 bool gnss_enable=false;std::unique_ptr<capture::GnssIngress> gnss;
 std::array<ros::Subscriber,5> gnss_subs;std::atomic<uint64_t> last_gnss_raw{0};
 void waitGnss(){
  if(!gnss_enable)return;const auto deadline=now(CLOCK_MONOTONIC)+10000000000ULL;
  while(ros::ok()&&!failed&&!last_gnss_raw&&now(CLOCK_MONOTONIC)<deadline)std::this_thread::sleep_for(std::chrono::milliseconds(10));
  if(!last_gnss_raw||failed)throw std::runtime_error("GNSS raw readiness failed; no RTK/UTC requirement");
 }
 void stopGnss(){
  if(!gnss_enable)return;
  try{
   std::ofstream stop(dir+"/gnss/stop");if(!stop)throw std::runtime_error("cannot request GNSS stop");stop<<"stop after capture producers joined\n";stop.close();
   const auto deadline=now(CLOCK_MONOTONIC)+10000000000ULL;bool matched=false;
   while(now(CLOCK_MONOTONIC)<deadline){
    std::ifstream f(dir+"/gnss/done");int status;std::array<uint64_t,5> expected{};
    if(f>>status>>expected[0]>>expected[1]>>expected[2]>>expected[3]>>expected[4]){
     if(status)fail("GNSS receiver reported failure; raw evidence retained");
     matched=true;for(size_t i=0;i<5;++i)if(gnss->counts[i].received!=expected[i])matched=false;
     if(matched){std::ofstream ack(dir+"/gnss/ack");if(!ack)throw std::runtime_error("cannot acknowledge GNSS transport");ack<<"all published messages received; bag drain follows\n";break;}
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
   }
   if(!matched)fail("GNSS published/received mismatch or missing completion handshake");
  }catch(const std::exception& e){fail(e.what());}
 }
 std::atomic<uint64_t> pairs{0},imu_count{0},lidar_count{0},livox_imu_count{0},bad_video{0},hid_reports{0},anchor_count{0},overflows{0};
 uint64_t start_ns=0;std::atomic<uint64_t> last_video_ns{0},last_hid_ns{0},last_lidar_ns{0},last_livox_imu_ns{0};
 uint64_t first_video=0,previous_video=0,sequence_gaps=0,video_backwards=0,video_duplicates=0,video_long=0;
 uint32_t previous_sequence=0;bool have_sequence=false;
 uint64_t previous_ticks=0,imu_backwards=0,imu_duplicates=0;
 uint64_t video_io_written=0,hid_io_written=0,previous_hid_tick=0,previous_hid_host=0;
 bool have_hid_tick=false;
 capture::ImuTimeSegments imu_segments;
 uint64_t imu_time_valid=0,imu_time_invalid=0,imu_time_unconfirmed=0,imu_time_segments=0;
 void recordImuDecisions(const std::vector<capture::ImuTimeDecision>& ds){
  for(const auto& d:ds){
   imu_validity<<d.sample<<','<<d.segment<<','<<d.decision_sample<<','<<d.state<<','<<d.reason<<'\n';
   if(d.state=="VALID_CONTIGUOUS")++imu_time_valid;else if(d.state=="UNCONFIRMED")++imu_time_unconfirmed;else ++imu_time_invalid;
   imu_time_segments=std::max(imu_time_segments,d.segment);
   std_msgs::String msg;msg.data="{\"sample_id\":"+std::to_string(d.sample)+",\"segment_id\":"+std::to_string(d.segment)+",\"decision_sample_id\":"+std::to_string(d.decision_sample)+",\"time_validity\":\""+d.state+"\",\"reason\":\""+d.reason+"\",\"sync_status\":\"SYNC_PENDING\"}";
   bag.write("/zed2i/imu/time_validity",stamp(now(CLOCK_REALTIME)),msg);imu_validity_pub.publish(msg);
  }
 }
 std::atomic<uint64_t> skipped_anchors{0};
 capture::Anchor anchor_snapshot{};bool anchor_available=false;
 std::atomic<uint64_t> poll_count{0},poll_duplicate_reads{0},poll_torn_reads{0},poll_max_interval{0},poll_max_lateness{0};
 std::unique_ptr<sl_oc::video::VideoCapture> camera;
 std::unique_ptr<sl_oc::sensors::SensorCapture> sensors;
 bool jpeg_shadow_enable=false,jpeg_files=false;std::string storage_mode="raw_bag",bag_name="data.bag";int jpeg_sync_ms=1000;void* shadow_library=nullptr;
 std::unique_ptr<capture::JpegShadow> shadow;
 void initShadow(){
  if(!jpeg_shadow_enable&&!jpeg_files)return;
  if(resolution!="HD720"||duration>(long_recording?300:30))throw std::runtime_error("JPEG requested duration exceeds mode limit");
  char exe[4096];const auto n=readlink("/proc/self/exe",exe,sizeof(exe)-1);
  if(n<=0)throw std::runtime_error("cannot locate shadow plugin");exe[n]=0;
  std::string path(exe);path=path.substr(0,path.rfind('/'));path=path.substr(0,path.rfind('/'))+"/libcapture_jpeg_shadow.so";
  shadow_library=dlopen(path.c_str(),RTLD_NOW|RTLD_LOCAL);
  if(!shadow_library)throw std::runtime_error(dlerror());
  if(jpeg_files){using Factory=capture::JpegShadow* (*)(const char*,int);auto create=reinterpret_cast<Factory>(dlsym(shadow_library,long_recording?"create_jpeg_files_incremental":"create_jpeg_files"));if(!create)throw std::runtime_error("files factory missing");shadow.reset(create(dir.c_str(),jpeg_sync_ms));}
  else {auto create=reinterpret_cast<capture::ShadowFactory>(dlsym(shadow_library,"create_jpeg_shadow"));if(!create)throw std::runtime_error("shadow factory missing");shadow.reset(create(dir.c_str()));}
 }
 void recordColorMetadata(){
  if(!jpeg_shadow_enable&&!jpeg_files)return;
  // A separate O_RDONLY descriptor performs G_FMT/G_PARM only. No controls,
  // streaming or buffer allocation on this descriptor. Uses selected device.
  const auto device=camera->getDeviceName();int fd=open(device.c_str(),O_RDONLY|O_NONBLOCK|O_CLOEXEC);
  v4l2_format fmt{};fmt.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
  v4l2_streamparm parm{};parm.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
  int fr=fd<0?-1:ioctl(fd,VIDIOC_G_FMT,&fmt);const int ferr=fr<0?errno:0;
  int pr=fd<0?-1:ioctl(fd,VIDIOC_G_PARM,&parm);const int perr=pr<0?errno:0;if(fd>=0)close(fd);
  std::ofstream out(dir+"/jpeg_shadow_color.json");
  out<<"{\"status\":\""<<(fr==0?"OBSERVED":"UNKNOWN")<<"\",\"device\":\""<<device<<"\",\"g_fmt_errno\":"<<ferr<<",\"g_parm_errno\":"<<perr;
  if(fr==0)out<<",\"width\":"<<fmt.fmt.pix.width<<",\"height\":"<<fmt.fmt.pix.height<<",\"pixel_format\":"<<fmt.fmt.pix.pixelformat<<",\"stride\":"<<fmt.fmt.pix.bytesperline<<",\"colorspace\":"<<fmt.fmt.pix.colorspace<<",\"ycbcr_enc\":"<<fmt.fmt.pix.ycbcr_enc<<",\"quantization\":"<<fmt.fmt.pix.quantization<<",\"xfer_func\":"<<fmt.fmt.pix.xfer_func;
  if(pr==0)out<<",\"timeperframe_numerator\":"<<parm.parm.capture.timeperframe.numerator<<",\"timeperframe_denominator\":"<<parm.parm.capture.timeperframe.denominator;
  out<<",\"interpretation\":\"Driver-reported raw enum values; DEFAULT(0) is not a measured color calibration. Conversion unchanged from C3 BT601 limited reference.\"}\n";
 }
 void fail(const std::string& why){std::lock_guard<std::mutex> lock(mutex);if(!failed.exchange(true)){failure=why;ROS_ERROR_STREAM(why);}cond.notify_all();}
 bool push(size_t bytes,std::function<void()> work){
  std::lock_guard<std::mutex> lock(mutex);
  if(long_recording){auto original=std::move(work);work=[this,original]{
   if(capture::bagLimitReached(bag.getSize()))throw std::runtime_error("C5G_SENSOR_BAG_8GB_LIMIT; explicit bounded index/storage budget");
   original();
  };}
  const auto r=capture::recordingEnqueue(queue,queued,peak,capacity,closed,failed,bytes,std::move(work));
  if(r==capture::EnqueueResult::Closed)return false;
  if(r==capture::EnqueueResult::Full){++overflows;failure="bounded recording queue overflow; acquisition stopped; session INCOMPLETE";failed=true;ROS_ERROR_STREAM(failure);cond.notify_all();return false;}
  cond.notify_one();return true;
 }
 void writeLoop(){
  try{capture::recordingDrain(mutex,cond,queue,queued,closed);recordImuDecisions(imu_segments.finish());}
  catch(const std::exception& e){fail(std::string("bag/sidecar writer: ")+e.what());}
 }
 void video(const sl_oc::video::Frame& f){
  if(failed)return;
  last_video_ns=f.dq_after_ns;const uint64_t copy_begin=now(CLOCK_MONOTONIC);
  auto meta=boost::make_shared<zed_capture::VideoStamp>();
  const uint64_t raw=f.v4l2_sec>=0&&f.v4l2_usec>=0?uint64_t(f.v4l2_sec)*1000000000ULL+uint64_t(f.v4l2_usec)*1000:0;
  meta->header.stamp=stamp(raw);meta->header.seq=f.sequence;meta->header.frame_id="zed2i_raw_stereo";
  meta->pair_id=f.frame_id;meta->oc_frame_id=f.frame_id;meta->oc_rebased_ns=f.timestamp;
  meta->v4l2_sec=f.v4l2_sec;meta->v4l2_usec=f.v4l2_usec;meta->v4l2_sequence=f.sequence;meta->v4l2_flags=f.flags;
  meta->timestamp_type=f.flags&V4L2_BUF_FLAG_TIMESTAMP_MASK;meta->timestamp_source=f.flags&V4L2_BUF_FLAG_TSTAMP_SRC_MASK;
  meta->bytesused=f.bytesused;meta->buffer_length=f.buffer_length;meta->row_stride=f.stride;meta->pixel_format=f.pixel_format;meta->field=f.field;
  meta->stereo_width=f.width;meta->height=f.height;meta->dq_monotonic_before_ns=f.dq_before_ns;meta->dq_monotonic_after_ns=f.dq_after_ns;meta->dq_realtime_ns=f.dq_realtime_ns;
  meta->payload_valid=f.payload_valid;meta->sync_status="SYNC_PENDING";
  auto left=boost::make_shared<sensor_msgs::Image>(),right=boost::make_shared<sensor_msgs::Image>();
  if(f.payload_valid){
   left->header=meta->header;right->header=meta->header;left->header.frame_id="zed2i_left_raw";right->header.frame_id="zed2i_right_raw";
   left->height=right->height=f.height;left->width=right->width=f.width/2;
   left->encoding=right->encoding="8UC2"; // Exact Y0 U Y1 V bytes. No color conversion.
   left->step=right->step=f.width;left->is_bigendian=right->is_bigendian=0;
   try{capture::splitYuyv(f.data,f.bytesused,f.width,f.height,f.stride,left->data,right->data);}catch(const std::exception& e){fail(e.what());return;}
  }
  const uint64_t copied=now(CLOCK_MONOTONIC);
  const ros::Time record_time=stamp(f.dq_realtime_ns);
  // C5-F sensor writer owns metadata only; pixel copies belong only to JPEG queue.
  auto record_left=jpeg_files?sensor_msgs::Image::Ptr():left,record_right=jpeg_files?sensor_msgs::Image::Ptr():right;
  const bool raw_accepted=push(jpeg_files?2048:left->data.size()+right->data.size()+2048,[this,meta,left=record_left,right=record_right,record_time,raw,copy_begin,copied]{
   const uint64_t writer_begin=now(CLOCK_MONOTONIC);
   bag.write("/zed2i/video_stamp",record_time,*meta);video_meta_pub.publish(meta);
   if(meta->payload_valid){if(!jpeg_files){bag.write("/zed2i/left/image_raw",record_time,*left);bag.write("/zed2i/right/image_raw",record_time,*right);++pairs;
    if(left_pub.getNumSubscribers())left_pub.publish(left);if(right_pub.getNumSubscribers())right_pub.publish(right);
   }else ++pairs;}else ++bad_video;
   if(have_sequence){uint32_t delta=meta->v4l2_sequence-previous_sequence;if(delta>1&&delta<0x80000000U)sequence_gaps+=delta-1;}
   previous_sequence=meta->v4l2_sequence;have_sequence=true;
   if(previous_video){if(raw<previous_video)++video_backwards;else if(raw==previous_video)++video_duplicates;else if(raw-previous_video>50000000ULL)++video_long;}
   if(!first_video)first_video=raw;previous_video=raw;
   frames<<meta->pair_id<<','<<meta->v4l2_sequence<<','<<raw<<','<<meta->v4l2_flags<<','<<meta->timestamp_type<<','<<meta->timestamp_source<<','<<meta->dq_monotonic_before_ns<<','<<meta->dq_monotonic_after_ns<<','<<meta->dq_realtime_ns<<','<<meta->oc_rebased_ns<<','<<meta->bytesused<<','<<meta->row_stride<<','<<int(meta->payload_valid)<<','<<copy_begin<<','<<copied<<','<<writer_begin<<','<<now(CLOCK_MONOTONIC)<<'\n';
  });
  // Only owned, immutable image copies are shared; never f.data/MMAP memory.
  // Raw recording is queued first. Shadow rejection cannot cancel that job.
  if(shadow)shadow->submit({meta,left,right,copied,raw_accepted});
 }
 void imuRaw(const uint8_t* bytes,size_t length,uint64_t before,uint64_t after,uint64_t wall){
  if(failed)return;last_hid_ns=after;
  auto meta=boost::make_shared<zed_capture::ImuStamp>();meta->sample_id=++hid_reports;
  meta->read_monotonic_before_ns=before;meta->read_monotonic_after_ns=after;meta->read_realtime_ns=wall;
  meta->raw_hid_report.assign(bytes,bytes+length);meta->sync_status="SYNC_PENDING";
  auto imu=boost::make_shared<sensor_msgs::Imu>();
  sl_oc::sensors::usb::RawData raw{};
  if(length>=sizeof(raw)&&bytes[0]==sl_oc::sensors::usb::REP_ID_SENSOR_DATA){
   std::memcpy(&raw,bytes,sizeof(raw));meta->device_ticks=raw.timestamp;
   meta->header.stamp=stamp(capture::ticksToNs(raw.timestamp));meta->header.seq=meta->sample_id;meta->header.frame_id="zed2i_imu_raw_axes";
   meta->imu_valid=raw.imu_not_valid!=1;meta->frame_sync=raw.frame_sync;meta->sync_capabilities=raw.sync_capabilities;meta->frame_sync_count=raw.frame_sync_count;
   imu->header=meta->header;imu->orientation_covariance[0]=-1;
   constexpr double d2r=3.14159265358979323846/180.0;
   imu->angular_velocity.x=raw.gX*GYRO_SCALE*d2r;imu->angular_velocity.y=raw.gY*GYRO_SCALE*d2r;imu->angular_velocity.z=raw.gZ*GYRO_SCALE*d2r;
   imu->linear_acceleration.x=raw.aX*ACC_SCALE;imu->linear_acceleration.y=raw.aY*ACC_SCALE;imu->linear_acceleration.z=raw.aZ*ACC_SCALE;
  }
  push(2048,[this,meta,imu,wall]{bag.write("/zed2i/imu_stamp",stamp(wall),*meta);imu_meta_pub.publish(meta);
   if(meta->imu_valid){bag.write("/zed2i/imu/data_raw",stamp(wall),*imu);imu_pub.publish(imu);++imu_count;
    if(previous_ticks){if(meta->device_ticks<previous_ticks)++imu_backwards;else if(meta->device_ticks==previous_ticks)++imu_duplicates;}previous_ticks=meta->device_ticks;}
   hid<<meta->sample_id<<','<<meta->device_ticks<<','<<meta->read_monotonic_before_ns<<','<<meta->read_monotonic_after_ns<<','<<meta->read_realtime_ns<<','<<int(meta->imu_valid)<<','<<capture::hex(meta->raw_hid_report.data(),meta->raw_hid_report.size())<<'\n';
   // Raw HID, raw IMU, headers and ticks above remain untouched. Consumers must
   // join sample_id with this explicit segmentation before fitting a time axis.
   recordImuDecisions(imu_segments.add(meta->sample_id,meta->device_ticks,meta->read_monotonic_after_ns,meta->imu_valid));
  });
 }
 void relay(const topic_tools::ShapeShifter::ConstPtr& message,const std::string& topic,const std::string& expected){
  if(message->getDataType()!=expected){fail("unexpected message type on "+topic+": "+message->getDataType());return;}
  const uint64_t mono=now(CLOCK_MONOTONIC),wall=now(CLOCK_REALTIME);
  if(topic=="/livox/lidar")last_lidar_ns=mono;else if(topic=="/livox/imu")last_livox_imu_ns=mono;
  push(message->size()+1024,[this,message,topic,wall]{bag.write(topic,stamp(wall),*message);if(topic=="/livox/lidar")++lidar_count;else if(topic=="/livox/imu")++livox_imu_count;});
 }
 void anchorLoop(){
  std::array<uint8_t,64> previous{};bool have=false;uint64_t old_seq=0,old_epoch=0;
  int fd=-1;ino_t inode=0;dev_t device=0;uint64_t last_open=0,previous_poll=0,deadline=now(CLOCK_MONOTONIC);
  while(!done && !failed){
   const uint64_t poll_start=now(CLOCK_MONOTONIC),interval=previous_poll?poll_start-previous_poll:0;
   const uint64_t late=poll_start>deadline?poll_start-deadline:0;previous_poll=poll_start;
   ++poll_count;poll_max_interval=std::max(poll_max_interval.load(),interval);poll_max_lateness=std::max(poll_max_lateness.load(),late);
   if(poll_start-last_open>100000000ULL){last_open=poll_start;struct stat st{};
    if(stat(anchor_path.c_str(),&st)==0 && st.st_size==64){if(fd<0||st.st_ino!=inode||st.st_dev!=device){if(fd>=0)close(fd);fd=open(anchor_path.c_str(),O_RDONLY|O_CLOEXEC);inode=st.st_ino;device=st.st_dev;have=false;}}
    else if(fd>=0){close(fd);fd=-1;have=false;std::lock_guard<std::mutex> lock(mutex);anchor_available=false;}
   }
   uint64_t read_before=now(CLOCK_MONOTONIC),read_after=read_before;bool stable=false;
   if(fd>=0){std::array<uint8_t,64> a{},b{};
    ssize_t na=pread(fd,a.data(),64,0),nb=pread(fd,b.data(),64,0);
    read_after=now(CLOCK_MONOTONIC); // comparison reference must be AFTER the snapshot read
    capture::Anchor state{};std::memcpy(&state,a.data(),64);
    stable=na==64 && nb==64 && a==b && !(state.seq&1);
    if(stable){std::lock_guard<std::mutex> lock(mutex);anchor_snapshot=state;anchor_available=true;}
    else ++poll_torn_reads;
    if(stable && have && a==previous)++poll_duplicate_reads;
    if(stable && (!have||a!=previous)){
     auto msg=boost::make_shared<zed_capture::TimeAnchor>();uint64_t wall=now(CLOCK_REALTIME);
     msg->header.stamp=stamp(wall);msg->reader_monotonic_ns=read_after;msg->writer_epoch=state.epoch;msg->write_sequence=state.seq;
     msg->imu_stamp_ns=state.device;msg->host_monotonic_ns=state.host;msg->update_monotonic_ns=state.updated;msg->clock_source=state.source;msg->ready=state.ready;msg->uncertainty_ns=state.uncertainty;
     msg->raw_state.assign(a.begin(),a.end());msg->validity=capture::validity(state,read_after);
     if(have && old_epoch==state.epoch && state.seq>old_seq+2)msg->skipped_updates=(state.seq-old_seq)/2-1;
     skipped_anchors+=msg->skipped_updates;old_seq=state.seq;old_epoch=state.epoch;previous=a;have=true;
     push(2048,[this,msg,wall,read_before,read_after,interval,late]{bag.write("/zed2i/time_anchor",stamp(wall),*msg);anchor_pub.publish(msg);++anchor_count;
      anchors<<"{\"reader_monotonic_ns\":"<<msg->reader_monotonic_ns<<",\"reader_realtime_ns\":"<<wall<<",\"writer_epoch\":"<<msg->writer_epoch<<",\"write_sequence\":"<<msg->write_sequence<<",\"imu_stamp_ns\":"<<msg->imu_stamp_ns<<",\"host_monotonic_ns\":"<<msg->host_monotonic_ns<<",\"update_monotonic_ns\":"<<msg->update_monotonic_ns<<",\"clock_source\":"<<msg->clock_source<<",\"ready\":"<<(msg->ready?"true":"false")<<",\"uncertainty_ns\":"<<msg->uncertainty_ns<<",\"skipped_updates\":"<<msg->skipped_updates<<",\"validity\":\""<<msg->validity<<"\",\"raw_hex\":\""<<capture::hex(msg->raw_state.data(),64)<<"\",\"read_before_ns\":"<<read_before<<",\"read_after_ns\":"<<read_after<<",\"poll_interval_ns\":"<<interval<<",\"wake_lateness_ns\":"<<late<<"}\n";
     });
    }
   }
   // Timing events are diagnostic only, never used to waive skipped-update failures.
   if(interval>2000000ULL || late>1000000ULL || (fd>=0&&!stable))push(256,[this,poll_start,interval,late,read_before,read_after,stable]{poll_events<<poll_start<<','<<interval<<','<<late<<','<<read_before<<','<<read_after<<','<<int(stable)<<'\n';});
   deadline=capture::nextPollDeadline(deadline,now(CLOCK_MONOTONIC));
   timespec wake{static_cast<time_t>(deadline/1000000000ULL),static_cast<long>(deadline%1000000000ULL)};
   int error;do{error=clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&wake,nullptr);}while(error==EINTR&&!done&&!failed);
   if(error && error!=EINTR){fail("anchor absolute sleep failed");break;}
  }if(fd>=0)close(fd);
 }
 void recordVideoTiming(const sl_oc::video::CaptureTiming& t){
  push(768,[this,t]{
   // Legacy successful-frame file keeps its one-row-per-pair contract.
   if(t.pair_id)video_timing<<t.pair_id<<','<<t.sequence<<','<<t.poll_before_ns<<','<<t.poll_after_ns<<','<<t.dq_before_ns<<','<<t.dq_after_ns<<','<<t.callback_end_ns<<','<<t.qbuf_end_ns<<','<<t.callback_cpu_ns<<','<<t.qbuf_result<<'\n';
   video_io<<t.event_id<<','<<t.pair_id<<','<<t.poll_before_ns<<','<<t.poll_after_ns<<','<<t.select_result<<','<<t.select_errno<<','<<int(t.dq_called)<<','<<t.dq_result<<','<<t.dq_errno<<','<<t.dq_before_ns<<','<<t.dq_ioctl_start_ns<<','<<t.dq_after_ns<<','<<int(t.buffer_valid)<<','<<t.buffer_index<<','<<t.sequence<<','<<t.raw_sec<<','<<t.raw_usec<<','<<t.flags<<','<<t.successful_frame_interval_ns<<','<<t.callback_end_ns<<','<<t.callback_cpu_ns<<','<<int(t.qbuf_called)<<','<<t.qbuf_result<<','<<t.qbuf_errno<<','<<t.qbuf_before_ns<<','<<t.qbuf_ioctl_start_ns<<','<<t.qbuf_end_ns<<','<<t.iteration_end_ns<<','<<t.iteration_cpu_ns<<','<<t.select_timeouts<<','<<t.select_errors<<','<<t.dq_eagain<<','<<t.dq_errors<<','<<t.qbuf_errors<<'\n';
   ++video_io_written;
  });
 }
 void recordHidTiming(const sl_oc::sensors::SensorReadTiming& t){
  const uint64_t sample=t.result>0?hid_reports.load():0;
  push(768,[this,t,sample]{
   const auto& q=t.trace;
   const int64_t tick_delta=t.tick_present&&have_hid_tick?int64_t(t.device_ticks)-int64_t(previous_hid_tick):0;
   const int64_t host_delta=t.result>0&&previous_hid_host?int64_t(t.after_ns)-int64_t(previous_hid_host):0;
   hid_io<<t.read_id<<','<<sample<<','<<t.before_ns<<','<<t.after_ns<<','<<t.realtime_ns<<','<<t.result<<','<<int(t.tick_present)<<','<<t.device_ticks<<','<<int(have_hid_tick)<<','<<tick_delta<<','<<host_delta<<','<<t.callback_end_ns<<','<<q.arrival_monotonic_ns<<','<<q.dequeue_monotonic_ns<<','<<q.completed_reports<<','<<q.consumed_reports<<','<<q.queue_discards<<','<<q.queue_depth<<','<<q.queue_peak;
   for(auto count:q.transfer_status)hid_io<<','<<count;
   hid_io<<','<<q.submit_errors<<','<<q.event_loop_errors<<','<<q.read_timeouts<<','<<q.read_errors<<','<<q.last_discard_arrival_ns<<','<<q.wait_result<<'\n';
   if(t.tick_present){previous_hid_tick=t.device_ticks;have_hid_tick=true;}
   if(t.result>0)previous_hid_host=t.after_ns;
   ++hid_io_written;
  });
 }
 void waitForInputs(){
  const uint64_t begin=now(CLOCK_MONOTONIC);uint64_t stable_since=0;bool ready=false;
  while(ros::ok()&&!failed&&now(CLOCK_MONOTONIC)-begin<10000000000ULL){
   capture::Anchor a{};bool available;{std::lock_guard<std::mutex> lock(mutex);a=anchor_snapshot;available=anchor_available;}
   uint64_t li=last_lidar_ns.load(),im=last_livox_imu_ns.load(),n=now(CLOCK_MONOTONIC);
   bool good=li&&im&&n>=li&&n>=im&&n-li<1000000000ULL&&n-im<1000000000ULL&&available&&capture::validity(a,n)=="HOST_ARRIVAL_ANCHOR";
   if(good){if(!stable_since)stable_since=n;if(n-stable_since>=1000000000ULL){ready=true;break;}}else stable_since=0;
   std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  std::ofstream log(dir+"/startup_readiness.json");log<<"{\"wait_ns\":"<<now(CLOCK_MONOTONIC)-begin<<",\"livox_and_anchor_stable_before_video\":"<<(ready?"true":"false")<<",\"sync_status\":\"SYNC_PENDING\",\"startup_history_retained\":true}\n";
  if(!ros::ok()||failed)throw std::runtime_error("capture stopped during readiness wait");
  if(!ready)ROS_WARN("Input preparation timed out; raw capture continues with SYNC_PENDING and recorded coverage limitations");
 }
 capture::InputSnapshot inputSnapshot() const {
  return capture::snapshotInputs({{&last_video_ns,&last_hid_ns,&last_lidar_ns,&last_livox_imu_ns}},start_ns,[]{return now(CLOCK_MONOTONIC);});
 }
 void inputTimeout(const capture::InputSnapshot& inputs){
  // Keep the exact triggering snapshot independently of the recording queue.
  // fail() stops ingestion; already queued records still drain normally.
  const std::string json=inputs.json();
  fail("required input missing/stalled for 3 seconds; input_watchdog="+json);
  try{
   std::ofstream out;out.exceptions(std::ios::badbit|std::ios::failbit);
   out.open(dir+"/input_timeout.json");out<<json<<'\n';out.close();
   int fd=open((dir+"/input_timeout.json").c_str(),O_RDONLY|O_CLOEXEC);
   if(fd<0)throw std::runtime_error("open input_timeout.json for fsync");
   int result=fsync(fd);close(fd);if(result)throw std::runtime_error("fsync input_timeout.json");
  }catch(const std::exception& e){ROS_ERROR_STREAM("Could not persist input timeout snapshot: "<<e.what()<<"; snapshot retained in capture.log");}
 }
 void diagnostic(const capture::InputSnapshot& inputs){
  size_t q,p;capture::Anchor a{};bool available;{std::lock_guard<std::mutex> l(mutex);q=queued;p=peak;a=anchor_snapshot;available=anchor_available;}
  uint64_t wall=now(CLOCK_REALTIME),mono=now(CLOCK_MONOTONIC);
  std::ostringstream s;s<<"{\"monotonic_ns\":"<<mono<<",\"pairs_written\":"<<pairs<<",\"zed_imu_written\":"<<imu_count<<",\"lidar_written\":"<<lidar_count<<",\"livox_imu_written\":"<<livox_imu_count<<",\"queue_bytes\":"<<q<<",\"queue_peak_bytes\":"<<p<<",\"queue_overflows\":"<<overflows<<",\"anchor_poll_skipped_states\":"<<skipped_anchors<<",\"sync_status\":\"SYNC_PENDING\"}";
  std::string json=s.str();json.pop_back();json+=",\"anchor_validity\":\""+(available?capture::validity(a,mono):std::string("MISSING"))+"\",\"anchor_last_host_monotonic_ns\":"+std::to_string(a.host)+"}";
  json.pop_back();json+=",\"anchor_poll_count\":"+std::to_string(poll_count)+",\"anchor_duplicate_reads\":"+std::to_string(poll_duplicate_reads)+",\"anchor_torn_reads\":"+std::to_string(poll_torn_reads)+",\"anchor_max_poll_interval_ns\":"+std::to_string(poll_max_interval)+",\"anchor_max_wake_lateness_ns\":"+std::to_string(poll_max_lateness)+"}";
  json.pop_back();json+=",\"input_watchdog\":"+inputs.json()+"}";
  std_msgs::String m;m.data=json;push(2048,[this,m,wall]{bag.write("/zed2i/diagnostics",stamp(wall),m);diag_pub.publish(m);metrics<<m.data<<'\n';frames.flush();hid.flush();anchors.flush();metrics.flush();video_timing.flush();poll_events.flush();imu_validity.flush();video_io.flush();hid_io.flush();});
 }
 public:
 Recorder(){
  pnh.param<std::string>("session_dir",dir,"");pnh.param<std::string>("anchor_path",anchor_path,"/home/jetson/timeshare_imu");
  pnh.param<std::string>("resolution",resolution,"HD1080");pnh.param("serial",serial,38003368);pnh.param("video_id",video_id,-1);pnh.param("duration",duration,30.0);
  pnh.param("jpeg_shadow_enable",jpeg_shadow_enable,false);pnh.param("gnss_enable",gnss_enable,false);
  pnh.param("long_recording",long_recording,false);pnh.param("minimum_free_gb",minimum_free_gb,10.0);
  pnh.param<std::string>("storage_mode",storage_mode,"raw_bag");pnh.param("jpeg_sync_ms",jpeg_sync_ms,1000);
  if(storage_mode!="raw_bag"&&storage_mode!="jpeg_files")throw std::runtime_error("unknown storage mode");
  jpeg_files=storage_mode=="jpeg_files";if(jpeg_files&&jpeg_shadow_enable)throw std::runtime_error("C5F and shadow are mutually exclusive");
  capture::validateLongRecording(long_recording,jpeg_files,jpeg_shadow_enable,resolution,duration,minimum_free_gb);
  if(gnss_enable&&(!jpeg_files||resolution!="HD720"||duration>(long_recording?300:30)||duration<=0))throw std::runtime_error("GNSS requested duration exceeds mode limit");
  if(long_recording)ROS_INFO_STREAM("C5-G duration="<<duration<<" reserve_GB="<<minimum_free_gb<<" directory="<<dir);
  if(jpeg_files)bag_name="sensors.bag";ROS_INFO_STREAM("ACTUAL_STORAGE_MODE="<<storage_mode<<" bag="<<bag_name);
  int queue_mb;pnh.param("queue_mb",queue_mb,256);capacity=size_t(std::max(32,std::min(512,queue_mb)))*1024*1024;
  if(dir.empty()||dir[0]!='/')throw std::runtime_error("absolute session_dir required");
  if(long_recording&&access((dir+"/c5g_checkpoints.jsonl").c_str(),F_OK)==0)throw std::runtime_error("refuse existing C5G checkpoint evidence");
  if(access((dir+"/"+bag_name).c_str(),F_OK)==0||access((dir+"/"+bag_name+".active").c_str(),F_OK)==0)throw std::runtime_error("refusing existing recording");
  for(auto f:{"video_timestamps.csv","zed_imu_raw.csv","anchors.jsonl","capture_metrics.jsonl","capture_summary.json","video_timing.csv","anchor_poll_events.csv","startup_readiness.json","input_timeout.json","zed_imu_time_validity.csv","video_io_events.csv","hid_io_events.csv"})if(access((dir+"/"+f).c_str(),F_OK)==0)throw std::runtime_error("refusing existing sidecar");
 }
 int run(){
  if(resolution!="HD1080"&&resolution!="HD720")throw std::runtime_error("resolution must be HD1080 or HD720; no automatic fallback");
  initShadow(); // Fail initialization before starting sensors; default is a no-op.
  bag.open(dir+"/"+bag_name+".active",rosbag::bagmode::Write);bag.setCompression(rosbag::compression::Uncompressed);bag.setChunkThreshold(8*1024*1024);
  for(auto* f:{&frames,&hid,&anchors,&metrics,&video_timing,&poll_events,&imu_validity,&video_io,&hid_io})f->exceptions(std::ios::badbit|std::ios::failbit);
  frames.open(dir+"/video_timestamps.csv");hid.open(dir+"/zed_imu_raw.csv");anchors.open(dir+"/anchors.jsonl");metrics.open(dir+"/capture_metrics.jsonl");
  imu_validity.open(dir+"/zed_imu_time_validity.csv");imu_validity<<"sample_id,segment_id,decision_sample_id,time_validity,reason\n";
  video_io.open(dir+"/video_io_events.csv");hid_io.open(dir+"/hid_io_events.csv");
  video_io<<"event_id,pair_id,select_before_ns,select_after_ns,select_result,select_errno,dq_called,dq_result,dq_errno,dq_before_ns,dq_ioctl_start_ns,dq_after_ns,buffer_valid,buffer_index,sequence,v4l2_sec,v4l2_usec,flags,successful_frame_interval_ns,callback_end_ns,callback_cpu_ns,qbuf_called,qbuf_result,qbuf_errno,qbuf_before_ns,qbuf_ioctl_start_ns,qbuf_end_ns,iteration_end_ns,iteration_cpu_ns,select_timeouts,select_errors,dq_eagain,dq_errors,qbuf_errors\n";
  hid_io<<"read_id,sample_id,read_before_ns,read_after_ns,realtime_ns,result,tick_present,device_ticks,had_previous_tick,tick_delta,host_interval_ns,raw_callback_end_ns,libusb_arrival_monotonic_ns,dequeue_monotonic_ns,completed_reports,consumed_reports,queue_discards,queue_depth,queue_peak,transfer_completed,transfer_error,transfer_timed_out,transfer_cancelled,transfer_stall,transfer_no_device,transfer_overflow,submit_errors,event_loop_errors,read_timeouts,read_errors,last_discard_arrival_ns,wait_result\n";
  video_timing.open(dir+"/video_timing.csv");poll_events.open(dir+"/anchor_poll_events.csv");
  video_timing<<"pair_id,sequence,poll_before_ns,poll_after_ns,dq_before_ns,dq_after_ns,callback_end_ns,qbuf_end_ns,callback_cpu_ns,qbuf_result\n";
  poll_events<<"poll_start_ns,interval_ns,wake_lateness_ns,read_before_ns,read_after_ns,stable\n";
  frames<<"pair_id,sequence,raw_ns,flags,timestamp_type,timestamp_source,dq_before_ns,dq_after_ns,realtime_ns,oc_rebased_ns,bytesused,stride,payload_valid,copy_begin_ns,copied_ns,writer_begin_ns,writer_end_ns\n";
  hid<<"sample_id,device_ticks,read_before_ns,read_after_ns,realtime_ns,imu_valid,raw_hex\n";
  if(!jpeg_files){left_pub=nh.advertise<sensor_msgs::Image>("/zed2i/left/image_raw",2);right_pub=nh.advertise<sensor_msgs::Image>("/zed2i/right/image_raw",2);}
  imu_validity_pub=nh.advertise<std_msgs::String>("/zed2i/imu/time_validity",128);
  imu_pub=nh.advertise<sensor_msgs::Imu>("/zed2i/imu/data_raw",64);
  video_meta_pub=nh.advertise<zed_capture::VideoStamp>("/zed2i/video_stamp",32);imu_meta_pub=nh.advertise<zed_capture::ImuStamp>("/zed2i/imu_stamp",128);
  anchor_pub=nh.advertise<zed_capture::TimeAnchor>("/zed2i/time_anchor",128);diag_pub=nh.advertise<std_msgs::String>("/zed2i/diagnostics",10);
  lidar_sub=nh.subscribe<topic_tools::ShapeShifter>("/livox/lidar",256,[this](const topic_tools::ShapeShifter::ConstPtr& m){relay(m,"/livox/lidar","livox_ros_driver2/CustomMsg");},ros::VoidConstPtr(),ros::TransportHints().tcpNoDelay());
  livox_imu_sub=nh.subscribe<topic_tools::ShapeShifter>("/livox/imu",1024,[this](const topic_tools::ShapeShifter::ConstPtr& m){relay(m,"/livox/imu","sensor_msgs/Imu");},ros::VoidConstPtr(),ros::TransportHints().tcpNoDelay());
  livox_diag_sub=nh.subscribe<topic_tools::ShapeShifter>("/livox_lidar_publisher2/timestamp_diagnostics",32,[this](const topic_tools::ShapeShifter::ConstPtr& m){relay(m,"/livox_lidar_publisher2/timestamp_diagnostics","diagnostic_msgs/DiagnosticArray");});
  if(gnss_enable){
   gnss.reset(new capture::GnssIngress(bag,[this](size_t n,std::function<void()> f){return push(n,std::move(f));},[this](const std::string& e){fail(e);}));
   for(size_t i=0;i<5;++i)gnss_subs[i]=nh.subscribe<topic_tools::ShapeShifter>(capture::gnssTypes()[i].topic,128,
    [this,i](const topic_tools::ShapeShifter::ConstPtr& m){if(gnss->receive(i,m,stamp(now(CLOCK_REALTIME)))&&i==0)last_gnss_raw=now(CLOCK_MONOTONIC);},
    ros::VoidConstPtr(),ros::TransportHints().tcpNoDelay());
  }
  writer=std::thread(&Recorder::writeLoop,this);anchor_thread=std::thread([this]{try{anchorLoop();}catch(const std::exception& e){fail(std::string("anchor reader: ")+e.what());}});
  ros::AsyncSpinner spinner(1);spinner.start();start_ns=now(CLOCK_MONOTONIC);
  try{
   waitForInputs();waitGnss();
   sl_oc::video::VideoParams params;params.res=resolution=="HD1080"?sl_oc::video::RESOLUTION::HD1080:sl_oc::video::RESOLUTION::HD720;params.fps=sl_oc::video::FPS::FPS_30;
   camera.reset(new sl_oc::video::VideoCapture(params));camera->setFrameCallback([this](const sl_oc::video::Frame& f){try{video(f);}catch(const std::exception& e){fail(e.what());}});
   camera->setTimingCallback([this](const sl_oc::video::CaptureTiming& t){try{recordVideoTiming(t);}catch(const std::exception& e){fail(e.what());}});
   sensors.reset(new sl_oc::sensors::SensorCapture());sensors->setRawCallback([this](const uint8_t* b,size_t n,uint64_t t0,uint64_t t1,uint64_t wall){try{imuRaw(b,n,t0,t1,wall);}catch(const std::exception& e){fail(e.what());}});
   sensors->setReadTimingCallback([this](const sl_oc::sensors::SensorReadTiming& t){try{recordHidTiming(t);}catch(const std::exception& e){fail(e.what());}});
   if(!camera->initializeVideo(video_id))throw std::runtime_error("Open Capture video initialization failed");
   if(camera->getSerialNumber()!=serial)throw std::runtime_error("video serial does not match selected HID serial");
   if(!sensors->initializeSensors(serial))throw std::runtime_error("Open Capture HID initialization failed");
   // Do NOT call enableSensorSync: preserve raw sensor/video clocks; no calibrated sync claim.
   std::ofstream settings(dir+"/device_settings.txt");int width,height;camera->getFrameSize(width,height);uint16_t major,minor;sensors->getFirmwareVersion(major,minor);
   if(width!=(resolution=="HD1080"?3840:2560)||height!=(resolution=="HD1080"?1080:720))throw std::runtime_error("negotiated video size differs from requested mode; no automatic fallback");
   settings<<"serial="<<serial<<"\nstereo_width="<<width<<"\nheight="<<height<<"\nrequested_fps=30\npixel_format=YUYV\nimu_firmware="<<major<<'.'<<minor<<"\ncontrols=preserved_no_reset\norientation=original\nextrinsics=UNKNOWN\nintrinsics=UNKNOWN\n";
   settings<<"v4l2_requested_buffers=4\nv4l2_actual_buffers="<<camera->getBufferCount()<<"\n";
   settings<<"aec_agc="<<camera->getAECAGC()<<"\nawb="<<camera->getAutoWhiteBalance()<<"\nwhite_balance="<<camera->getWhiteBalance()<<"\ngain_left="<<camera->getGain(sl_oc::video::CAM_SENS_POS::LEFT)<<"\ngain_right="<<camera->getGain(sl_oc::video::CAM_SENS_POS::RIGHT)<<"\nexposure_left_control_units="<<camera->getExposure(sl_oc::video::CAM_SENS_POS::LEFT)<<"\nexposure_right_control_units="<<camera->getExposure(sl_oc::video::CAM_SENS_POS::RIGHT)<<"\ngamma="<<camera->getGamma()<<"\nbrightness="<<camera->getBrightness()<<"\ncontrast="<<camera->getContrast()<<"\nsaturation="<<camera->getSaturation()<<"\nsharpness="<<camera->getSharpness()<<"\n";
   settings.close();
   recordColorMetadata();
   start_ns=now(CLOCK_MONOTONIC);uint64_t last_diag=0;
   while(ros::ok()&&!failed){
    if(jpeg_files&&shadow->failed()){fail("C5F JPEG pipeline failed; see frames.csv and jpeg_files_summary.json");break;}
    const auto inputs=inputSnapshot();const uint64_t n=inputs.now_ns;
    if(n-start_ns>=uint64_t(duration*1e9))break;
    if(long_recording&&n-last_disk_check>=1000000000ULL){
     last_disk_check=n;struct statvfs fs{};
     if(statvfs(dir.c_str(),&fs)){fail("C5G_DISK_STATE_UNAVAILABLE");break;}
     if(capture::diskReserveReached(uint64_t(fs.f_bavail)*fs.f_frsize,uint64_t(minimum_free_gb*1e9),capacity)){
      fail("C5G_DISK_RESERVE_REACHED; stopping producers and draining bounded queues");break;
     }
    }
    if(gnss_enable){const auto last=last_gnss_raw.load();const auto current=now(CLOCK_MONOTONIC);if(current>=last&&current-last>3000000000ULL){fail("GNSS raw input stalled for 3 seconds");break;}}
    if(inputs.failed()){inputTimeout(inputs);break;}
    if(n-last_diag>1000000000ULL){diagnostic(inputs);last_diag=n;}
    if(long_recording&&n-last_checkpoint>=5000000000ULL){last_checkpoint=n;push(256,[this]{checkpoint();});}
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
   }
  }catch(const std::exception& e){fail(e.what());}
  camera.reset();sensors.reset();stopGnss();spinner.stop();done=true;if(anchor_thread.joinable())anchor_thread.join();
  {std::lock_guard<std::mutex> lock(mutex);closed=true;}cond.notify_all();if(writer.joinable())writer.join();
  if(gnss){if(!gnss->complete())fail("GNSS writer accounting incomplete");std::ofstream report(dir+"/gnss_writer_summary.json");report<<gnss->json();}
  // Producer has joined. Finish shadow independently; never turn JPEG failure
  // into missing raw data or suppress the original integrity checker.
  if(shadow){try{shadow->finish();if(jpeg_files&&shadow->failed())fail("C5F JPEG pipeline incomplete");}catch(const std::exception& e){std::ofstream out(dir+"/jpeg_shadow_failure.txt");out<<e.what()<<'\n';if(jpeg_files)fail(e.what());}shadow.reset();}
  if(shadow_library){dlclose(shadow_library);shadow_library=nullptr;}
  bool finalized=true;try{bag.close();frames.close();hid.close();anchors.close();metrics.close();video_timing.close();poll_events.close();imu_validity.close();video_io.close();hid_io.close();}catch(const std::exception& e){fail(e.what());finalized=false;}
  if(finalized){
   for(auto name:{"data.bag.active","video_timestamps.csv","zed_imu_raw.csv","anchors.jsonl","capture_metrics.jsonl","video_timing.csv","anchor_poll_events.csv","zed_imu_time_validity.csv","video_io_events.csv","hid_io_events.csv"}){
    int fd=open((dir+"/"+(std::string(name)=="data.bag.active"?bag_name+".active":name)).c_str(),O_RDONLY|O_CLOEXEC);
    if(fd<0){fail("cannot open recording for fsync");finalized=false;break;}
    int result=fsync(fd);close(fd);if(result){fail("recording fsync failed");finalized=false;break;}
   }
   if(long_recording){int fd=open((dir+"/c5g_checkpoints.jsonl").c_str(),O_RDONLY|O_CLOEXEC);
    if(fd>=0){if(fsync(fd)){fail("C5G checkpoint final sync failed");finalized=false;}close(fd);}
   }
  }
  if(finalized && rename((dir+"/"+bag_name+".active").c_str(),(dir+"/"+bag_name).c_str())){fail("bag rename failed");finalized=false;}
  if(finalized){int fd=open(dir.c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(fd<0){fail("cannot open session directory for fsync");finalized=false;}else{if(fsync(fd)){fail("directory fsync failed");finalized=false;}close(fd);}}
  std::ofstream summary(dir+"/capture_summary.json");summary<<"{\n\"software_version\":\"zed_capture-0.1.0\",\n\"sync_status\":\"SYNC_PENDING\",\n\"physical_sync_verified\":false,\n\"failed\":"<<(failed?"true":"false")<<",\n\"bag_finalized\":"<<(finalized?"true":"false")<<",\n\"pairs_written\":"<<pairs<<",\n\"zed_imu_written\":"<<imu_count<<",\n\"lidar_written\":"<<lidar_count<<",\n\"livox_imu_written\":"<<livox_imu_count<<",\n\"video_sequence_gaps\":"<<sequence_gaps<<",\n\"video_timestamp_backwards\":"<<video_backwards<<",\n\"video_timestamp_duplicates\":"<<video_duplicates<<",\n\"video_long_intervals\":"<<video_long<<",\n\"invalid_video_buffers\":"<<bad_video<<",\n\"imu_timestamp_backwards\":"<<imu_backwards<<",\n\"imu_timestamp_duplicates\":"<<imu_duplicates<<",\n\"anchor_states_written\":"<<anchor_count<<",\n\"anchor_poll_skipped_states\":"<<skipped_anchors<<",\n\"queue_peak_bytes\":"<<peak<<",\n\"queue_overflows\":"<<overflows<<",\n\"anchor_poll_count\":"<<poll_count<<",\n\"anchor_max_poll_interval_ns\":"<<poll_max_interval<<",\n\"anchor_max_wake_lateness_ns\":"<<poll_max_lateness<<",\n\"anchor_duplicate_reads\":"<<poll_duplicate_reads<<",\n\"anchor_torn_reads\":"<<poll_torn_reads<<",\n\"imu_time_valid_reports\":"<<imu_time_valid<<",\n\"imu_time_invalid_reports\":"<<imu_time_invalid<<",\n\"imu_time_unconfirmed_reports\":"<<imu_time_unconfirmed<<",\n\"imu_time_segments\":"<<imu_time_segments<<",\n\"low_level_diagnostics_version\":1,\n\"video_io_events_written\":"<<video_io_written<<",\n\"hid_io_events_written\":"<<hid_io_written<<"\n}\n";
  if(failed){std::ofstream why(dir+"/failure.txt");why<<failure<<'\n';}
  return failed?2:0;
 }
};
int main(int argc,char** argv){ros::init(argc,argv,"zed_capture");try{Recorder r;return r.run();}catch(const std::exception& e){ROS_FATAL_STREAM(e.what());return 2;}}
