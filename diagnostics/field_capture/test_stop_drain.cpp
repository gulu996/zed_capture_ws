// SYNTHETIC offline SIGINT + production queue -> actual rosbag round trip.
// No NodeHandle/roscore, camera, UART or hardware is started.
#include "field_stop.hpp"
#include "zed_capture/recording_queue.hpp"
#include "zed_capture/long_recording.hpp"
#include <ros/ros.h>
#include <rosbag/bag.h>
#include <rosbag/view.h>
#include <sensor_msgs/Imu.h>
#include <cassert>
#include <thread>
#include <fstream>
#include <unistd.h>
int main(int argc,char** argv){
 assert(argc==2);ros::init(argc,argv,"c5i_offline_stop_drain",ros::init_options::NoSigintHandler);
 ros::Time::init();field_capture::install();assert(!field_capture::stopping());
 assert(!ros::isShuttingDown());raise(SIGINT);assert(field_capture::stopping());
 assert(!ros::isShuttingDown());raise(SIGTERM);assert(!ros::isShuttingDown());
 std::mutex mutex;std::condition_variable cond;std::deque<capture::RecordingJob> q;
 size_t bytes=0,peak=0;bool closed=false;rosbag::Bag bag;bag.open(argv[1],rosbag::bagmode::Write);
 std::thread writer([&]{capture::recordingDrain(mutex,cond,q,bytes,closed);});
 // Messages received after stop request must still drain until producer join.
 for(unsigned i=0;i<100;++i){sensor_msgs::Imu m;m.header.seq=i;m.header.stamp=ros::Time(1234567890,i*5000000);
  std::lock_guard<std::mutex> l(mutex);
  assert(capture::recordingEnqueue(q,bytes,peak,1048576,false,false,512,[&,m]{bag.write("/SYNTHETIC/livox/imu",m.header.stamp,m);})==capture::EnqueueResult::Accepted);
  cond.notify_one();}
 {std::lock_guard<std::mutex> l(mutex);closed=true;}cond.notify_one();writer.join();bag.close();assert(bytes==0);
 rosbag::Bag input;input.open(argv[1],rosbag::bagmode::Read);unsigned n=0;
 for(auto& record:rosbag::View(input)){auto m=record.instantiate<sensor_msgs::Imu>();assert(m&&m->header.seq==n&&m->header.stamp.nsec==n*5000000);++n;}
 assert(n==100);input.close();
 assert(capture::bagLimitReached(8000000000ULL));assert(!capture::bagLimitReached(7999999999ULL));
 assert(capture::diskReserveReached(10000000000ULL,10000000000ULL,256ULL*1024*1024));
 std::cout<<"SYNTHETIC PASS: real SIGINT/TERM leaves ROS shutdown false; production bounded writer drains 100 messages; bag reopens; integer stamps unchanged; disk and 8GB protections retained\n";
}
