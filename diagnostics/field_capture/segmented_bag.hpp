#pragma once
// Single writer only. No background writer, no timestamp modification.
#include <rosbag/bag.h>
#include <ros/message_traits.h>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <map>
#include <memory>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdexcept>
namespace field_capture {
class SegmentedBag {
 struct Topic {std::string type,md5;uint64_t count=0;};
 std::unique_ptr<rosbag::Bag> bag;
 std::string dir,name;uint64_t limit=512ULL*1024*1024,part=0,count=0,total=0,first=0,last=0,min_time=0,max_time=0;
 std::map<std::string,Topic> topics;std::ofstream journal;bool finished=false;
 static std::string quote(const std::string& s){std::string o="\"";for(unsigned char c:s){if(c<32)throw std::runtime_error("invalid segment metadata");if(c=='"'||c=='\\')o+='\\';o+=c;}return o+'"';}
 static void sync(const std::string& s,bool directory=false){int fd=::open(s.c_str(),O_RDONLY|O_CLOEXEC|(directory?O_DIRECTORY:0));if(fd<0)throw std::runtime_error("segment sync open: "+s);int rc=::fsync(fd);int cl=::close(fd);if(rc||cl)throw std::runtime_error("segment sync failed: "+s);}
 void next(){
  ++part;std::ostringstream n;if(part==1)n<<"sensors.bag";else n<<"sensors_"<<std::setw(9)<<std::setfill('0')<<part<<".bag";name=n.str();
  if(access((dir+'/'+name).c_str(),F_OK)==0||access(activePath().c_str(),F_OK)==0)throw std::runtime_error("refuse existing segment");
  bag.reset(new rosbag::Bag);bag->open(activePath(),rosbag::bagmode::Write);bag->setCompression(rosbag::compression::Uncompressed);bag->setChunkThreshold(8*1024*1024);
  count=first=last=min_time=max_time=0;topics.clear();
 }
 void seal(){
  bag->close();sync(activePath());if(::rename(activePath().c_str(),(dir+'/'+name).c_str()))throw std::runtime_error("segment rename failed");sync(dir,true);
  struct stat st{};if(stat((dir+'/'+name).c_str(),&st))throw std::runtime_error("segment stat failed");
  journal<<"{\"segment\":"<<part<<",\"file\":"<<quote(name)<<",\"messages\":"<<count<<",\"first_message_ordinal\":"<<(count?total-count+1:0)<<",\"last_message_ordinal\":"<<total<<",\"first_record_ns\":"<<first<<",\"last_record_ns\":"<<last<<",\"min_record_ns\":"<<min_time<<",\"max_record_ns\":"<<max_time<<",\"bytes\":"<<st.st_size<<",\"closed\":true,\"topics\":{";
  bool comma=false;for(const auto& kv:topics){if(comma)journal<<',';comma=true;journal<<quote(kv.first)<<":{\"datatype\":"<<quote(kv.second.type)<<",\"md5\":"<<quote(kv.second.md5)<<",\"messages\":"<<kv.second.count<<'}';}
  journal<<"}}\n";journal.flush();sync(dir+"/bag_segments.jsonl");bag.reset();
 }
 public:
 explicit SegmentedBag(uint64_t bytes=512ULL*1024*1024):limit(bytes){if(!limit)throw std::runtime_error("zero segment budget");}
 std::string activePath()const{return dir+'/'+name+".active";}
 void open(const std::string& path,uint32_t){dir=path.substr(0,path.find_last_of('/'));
  for(auto f:{"bag_segments.jsonl","bag_segments.json"})if(access((dir+'/'+f).c_str(),F_OK)==0)throw std::runtime_error("refuse existing segment index");
  journal.exceptions(std::ios::badbit|std::ios::failbit);journal.open(dir+"/bag_segments.jsonl");next();
 }
 void setCompression(rosbag::compression::CompressionType){} // fixed Uncompressed
 void setChunkThreshold(uint32_t){} // fixed 8 MiB, included in budget overshoot
 uint64_t getSize()const{return bag?bag->getSize():0;}
 template<class M> void write(const std::string& topic,const ros::Time& t,const M& m){
  if(!bag||finished)throw std::runtime_error("write to closed segmented bag");
  if(count&&(bag->getSize()>=limit||count>=250000)){seal();next();}
  auto it=topics.find(topic);
  std::string type=ros::message_traits::DataType<M>::value(m),md5=ros::message_traits::MD5Sum<M>::value(m);
  if(it==topics.end()){if(topics.size()>=128)throw std::runtime_error("segment topic bound exceeded");Topic v;v.type=type;v.md5=md5;it=topics.emplace(topic,v).first;}
  else if(it->second.type!=type||it->second.md5!=md5)throw std::runtime_error("topic type changed in segment");
  bag->write(topic,t,m);++count;++total;++it->second.count;last=t.toNSec();if(count==1)first=min_time=max_time=last;min_time=std::min(min_time,last);max_time=std::max(max_time,last);
 }
 void close(){if(finished)return;if(bag)seal();journal.close();
  // Stream final manifest from durable journal; no growing segment vector.
  std::ifstream in(dir+"/bag_segments.jsonl");std::ofstream out;out.exceptions(std::ios::badbit|std::ios::failbit);out.open(dir+"/bag_segments.json.tmp");
  out<<"{\"version\":1,\"session_id\":"<<quote(dir.substr(dir.find_last_of('/')+1))<<",\"all_closed\":true,\"segment_message_limit\":250000,\"segment_limit_bytes\":"<<limit<<",\"message_count\":"<<total<<",\"segments\":[";
  std::string line;bool comma=false;while(std::getline(in,line)){if(comma)out<<',';comma=true;out<<line;}if(!in.eof())throw std::runtime_error("segment index read failed");
  out<<"]}\n";out.close();sync(dir+"/bag_segments.json.tmp");if(::rename((dir+"/bag_segments.json.tmp").c_str(),(dir+"/bag_segments.json").c_str()))throw std::runtime_error("segment manifest rename failed");sync(dir,true);finished=true;
 }
};
}
