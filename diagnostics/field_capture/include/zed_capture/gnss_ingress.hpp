#pragma once
#include "segmented_bag.hpp"
#include <topic_tools/shape_shifter.h>
#include <array>
#include <atomic>
#include <functional>
#include <sstream>
namespace capture {
struct GnssType {const char* topic;const char* datatype;const char* md5;};
inline const std::array<GnssType,5>& gnssTypes(){static const std::array<GnssType,5> t{{
 {"/gnss/raw","sensor_time_msgs/RawSerialFrame","b3f0843fc91b42663f3ec3c977e3095b"},
 {"/gnss/status_v2","gnss_serial_driver/GnssStatus","89bd2929a7a8274c1f46b1f399c930ec"},
 {"/gnss/pvt_local","gnss_serial_driver/GnssPvtStamped","bdfb1e39cf636dda7ac090d7feb65573"},
 {"/ublox_driver/receiver_pvt","gnss_comm/GnssPVTSolnMsg","d18171357d7a159f76d4d7c0b12fb631"},
 {"/sensor_time/utc_observation","sensor_time_msgs/UtcObservation","55266fcd72cb453b63ebcad49e53171a"}}};return t;}
struct GnssCounts {std::atomic<uint64_t> received{0},enqueued{0},written{0},rejected{0},serialization_errors{0},write_errors{0};};
class GnssIngress {
 field_capture::SegmentedBag& bag;
 std::function<bool(size_t,std::function<void()>)> enqueue;
 std::function<void(const std::string&)> fail;
 public:
 std::array<GnssCounts,5> counts;
 GnssIngress(field_capture::SegmentedBag& b,std::function<bool(size_t,std::function<void()>)> q,
  std::function<void(const std::string&)> f):bag(b),enqueue(q),fail(f){}
 bool receive(size_t i,const topic_tools::ShapeShifter::ConstPtr& m,const ros::Time& reception){
  if(i>=5)throw std::out_of_range("GNSS topic index");auto& c=counts[i];++c.received;
  if(!m){++c.rejected;++c.serialization_errors;fail("GNSS missing serialized message");return false;}
  if(m->getDataType()!=gnssTypes()[i].datatype||m->getMD5Sum()!=gnssTypes()[i].md5){
   ++c.rejected;fail(std::string("GNSS datatype/MD5 rejected: ")+gnssTypes()[i].topic);return false;}
  try {
   if(m->size()==0||m->size()>65536)throw std::runtime_error("GNSS serialized size outside 1..65536");
   // ShapeShifter already owns the serialized bytes; immutable shared ownership
   // survives callback return. No camera/MMAP ownership or JPEG lock involved.
   bool accepted=enqueue(m->size()+1024,[this,i,m,reception]{
    try{bag.write(gnssTypes()[i].topic,reception,*m);++counts[i].written;}
    catch(...){++counts[i].write_errors;fail(std::string("GNSS bag write error: ")+gnssTypes()[i].topic);throw;}
   });
   if(accepted)++c.enqueued;else{++c.rejected;fail(std::string("GNSS recording queue refused: ")+gnssTypes()[i].topic);}return accepted;
  }catch(const ros::serialization::StreamOverrunException&){++c.serialization_errors;++c.rejected;fail("GNSS serialization error");return false;}
  catch(const std::exception& e){++c.serialization_errors;++c.rejected;fail(std::string("GNSS enqueue/serialization: ")+e.what());return false;}
 }
 bool complete()const{for(auto& c:counts)if(c.received!=c.written||c.rejected||c.serialization_errors||c.write_errors)return false;return true;}
 std::string json()const{std::ostringstream s;s<<"{\"mapping_status\":\"PENDING\",\"topics\":{";
  for(size_t i=0;i<5;++i){auto& c=counts[i];if(i)s<<',';s<<'"'<<gnssTypes()[i].topic<<"\":{\"received\":"<<c.received<<",\"enqueued\":"<<c.enqueued<<",\"written\":"<<c.written<<",\"rejected\":"<<c.rejected<<",\"serialization_errors\":"<<c.serialization_errors<<",\"write_errors\":"<<c.write_errors<<'}';}
  s<<"},\"complete\":"<<(complete()?"true":"false")<<"}\n";return s.str();}
};
}
