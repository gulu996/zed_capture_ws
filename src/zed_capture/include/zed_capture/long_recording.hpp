#pragma once
#include <cstdint>
#include <cmath>
#include <stdexcept>
#include <string>
namespace capture {
inline void validateLongRecording(bool on,bool files,bool shadow,const std::string& resolution,double duration,double reserve){
 if(on&&(!files||shadow||resolution!="HD720"||!std::isfinite(duration)||duration<=0||duration>300||!std::isfinite(reserve)||reserve<10))
  throw std::runtime_error("C5-G requires HD720 JPEG files, duration<=300s and reserve>=10GB");
}
inline bool diskReserveReached(uint64_t free,uint64_t reserve,uint64_t queued_bound){
 // Reserve includes room for bounded outstanding jobs and metadata/final indexes.
 return free<reserve || free-reserve<queued_bound+64ULL*1024*1024;
}
constexpr uint64_t longBagLimit=8ULL*1000*1000*1000;
inline bool bagLimitReached(uint64_t size,uint64_t limit=longBagLimit){return size>=limit;}
}
