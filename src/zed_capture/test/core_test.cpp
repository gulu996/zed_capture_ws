#include "zed_capture/core.hpp"
#include <cassert>
#include <iostream>
int main(){
 using namespace capture;
 Anchor a;assert(validity(a,1000)=="BAD_PROTOCOL");
 a.magic=0x31414d49;a.version=1;a.epoch=1;a.seq=2;a.device=100;a.host=10;a.updated=11;a.source=2;a.ready=1;
 assert(validity(a,12)=="HOST_ARRIVAL_ANCHOR");
 assert(validity(a,200000000)=="STALE");a.seq=3;assert(validity(a,12)=="TORN");a.seq=4;a.host=15;assert(validity(a,12)=="HOST_CLOCK_INVALID");
 assert(ticksToNs(1)==39062);assert(ticksToNs(2)==78125);
 assert(ticksToNs(100000000001ULL)==3906250000039062ULL);
 a.host=90;a.updated=110;a.seq=4;
 assert(validity(a,100)=="HOST_CLOCK_INVALID"); // writer updated during our read
 assert(validity(a,120)=="HOST_ARRIVAL_ANCHOR"); // evaluate completed snapshot at read-end
 a.updated=130;assert(validity(a,120)=="HOST_CLOCK_INVALID"); // still reject true future data
 assert(nextPollDeadline(100,120,100)==200);
 assert(nextPollDeadline(100,200,100)==300);
 assert(nextPollDeadline(100,450,100)==500);
 const uint8_t raw[]={1,2,3,4,5,6,7,8,99,99,11,12,13,14,15,16,17,18,88,88};
 std::vector<uint8_t> l,r;splitYuyv(raw,20,4,2,10,l,r);
 assert((l==std::vector<uint8_t>{1,2,3,4,11,12,13,14}));assert((r==std::vector<uint8_t>{5,6,7,8,15,16,17,18}));
 bool threw=false;try{splitYuyv(raw,19,4,2,10,l,r);}catch(...){threw=true;}assert(threw);
 std::cout<<"SOFTWARE_TESTED synthetic unit fixtures: anchor validation, tick precision, lossless stereo splitting\n";
}
