// SYNTHETIC, no ROS master/camera/bag. Compile the actual codec implementation.
#include "../src/jpeg_shadow.cpp"
#include <boost/make_shared.hpp>
#include <iostream>
int main(){
 std::thread t([]{
  Codec codec;auto m=boost::make_shared<zed_capture::VideoStamp>();
  auto l=boost::make_shared<sensor_msgs::Image>(),r=boost::make_shared<sensor_msgs::Image>();
  for(auto im:{l,r}){im->width=1280;im->height=720;im->encoding="8UC2";im->step=2560;im->data.resize(1843200);
   for(size_t k=0;k<im->data.size();k+=4){im->data[k]=16+(k/4)%220;im->data[k+1]=100;im->data[k+2]=16+(k/16)%220;im->data[k+3]=150;}}
  capture::ShadowInput in{m,l,r,0,true};
  std::cout<<"synthetic,iteration,convert_ns,encode_ns,total_ns\n";
  for(int i=0;i<6;++i){auto start=capture::now(CLOCK_MONOTONIC);auto x=codec(in);auto end=capture::now(CLOCK_MONOTONIC);std::cout<<"true,"<<i<<','<<x.convert_ns<<','<<x.encode_ns<<','<<end-start<<'\n';}
 });t.join();
}
