// SYNTHETIC: exercise the unchanged production splitter at native HD720 size.
#include "zed_capture/core.hpp"
#include <cassert>
#include <iostream>
int main(){
 const unsigned width=2560,height=720,stride=5120,eye_step=2560;
 std::vector<uint8_t> raw(stride*height),left,right;
 for(unsigned y=0;y<height;++y)for(unsigned x=0;x<stride;++x)
  raw[y*stride+x]=static_cast<uint8_t>((y*13+x*7+(x>=eye_step?89:0))%251);
 capture::splitYuyv(raw.data(),raw.size(),width,height,stride,left,right);
 assert(raw.size()==3686400 && left.size()==1843200 && right.size()==1843200);
 assert(left!=right);
 for(unsigned y=0;y<height;++y)for(unsigned x=0;x<eye_step;++x){
  assert(left[y*eye_step+x]==raw[y*stride+x]);
  assert(right[y*eye_step+x]==raw[y*stride+eye_step+x]);
 }
 std::cout<<"SYNTHETIC PASS: all HD720 bytes preserve row order and left/right halves; V4L2 stride=5120, per-eye step=2560, bytes=1843200. No actual pixels verified.\n";
}
