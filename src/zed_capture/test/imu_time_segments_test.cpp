#include "zed_capture/imu_time_segments.hpp"
#include <cassert>
#include <fstream>
#include <iostream>
#include <sstream>
#include <set>
using capture::ImuTimeSegments;
int main(int argc,char**argv){
 if(argc==3){ // Read-only replay. Output is exclusive by caller; never writes session data.
  std::ifstream in(argv[1]);std::ofstream out(argv[2],std::ios::app);
  if(!in||!out||out.tellp()!=0)return 2;
  out<<"sample_id,segment_id,decision_sample_id,time_validity,reason\n";
  ImuTimeSegments g;std::string line;std::getline(in,line);size_t count=0,decided=0;
  auto emit=[&](const std::vector<capture::ImuTimeDecision>& ds){for(auto& d:ds){out<<d.sample<<','<<d.segment<<','<<d.decision_sample<<','<<d.state<<','<<d.reason<<'\n';++decided;}};
  while(std::getline(in,line)){std::stringstream s(line);std::vector<std::string> v;std::string f;while(std::getline(s,f,','))v.push_back(f);
   if(v.size()!=7)return 2;emit(g.add(std::stoull(v[0]),std::stoull(v[1]),std::stoull(v[3]),v[5]=="1"||v[5]==std::string(1,'\1')));++count;}
  emit(g.finish());assert(count==decided);std::cout<<"historical raw reports="<<count<<" classified="<<decided<<'\n';return out?0:2;
 }
 // SYNTHETIC regression using the measured first two ticks and arrival delta.
 ImuTimeSegments g;assert(g.add(1,17005120,1000000000,true).empty());
 auto d=g.add(2,29429285,1000864830,true);assert(d.size()==1&&d[0].sample==1&&d[0].state=="INVALID_SUSPECT");
 size_t good=0;for(uint64_t i=3;i<=20;++i)for(auto& x:g.add(i,29429285+(i-2)*64,1000864830+(i-2)*2468500,true)){assert(x.segment==2&&x.state=="VALID_CONTIGUOUS");++good;}
 assert(good==19&&g.finish().empty());
 ImuTimeSegments normal;std::set<uint64_t> seen;
 for(uint64_t i=1;i<=1000;++i)for(auto& x:normal.add(i,1000+i*64,1000000000+i*2468500,true)){assert(x.segment==1&&x.state=="VALID_CONTIGUOUS");assert(seen.insert(x.sample).second);}
 assert(seen.size()==1000&&normal.finish().empty());
 auto reset=normal.add(1001,1,4000000000,true);assert(reset.empty());
 auto end=normal.finish();assert(end.size()==1&&end[0].segment==2&&end[0].state=="UNCONFIRMED");
 ImuTimeSegments burst;size_t total=0;
 for(uint64_t i=1;i<=100;++i)total+=burst.add(i,1000+i*64,1000000000+i,true).size();
 total+=burst.finish().size();assert(total==100); // bounded startup burst, nothing silently discarded
 auto bad=burst.add(101,0,2000000000,false);assert(bad.size()==1&&bad[0].state=="INVALID_SENSOR");
 ImuTimeSegments dup;dup.add(1,10,1000000000,true);auto r=dup.add(2,10,1002000000,true);assert(r.size()==1&&r[0].state=="INVALID_SUSPECT");
 std::cout<<"SYNTHETIC: startup jump, continuous 1.28% scaling, reset, duplicate, bounded burst and shutdown PASS\n";
}
