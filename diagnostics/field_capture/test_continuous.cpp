// SYNTHETIC fault injection, no hardware or ROS master.
#include "zed_capture/jpeg_files.hpp"
#include "segmented_bag.hpp"
#include "field_stop.hpp"
#include <rosbag/view.h>
#include <sensor_msgs/Imu.h>
#include <boost/make_shared.hpp>
#include <cassert>
#include <iostream>
#include <dirent.h>
static capture::ShadowInput input(unsigned id){auto m=boost::make_shared<zed_capture::VideoStamp>();m->pair_id=id;m->v4l2_sequence=id;m->header.seq=id;m->header.stamp.fromNSec(1790000000000000000ULL+id*33333000ULL);m->v4l2_sec=m->header.stamp.sec;m->v4l2_usec=m->header.stamp.nsec/1000;m->payload_valid=true;auto l=boost::make_shared<sensor_msgs::Image>(),r=boost::make_shared<sensor_msgs::Image>();l->header=r->header=m->header;return {m,l,r,capture::now(CLOCK_MONOTONIC),true};}
static capture::FileEncoded fake(const capture::ShadowInput&){capture::FileEncoded d;d.left={255,216,255,217};d.right=d.left;d.timing={1,2,4,4,true};return d;}
static std::string read(const std::string& p){std::ifstream f(p);return {std::istreambuf_iterator<char>(f),{}};}
int main(int argc,char**argv){assert(argc==2);ros::Time::init();field_capture::install();std::string root=argv[1];assert(!mkdir(root.c_str(),0750));auto path=[&](std::string n){auto p=root+'/'+n;assert(!mkdir(p.c_str(),0750));return p;};
 // Reproduce the observed 250ms writer sync pause at fixed 30 pairs/s.
 for(int pause:{250,800}){auto p=path("sync_"+std::to_string(pause)+"ms");std::atomic<bool> injected{false};
  capture::JpegFiles w(p,fake,[]{},100,[](int fd,const void*b,size_t n){return ::write(fd,b,n);},true,[&](int fd){if(!injected.exchange(true))std::this_thread::sleep_for(std::chrono::milliseconds(pause));return ::fsync(fd);});
  const auto t=std::chrono::steady_clock::now();for(unsigned i=1;i<=40;i++){std::this_thread::sleep_until(t+std::chrono::microseconds((i-1)*33333));w.submit(input(i));}w.finish();assert(injected);assert(w.failed()==(pause==800));
  auto summary=read(p+"/jpeg_files_summary.json");assert(summary.find("\"final_synced\":true")!=std::string::npos);
  if(pause==250){assert(summary.find("\"completed\":40")!=std::string::npos);assert(summary.find("\"write_queue_rejected\":0")!=std::string::npos);}else assert(read(p+"/frames.csv").find("WRITE_QUEUE_REJECTED")!=std::string::npos);
 }
 {auto p=path("sync_error");capture::JpegFiles w(p,fake,[]{},1000,[](int fd,const void*b,size_t n){return ::write(fd,b,n);},true,[](int){errno=EIO;return -1;});w.submit(input(1));bool raised=false;try{w.finish();}catch(...){raised=true;}assert(raised&&w.failed());assert(read(p+"/jpeg_files_summary.json").find("\"final_synced\":false")!=std::string::npos);}
 // Many incremental events beyond 4096; fixed in-flight memory and sharding.
 {auto p=path("5000_events");capture::JpegFiles w(p,fake,[]{},5000,[](int fd,const void*b,size_t n){return ::write(fd,b,n);},true);
  for(unsigned i=1;i<=5000;i++){w.submit(input(i));while(w.recordedEvents()<i&&!w.failed())std::this_thread::sleep_for(std::chrono::microseconds(100));assert(!w.failed());}w.finish();assert(!w.failed());assert(w.recordedEvents()==5000);assert(access((p+"/camera/right/000004/000000005000.jpg").c_str(),F_OK)==0);
 }
 // Actual ROS bags, small test rotation threshold, unchanged Header/record stamp.
 {auto p=path("segments");field_capture::SegmentedBag b(4096);b.open(p+"/sensors.bag.active",rosbag::bagmode::Write);
  for(unsigned i=0;i<200;i++){sensor_msgs::Imu m;m.header.seq=i;m.header.stamp=ros::Time(1790000000+i*2,123456789);m.header.frame_id="SYNTHETIC";if(i==199){raise(SIGINT);assert(field_capture::stopping());}b.write("/livox/imu",ros::Time(1790000001+i*2,987654321),m);}b.close();b.close();
  unsigned expected=0,parts=0;for(unsigned part=1;;part++){std::ostringstream n;if(part==1)n<<"sensors.bag";else n<<"sensors_"<<std::setw(9)<<std::setfill('0')<<part<<".bag";if(access((p+'/'+n.str()).c_str(),F_OK))break;++parts;rosbag::Bag r(p+'/'+n.str());for(auto& row:rosbag::View(r)){auto m=row.instantiate<sensor_msgs::Imu>();assert(m&&m->header.seq==expected&&m->header.stamp==ros::Time(1790000000+expected*2,123456789)&&row.getTime()==ros::Time(1790000001+expected*2,987654321));++expected;}r.close();}
  assert(parts>1&&expected==200);bool rejected=false;try{sensor_msgs::Imu m;b.write("/livox/imu",ros::Time(1,0),m);}catch(...){rejected=true;}assert(rejected);
  field_capture::SegmentedBag other;rejected=false;try{other.open(p+"/sensors.bag.active",rosbag::bagmode::Write);}catch(...){rejected=true;}assert(rejected);
 }
 {auto p=path("segment_close_failure");field_capture::SegmentedBag b;b.open(p+"/sensors.bag.active",rosbag::bagmode::Write);sensor_msgs::Imu m;b.write("/livox/imu",ros::Time(1,0),m);assert(!mkdir((p+"/sensors.bag").c_str(),0750));bool caught=false;try{b.close();}catch(...){caught=true;}assert(caught);assert(access((p+"/bag_segments.json").c_str(),F_OK)!=0);}
 std::cout<<"SYNTHETIC PASS: 250ms sync handled, 800ms overload explicit FAIL, sync error, 5000 events, rotation exact timestamps/counts, no overwrite, close idempotent\n";
}
