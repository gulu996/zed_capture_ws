// Offline REAL historical GNSS messages -> production C5-F queue/ingress -> bag.
// No NodeHandle, ROS master, camera, serial or synthetic hardware success.
#include "zed_capture/recording_queue.hpp"
#include "zed_capture/gnss_ingress.hpp"
#include <rosbag/view.h>
#include <boost/make_shared.hpp>
#include <thread>
#include <fstream>
#include <cassert>
#include <sys/stat.h>
#include <unistd.h>
struct Writer {
 std::mutex mutex;std::condition_variable cond;std::deque<capture::RecordingJob> queue;
 size_t queued=0,peak=0,capacity=1048576;bool closed=false;std::atomic<bool> failed{false};
 rosbag::Bag bag;capture::GnssIngress ingress;
 Writer():ingress(bag,[this](size_t n,std::function<void()> f){
  std::lock_guard<std::mutex> lock(mutex);auto result=capture::recordingEnqueue(queue,queued,peak,capacity,closed,failed,n,std::move(f));cond.notify_one();return result==capture::EnqueueResult::Accepted;
 },[this](const std::string&){failed=true;}){}
 void finish(){closed=true;cond.notify_all();capture::recordingDrain(mutex,cond,queue,queued,closed);}
};
int main(int argc,char** argv){
 assert(argc==3);ros::Time::init();std::string root=argv[2];assert(mkdir(root.c_str(),0750)==0);
 rosbag::Bag input;input.open(argv[1],rosbag::bagmode::Read);std::vector<std::pair<size_t,topic_tools::ShapeShifter::ConstPtr>> messages;std::vector<ros::Time> times;
 for(auto& m:rosbag::View(input)){
  size_t i=0;for(;i<5;++i)if(m.getTopic()==capture::gnssTypes()[i].topic)break;assert(i<5);
  messages.emplace_back(i,m.instantiate<topic_tools::ShapeShifter>());times.push_back(m.getTime());assert(messages.back().second);
 }
 assert(!messages.empty());Writer w;w.capacity=8*1024*1024;w.bag.open(root+"/sensors.bag",rosbag::bagmode::Write);w.bag.setChunkThreshold(8*1024*1024);
 std::thread thread([&]{capture::recordingDrain(w.mutex,w.cond,w.queue,w.queued,w.closed);});
 for(size_t i=0;i<messages.size();++i)assert(w.ingress.receive(messages[i].first,messages[i].second,times[i]));
 {std::lock_guard<std::mutex> lock(w.mutex);w.closed=true;}w.cond.notify_all();thread.join();w.bag.close();
 assert(!w.failed&&w.queued==0&&w.ingress.complete());for(auto& c:w.ingress.counts)assert(c.written>0);
 std::ofstream report(root+"/writer_counts.json");report<<w.ingress.json();report.close();
 std::array<std::deque<size_t>,5> expected;for(size_t i=0;i<messages.size();++i)expected[messages[i].first].push_back(i);
 rosbag::Bag read;read.open(root+"/sensors.bag",rosbag::bagmode::Read);size_t n=0;
 for(auto& m:rosbag::View(read)){
  assert(n<messages.size());size_t ti=0;for(;ti<5;++ti)if(m.getTopic()==capture::gnssTypes()[ti].topic)break;assert(ti<5&&!expected[ti].empty());
  const auto index=expected[ti].front();expected[ti].pop_front();auto original=messages[index].second;auto restored=m.instantiate<topic_tools::ShapeShifter>();
  assert(m.getTime()==times[index]);
  assert(m.getMD5Sum()==original->getMD5Sum()&&m.getDataType()==original->getDataType());
  std::vector<uint8_t> a(original->size()),b(restored->size());ros::serialization::OStream ao(a.data(),a.size()),bo(b.data(),b.size());original->write(ao);restored->write(bo);assert(a==b);++n;
 }assert(n==messages.size());read.close();
 // SYNTHETIC failures only; the valid fixture above is historical real input.
 auto raw=messages.front().second;size_t index=messages.front().first;
 Writer wrong;auto bad=boost::make_shared<topic_tools::ShapeShifter>();bad->morph("wrong-md5",raw->getDataType(),raw->getMessageDefinition(),"0");
 assert(!wrong.ingress.receive(index,bad,ros::Time(1,0))&&wrong.failed&&wrong.ingress.counts[index].rejected==1);
 Writer empty;assert(!empty.ingress.receive(index,{},ros::Time(1,0)));assert(empty.ingress.counts[index].serialization_errors==1);
 Writer full;full.capacity=1;assert(!full.ingress.receive(index,raw,ros::Time(1,0))&&full.failed&&full.queued==0);
 Writer closed;closed.closed=true;assert(!closed.ingress.receive(index,raw,ros::Time(1,0)));
 Writer disk;assert(disk.ingress.receive(index,raw,ros::Time(1,0)));bool threw=false;try{disk.finish();}catch(...){threw=true;}
 assert(threw&&disk.failed&&disk.ingress.counts[index].write_errors==1&&disk.ingress.counts[index].written==0);
 // Existing non-GNSS jobs share the exact same bounded drain, preserving FIFO.
 std::mutex mutex;std::condition_variable cond;std::deque<capture::RecordingJob> q;size_t bytes=0,peak=0;bool done=false;int order=0;
 for(int i=0;i<8;++i)assert(capture::recordingEnqueue(q,bytes,peak,128,false,false,16,[&,i]{assert(order++==i);})==capture::EnqueueResult::Accepted);
 assert(capture::recordingEnqueue(q,bytes,peak,128,false,false,1,[]{})==capture::EnqueueResult::Full);
 done=true;capture::recordingDrain(mutex,cond,q,bytes,done);assert(order==8&&bytes==0&&peak==128);
 std::ofstream result(root+"/test_result.json");result<<"{\"production_writer_roundtrip_records\":"<<n<<",\"exact_serialized_bytes_equal\":true,\"all_five_topics\":true,\"wrong_md5_rejected\":true,\"queue_full_rejected\":true,\"serialization_error_reported\":true,\"write_error_reported\":true,\"exit_drain\":true,\"old_mode_fifo\":true,\"hardware_run\":false}\n";
}
