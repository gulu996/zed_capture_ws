#pragma once
#include <cstdint>
#include <deque>
#include <string>
#include <vector>

namespace capture {
// Acquisition-quality segmentation, NOT L2-B mapping or physical synchronization.
// Every input gets exactly one final classification. Raw data is recorded separately.
struct ImuTimeDecision {
 uint64_t sample,segment,decision_sample;
 std::string state,reason;
};
class ImuTimeSegments {
 struct Sample {uint64_t id,ticks,host;};
 std::deque<Sample> pending;
 Sample previous{};
 bool have=false,confirmed=false;
 uint64_t segment=1;
 std::string start_reason="STARTUP";
 void drain(std::vector<ImuTimeDecision>& out,const std::string& state,const std::string& reason,uint64_t trigger){
  for(const auto& s:pending)out.push_back({s.id,segment,trigger,state,reason});pending.clear();
 }
 public:
 // 100 ms is a coarse discontinuity detector, not an allowed synchronization error.
 // It tolerates ordinary ~1.28% tick scaling and receive jitter without accepting
 // hundreds of seconds of device advance in a sub-millisecond host interval.
 static constexpr uint64_t delta_disagreement_ns=100000000ULL;
 static constexpr size_t max_pending=32;
 std::vector<ImuTimeDecision> add(uint64_t id,uint64_t ticks,uint64_t host,bool sensor_valid){
  std::vector<ImuTimeDecision> out;
  if(!sensor_valid){
   drain(out,"UNCONFIRMED","SENSOR_INVALID_INTERRUPTED_STARTUP",id);
   out.push_back({id,segment,id,"INVALID_SENSOR","SENSOR_INVALID_OR_MALFORMED"});
   ++segment;have=confirmed=false;start_reason="AFTER_INVALID_SENSOR";return out;
  }
  std::string boundary;
  if(have){
   if(host<=previous.host)boundary="HOST_NONINCREASING";
   else if(ticks<=previous.ticks)boundary=ticks==previous.ticks?"TICK_DUPLICATE":"TICK_RESET_OR_BACKWARD";
   else {
    // Exact integer conversion; unsigned 128 bits prevents wrap at huge tick jumps.
    __uint128_t dd=__uint128_t(ticks-previous.ticks)*78125/2,dh=host-previous.host;
    if(dd>dh+delta_disagreement_ns || dh>dd+delta_disagreement_ns)boundary="DEVICE_HOST_DELTA_DISAGREEMENT";
   }
  }
  if(!boundary.empty()){
   drain(out,"INVALID_SUSPECT","UNCONFIRMED_BEFORE_"+boundary,id);
   ++segment;confirmed=false;start_reason="AFTER_"+boundary;
  }
  previous={id,ticks,host};have=true;
  if(confirmed){out.push_back({id,segment,id,"VALID_CONTIGUOUS","CONTINUITY_ONLY_NOT_SYNC"});return out;}
  pending.push_back(previous);
  if(pending.size()>=8 && host-pending.front().host>=10000000ULL){
   drain(out,"VALID_CONTIGUOUS","CONFIRMED_"+start_reason,id);confirmed=true;
  }else if(pending.size()>=max_pending){
   const auto s=pending.front();pending.pop_front();
   out.push_back({s.id,segment,id,"UNCONFIRMED","STARTUP_BUFFER_LIMIT"});
  }
  return out;
 }
 std::vector<ImuTimeDecision> finish(){std::vector<ImuTimeDecision> out;drain(out,"UNCONFIRMED","END_BEFORE_CONTINUITY_CONFIRMED",previous.id);return out;}
};
}
