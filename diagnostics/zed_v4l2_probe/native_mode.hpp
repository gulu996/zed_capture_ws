#pragma once
// Probe only. Never modifies the production library or camera controls.
#include <linux/videodev2.h>
#include <cerrno>
#include <cstdint>
#include <ostream>
#include <stdexcept>
#include <string>
struct NativeMode {
 std::string name; uint32_t width,height;
 static NativeMode parse(const std::string& s){
  if(s=="HD1080")return {s,3840,1080};
  if(s=="HD720")return {s,2560,720};
  throw std::runtime_error("resolution must be HD1080 or HD720");
 }
 uint32_t bytes()const{return width*height*2;}
 bool matches(const v4l2_format& f,const v4l2_streamparm& p)const{
  const auto& v=f.fmt.pix;const auto& t=p.parm.capture.timeperframe;
  return v.width==width && v.height==height && v.pixelformat==V4L2_PIX_FMT_YUYV &&
   v.bytesperline==width*2 && v.sizeimage==bytes() && t.numerator && uint64_t(t.numerator)*30==t.denominator;
 }
};
// ENUM may expose the integer 100 ns UVC descriptor interval (333333 units).
// This quantization check does NOT relax G_PARM, frame-gap or mapping thresholds.
inline bool enumThirty(uint32_t n,uint32_t d){
 if(!n || !d)return false;
 long double ns=static_cast<long double>(n)*1000000000.L/d;
 return ns>=1000000000.L/30-100 && ns<=1000000000.L/30+100;
}
template<class Query> bool enumerateNative(const NativeMode& mode,std::ostream& out,Query query){
 bool yuyv=false,size=false,rate=false,fmt_end=false,size_end=false,rate_end=false;
 out<<"{\"requested\":\""<<mode.name<<"\",\"width\":"<<mode.width<<",\"height\":"<<mode.height
    <<",\"pixel_format\":\"YUYV\",\"scope\":\"all capture formats; all YUYV sizes; requested YUYV size intervals\","
      "\"interval_policy\":\"ENUM: 1/30 with 100ns descriptor quantization; G_PARM: exact 30fps\",\"VIDIOC_ENUM_FMT\":[";
 for(uint32_t i=0;i<64;++i){
  v4l2_fmtdesc f{};f.index=i;f.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
  int r=query(VIDIOC_ENUM_FMT,&f),e=r<0?errno:0;if(i)out<<',';
  out<<"{\"index\":"<<i<<",\"result\":"<<r<<",\"errno\":"<<e<<",\"fourcc\":"<<f.pixelformat<<",\"flags\":"<<f.flags<<'}';
  if(r<0){fmt_end=e==EINVAL;break;}if(f.pixelformat==V4L2_PIX_FMT_YUYV)yuyv=true;
 }
 out<<"],\"VIDIOC_ENUM_FRAMESIZES\":[";
 for(uint32_t i=0;i<256;++i){
  v4l2_frmsizeenum f{};f.index=i;f.pixel_format=V4L2_PIX_FMT_YUYV;
  int r=query(VIDIOC_ENUM_FRAMESIZES,&f),e=r<0?errno:0;if(i)out<<',';
  out<<"{\"index\":"<<i<<",\"result\":"<<r<<",\"errno\":"<<e<<",\"type\":"<<f.type;
  if(r==0 && f.type==V4L2_FRMSIZE_TYPE_DISCRETE){
   out<<",\"width\":"<<f.discrete.width<<",\"height\":"<<f.discrete.height;
   if(f.discrete.width==mode.width && f.discrete.height==mode.height)size=true;
  }else if(r==0){
   const auto& s=f.stepwise;
   out<<",\"min_width\":"<<s.min_width<<",\"max_width\":"<<s.max_width<<",\"step_width\":"<<s.step_width
      <<",\"min_height\":"<<s.min_height<<",\"max_height\":"<<s.max_height<<",\"step_height\":"<<s.step_height;
  }
  out<<'}';if(r<0){size_end=e==EINVAL;break;}
 }
 out<<"],\"VIDIOC_ENUM_FRAMEINTERVALS\":[";
 for(uint32_t i=0;i<128;++i){
  v4l2_frmivalenum f{};f.index=i;f.pixel_format=V4L2_PIX_FMT_YUYV;f.width=mode.width;f.height=mode.height;
  int r=query(VIDIOC_ENUM_FRAMEINTERVALS,&f),e=r<0?errno:0;if(i)out<<',';
  out<<"{\"index\":"<<i<<",\"result\":"<<r<<",\"errno\":"<<e<<",\"type\":"<<f.type;
  if(r==0 && f.type==V4L2_FRMIVAL_TYPE_DISCRETE){
   out<<",\"numerator\":"<<f.discrete.numerator<<",\"denominator\":"<<f.discrete.denominator;
   if(enumThirty(f.discrete.numerator,f.discrete.denominator))rate=true;
  }else if(r==0){
   const auto& s=f.stepwise;
   out<<",\"min_numerator\":"<<s.min.numerator<<",\"min_denominator\":"<<s.min.denominator
      <<",\"max_numerator\":"<<s.max.numerator<<",\"max_denominator\":"<<s.max.denominator
      <<",\"step_numerator\":"<<s.step.numerator<<",\"step_denominator\":"<<s.step.denominator;
  }
  out<<'}';if(r<0){rate_end=e==EINVAL;break;}
 }
 bool complete=fmt_end&&size_end&&rate_end,verified=complete&&yuyv&&size&&rate;
 out<<"],\"enumeration_complete\":"<<(complete?"true":"false")
    <<",\"yuyv_listed\":"<<(yuyv?"true":"false")<<",\"discrete_size_listed\":"<<(size?"true":"false")
    <<",\"discrete_30fps_listed\":"<<(rate?"true":"false")<<",\"requested_mode_enumerated\":"<<(verified?"true":"false")<<"}\n";
 return verified; // Unknown/stepwise-only support is recorded but not claimed verified.
}
