// Small real-data replay only. No ROS master, hardware, altered timestamps or full bag copy.
#include "zed_capture/jpeg_shadow.hpp"
#include <rosbag/bag.h>
#include <rosbag/view.h>
#include <map>
#include <thread>
#include <fstream>
#include <iostream>
#include <sys/stat.h>
#include "zed_capture/core.hpp"
extern "C" capture::JpegShadow* create_jpeg_files(const char*,int);
int main(int argc,char**argv){if(argc!=3)return 2;std::string out=argv[2];if(mkdir(out.c_str(),0750))return 3;ros::Time::init();rosbag::Bag src;src.open(argv[1],rosbag::bagmode::Read);rosbag::View video_start(src,rosbag::TopicQuery(std::vector<std::string>{"/zed2i/video_stamp"}));const auto begin=video_start.getBeginTime();const auto end=begin+ros::Duration(.5);rosbag::View view(src,begin,end);rosbag::Bag sensors;sensors.open(out+"/sensors.bag",rosbag::bagmode::Write);
 std::unique_ptr<capture::JpegShadow> pipe(create_jpeg_files(out.c_str(),1000));
 std::map<uint32_t,zed_capture::VideoStamp::ConstPtr> metas;std::map<uint32_t,sensor_msgs::Image::ConstPtr> left,right;
 for(const auto& m:video_start){auto x=m.instantiate<zed_capture::VideoStamp>();if(x->pair_id>3)break;metas[x->v4l2_sequence]=x;}
 int count=0;std::ofstream provenance(out+"/replay.json");
 for(const auto& m:view){auto topic=m.getTopic();if(topic=="/zed2i/video_stamp"){auto x=m.instantiate<zed_capture::VideoStamp>();if(x->pair_id<=3){metas[x->v4l2_sequence]=x;sensors.write(topic,m.getTime(),m);}continue;}
  if(topic=="/zed2i/left/image_raw"){auto x=m.instantiate<sensor_msgs::Image>();if(metas.count(x->header.seq))left[x->header.seq]=x;continue;}
  if(topic=="/zed2i/right/image_raw"){auto x=m.instantiate<sensor_msgs::Image>();if(metas.count(x->header.seq))right[x->header.seq]=x;continue;}
  if(m.getDataType()=="sensor_msgs/Image"||m.getDataType()=="sensor_msgs/CompressedImage")continue;sensors.write(topic,m.getTime(),m);
 }
 for(const auto& m:metas){if(!left.count(m.first)||!right.count(m.first))return 5;pipe->submit({m.second,left.at(m.first),right.at(m.first),capture::now(CLOCK_MONOTONIC),true});++count;std::this_thread::sleep_for(std::chrono::milliseconds(35));}
 pipe->finish();sensors.close();provenance<<"{\"software_replay\":true,\"synthetic_pixels\":false,\"pairs\":"<<count<<",\"hardware_test\":false,\"nonimage_window_seconds\":0.5}\n";if(pipe->failed()||count!=3)return 4;std::cout<<"REAL_DATA_SOFTWARE_REPLAY_PASS pairs="<<count<<"\n";
}
