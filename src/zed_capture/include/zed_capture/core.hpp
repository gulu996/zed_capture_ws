#pragma once
#include <array>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>
#include <time.h>
namespace capture {
inline uint64_t now(clockid_t id) { timespec t{}; if(clock_gettime(id,&t)) throw std::runtime_error("clock_gettime"); return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec; }
// Protocol IMA1 v1, little endian, exactly 64 bytes. Never write the source file.
struct Anchor {
 uint32_t magic=0,version=0; uint64_t epoch=0,seq=0,device=0,host=0,updated=0;
 uint32_t source=0,ready=0; uint64_t uncertainty=0;
};
static_assert(sizeof(Anchor)==64,"anchor ABI");
inline std::string validity(const Anchor& a,uint64_t mono,uint64_t max_age=100000000ULL) {
 if(a.magic!=0x31414d49 || a.version!=1) return "BAD_PROTOCOL";
 if(a.seq&1) return "TORN";
 if(!a.ready || !a.epoch || !a.device || !a.host) return "NOT_READY";
 if(a.source!=1 && a.source!=2) return "UNKNOWN_CLOCK";
 if(a.host>mono || a.updated>mono || a.updated<a.host) return "HOST_CLOCK_INVALID";
 if(mono-a.host>max_age || mono-a.updated>max_age) return "STALE";
 return "HOST_ARRIVAL_ANCHOR"; // explicitly NOT exposure/PPS correspondence
}
inline uint64_t ticksToNs(uint64_t ticks) {
 __uint128_t n=__uint128_t(ticks)*78125/2;
 if(n>UINT64_MAX) throw std::overflow_error("IMU tick conversion overflow");
 return uint64_t(n);
}
// Keep an absolute cadence, skipping expired deadlines instead of busy catch-up.
inline uint64_t nextPollDeadline(uint64_t previous,uint64_t finished,uint64_t period=1000000ULL) {
 uint64_t next=previous+period;
 if(next<=finished)next+=((finished-next)/period+1)*period;
 return next;
}
inline void splitYuyv(const uint8_t* data,size_t bytes,uint32_t width,uint32_t height,uint32_t stride,
                     std::vector<uint8_t>& left,std::vector<uint8_t>& right) {
 if(!data || width%4 || !height || stride<uint64_t(width)*2 || bytes<uint64_t(stride)*height)
  throw std::runtime_error("invalid stereo YUYV layout");
 const size_t half_bytes=width; // stereo width/2 pixels, 2 bytes/pixel
 left.resize(half_bytes*height);right.resize(half_bytes*height);
 for(size_t y=0;y<height;y++) { std::memcpy(left.data()+y*half_bytes,data+y*stride,half_bytes);
  std::memcpy(right.data()+y*half_bytes,data+y*stride+half_bytes,half_bytes); }
}
inline std::string hex(const uint8_t* data,size_t size) {
 static const char* d="0123456789abcdef";std::string s(size*2,'0');
 for(size_t i=0;i<size;i++){s[2*i]=d[data[i]>>4];s[2*i+1]=d[data[i]&15];}return s;
}
}
