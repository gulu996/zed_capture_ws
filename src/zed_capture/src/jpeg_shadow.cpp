#include "zed_capture/jpeg_files.hpp"
#include <opencv2/core.hpp>
#include <opencv2/core/ocl.hpp>
#include <opencv2/imgproc.hpp>
#include <turbojpeg.h>
#include <boost/make_shared.hpp>
namespace {
struct Codec {
 tjhandle encoder=tjInitCompress(),decoder=tjInitDecompress();
 Codec(){if(!encoder||!decoder)throw std::runtime_error("TurboJPEG init failed");cv::setNumThreads(1);cv::ocl::setUseOpenCL(false);}
 ~Codec(){if(encoder)tjDestroy(encoder);if(decoder)tjDestroy(decoder);}
 void warmup(const std::string& dir){
  for(const char* n:{"jpeg_shadow_warmup.csv","jpeg_shadow_warmup.json"})if(access((dir+"/"+n).c_str(),F_OK)==0)throw std::runtime_error("refusing existing warmup evidence");
  auto meta=boost::make_shared<zed_capture::VideoStamp>();
  auto left=boost::make_shared<sensor_msgs::Image>(),right=boost::make_shared<sensor_msgs::Image>();
  for(auto im:{left,right}){im->width=1280;im->height=720;im->step=2560;im->encoding="8UC2";im->header.frame_id="SYNTHETIC_WARMUP_NOT_SENSOR";im->data.resize(1843200);
   for(size_t k=0;k<im->data.size();k+=4){im->data[k]=16+(k/4)%220;im->data[k+1]=100;im->data[k+2]=16+(k/16)%220;im->data[k+3]=150;}}
  capture::ShadowInput in{meta,left,right,0,true};
  std::ofstream out;out.exceptions(std::ios::badbit|std::ios::failbit);out.open(dir+"/jpeg_shadow_warmup.csv");
  out<<"synthetic,warmup_id,begin_ns,end_ns,convert_pair_ns,encode_pair_ns,sof_420\n";
  const auto begin=capture::now(CLOCK_MONOTONIC);
  for(int i=0;i<3;++i){const auto a=capture::now(CLOCK_MONOTONIC);auto e=(*this)(in);const auto b=capture::now(CLOCK_MONOTONIC);out<<"true,"<<i<<','<<a<<','<<b<<','<<e.convert_ns<<','<<e.encode_ns<<','<<e.is420<<'\n';}
  out.close();const auto end=capture::now(CLOCK_MONOTONIC);
  std::ofstream summary;summary.exceptions(std::ios::badbit|std::ios::failbit);summary.open(dir+"/jpeg_shadow_warmup.json");
  summary<<"{\"status\":\"SOFTWARE_WARMUP_COMPLETED\",\"synthetic\":true,\"pairs\":3,\"real_sensor_inputs\":0,\"counted_in_shadow_inputs\":false,\"begin_ns\":"<<begin<<",\"end_ns\":"<<end<<",\"same_encoding_worker\":true,\"quality\":95,\"subsampling\":\"420\"}\n";
 }
 capture::ShadowEncoding operator()(const capture::ShadowInput& in, capture::FileEncoded* output=nullptr){
  if(in.left->header.seq!=in.right->header.seq||in.left->header.stamp!=in.right->header.stamp||
     in.left->header.stamp!=in.meta->header.stamp||in.left->header.seq!=in.meta->v4l2_sequence)
   throw std::runtime_error("STEREO_HEADER_MISMATCH");
  capture::ShadowEncoding result;result.is420=true;
  for(int eye=0;eye<2;++eye){const auto& im=eye?in.right:in.left;
   if(im->encoding!="8UC2"||im->width!=1280||im->height!=720||im->step!=2560||im->data.size()!=1843200)
    throw std::runtime_error("NOT_NATIVE_720_YUYV");
   const uint64_t t0=capture::now(CLOCK_MONOTONIC);
   cv::Mat raw(720,1280,CV_8UC2,const_cast<uint8_t*>(im->data.data()),im->step),bgr;
   cv::cvtColor(raw,bgr,cv::COLOR_YUV2BGR_YUY2);const auto t1=capture::now(CLOCK_MONOTONIC);result.convert_ns+=t1-t0;
   unsigned char* jpeg=nullptr;unsigned long size=0;
   const int rc=tjCompress2(encoder,bgr.data,1280,bgr.step,720,TJPF_BGR,&jpeg,&size,TJSAMP_420,95,TJFLAG_ACCURATEDCT);
   const auto t2=capture::now(CLOCK_MONOTONIC);result.encode_ns+=t2-t1;
   if(rc){if(jpeg)tjFree(jpeg);throw std::runtime_error("tjCompress2 failed");}
   int w=0,h=0,sampling=-1,colorspace=-1;
   const int header_rc=tjDecompressHeader3(decoder,jpeg,size,&w,&h,&sampling,&colorspace);
   // This parses each actual JPEG SOF, not just the requested encoder setting.
   const bool valid=header_rc==0&&w==1280&&h==720&&sampling==TJSAMP_420;
   if(output&&valid){auto& bytes=eye?output->right:output->left;try{bytes.assign(jpeg,jpeg+size);}catch(...){tjFree(jpeg);throw;}}
   tjFree(jpeg);if(!valid)throw std::runtime_error("JPEG_HEADER_INVALID");
   if(eye)result.right_bytes=size;else result.left_bytes=size;
  }return result;
 }
};
}
extern "C" capture::JpegShadow* create_jpeg_shadow(const char* dir){
 auto codec=std::make_shared<Codec>();
 return new capture::ShadowWorker(dir,[codec](const capture::ShadowInput& in){return (*codec)(in);},[codec,dir=std::string(dir)]{codec->warmup(dir);});
}

extern "C" capture::JpegShadow* create_jpeg_files(const char* dir,int sync_ms){
 auto codec=std::make_shared<Codec>();
 return new capture::JpegFiles(dir,[codec](const capture::ShadowInput& in){capture::FileEncoded out;out.timing=(*codec)(in,&out);return out;},[codec,d=std::string(dir)]{codec->warmup(d);},sync_ms);
}

extern "C" capture::JpegShadow* create_jpeg_files_incremental(const char* dir,int sync_ms){
 auto codec=std::make_shared<Codec>();
 return new capture::JpegFiles(dir,[codec](const capture::ShadowInput& in){capture::FileEncoded out;out.timing=(*codec)(in,&out);return out;},[codec,d=std::string(dir)]{codec->warmup(d);},sync_ms,
  [](int fd,const void* b,size_t n){return ::write(fd,b,n);},true);
}
