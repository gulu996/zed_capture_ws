// SYNTHETIC tests only: no device open, STREAMON, or real ioctl calls.
#include <sys/ioctl.h>
#include "native_mode.hpp"
#include <cassert>
#include <iostream>
#include <sstream>
int main(){
 auto hd=NativeMode::parse("HD720");assert(hd.width==2560 && hd.height==720 && hd.bytes()==3686400);
 assert(NativeMode::parse("HD1080").bytes()==8294400);
 bool rejected=false;try{NativeMode::parse("VGA");}catch(const std::exception&){rejected=true;}assert(rejected);
 assert(enumThirty(1,30) && enumThirty(333333,10000000) && !enumThirty(1,15) && !enumThirty(1,60) && !enumThirty(0,0));
 v4l2_format f{};f.fmt.pix.width=2560;f.fmt.pix.height=720;f.fmt.pix.bytesperline=5120;f.fmt.pix.sizeimage=3686400;f.fmt.pix.pixelformat=V4L2_PIX_FMT_YUYV;
 v4l2_streamparm p{};p.parm.capture.timeperframe={1,30};assert(hd.matches(f,p));
 f.fmt.pix.width=3840;assert(!hd.matches(f,p));f.fmt.pix.width=2560;
 p.parm.capture.timeperframe={1,15};assert(!hd.matches(f,p));p.parm.capture.timeperframe={1,30};
 f.fmt.pix.pixelformat=V4L2_PIX_FMT_MJPEG;assert(!hd.matches(f,p));f.fmt.pix.pixelformat=V4L2_PIX_FMT_YUYV;
 f.fmt.pix.bytesperline++;assert(!hd.matches(f,p));f.fmt.pix.bytesperline--;
 f.fmt.pix.sizeimage++;assert(!hd.matches(f,p));
 auto mock=[](unsigned long cmd,void* data)->int{
  if(cmd==VIDIOC_ENUM_FMT){auto& x=*static_cast<v4l2_fmtdesc*>(data);if(!x.index){x.pixelformat=V4L2_PIX_FMT_YUYV;return 0;}}
  if(cmd==VIDIOC_ENUM_FRAMESIZES){auto& x=*static_cast<v4l2_frmsizeenum*>(data);if(!x.index){x.type=V4L2_FRMSIZE_TYPE_DISCRETE;x.discrete={2560,720};return 0;}}
  if(cmd==VIDIOC_ENUM_FRAMEINTERVALS){auto& x=*static_cast<v4l2_frmivalenum*>(data);if(!x.index){x.type=V4L2_FRMIVAL_TYPE_DISCRETE;x.discrete={333333,10000000};return 0;}}
  errno=EINVAL;return -1;
 };
 std::ostringstream good,wrong,denied,bounded;
 assert(enumerateNative(hd,good,mock));assert(!enumerateNative(NativeMode::parse("HD1080"),wrong,mock));
 assert(!enumerateNative(hd,denied,[](unsigned long,void*){errno=EACCES;return -1;}));
 int calls=0;assert(!enumerateNative(hd,bounded,[&](unsigned long,void*){++calls;return 0;}));assert(calls==64+256+128);
 std::cout<<"SYNTHETIC PASS: modes, exact negotiated format/rate, enumeration errors, bounds and descriptor quantization\n"<<good.str();
}
