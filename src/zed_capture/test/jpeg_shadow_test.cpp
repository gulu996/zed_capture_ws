#include "zed_capture/jpeg_shadow_worker.hpp"
#include <boost/make_shared.hpp>
#include <boost/weak_ptr.hpp>
#include <cassert>
#include <future>
#include <iostream>
#include <atomic>
#include <sys/stat.h>
extern "C" capture::JpegShadow* create_jpeg_shadow(const char*);
std::string load(const std::string& p){std::ifstream f(p);return std::string(std::istreambuf_iterator<char>(f),{});}
capture::ShadowInput sample(uint64_t id,bool pixels=false){
 auto m=boost::make_shared<zed_capture::VideoStamp>();m->pair_id=id;m->v4l2_sequence=id+10;m->header.seq=id+10;m->header.stamp.fromNSec(13984210934000ULL+id*33333333ULL);m->payload_valid=true;m->timestamp_type=8192;
 auto l=boost::make_shared<sensor_msgs::Image>(),r=boost::make_shared<sensor_msgs::Image>();
 for(auto im:{l,r}){im->header=m->header;im->header.frame_id=im==l?"left,raw":"right_raw";im->width=1280;im->height=720;im->step=2560;im->encoding="8UC2";
  if(pixels){im->data.resize(1843200);for(size_t i=0;i<im->data.size();i+=4){im->data[i]=80;im->data[i+1]=100;im->data[i+2]=150;im->data[i+3]=170;}}}
 return {m,l,r,capture::now(CLOCK_MONOTONIC),true};
}
int main(int argc,char** argv){
 assert(argc==2);std::string root=argv[1];assert(mkdir(root.c_str(),0750)==0);
 auto dir=[&](const std::string& s){auto p=root+'/'+s;assert(mkdir(p.c_str(),0750)==0);return p;};
 {auto p=dir("empty_shutdown");capture::ShadowWorker w(p,[](const capture::ShadowInput&){return capture::ShadowEncoding{};});w.finish();w.finish();assert(load(p+"/jpeg_shadow_summary.json").find("\"worker_joined\":true")!=std::string::npos);}
 {auto p=dir("preparation_barrier");std::atomic<bool> prepared{false};capture::ShadowWorker w(p,[&](const capture::ShadowInput&){assert(prepared);return capture::ShadowEncoding{1,2,3,4,true};},[&]{std::this_thread::sleep_for(std::chrono::milliseconds(2));prepared=true;});assert(prepared);w.submit(sample(1));w.finish();assert(load(p+"/jpeg_shadow_summary.json").find("\"completed\":1")!=std::string::npos);}
 {auto p=dir("preparation_failure");bool threw=false;try{capture::ShadowWorker w(p,[](const capture::ShadowInput&){assert(false);return capture::ShadowEncoding{};},[]{throw std::runtime_error("SYNTHETIC_PREPARATION_FAILURE");});}catch(const std::runtime_error&){threw=true;}assert(threw);}
 {auto p=dir("queue_and_ownership");std::promise<void> entered,release;auto gate=release.get_future().share();std::atomic<unsigned> calls{0};
  capture::ShadowWorker w(p,[&](const capture::ShadowInput& s){if(calls++==0)entered.set_value();gate.wait();assert(s.left->header.stamp==s.meta->header.stamp);return capture::ShadowEncoding{1,2,3,4,true};});
  auto first=sample(1);boost::weak_ptr<const sensor_msgs::Image> weak=first.left;w.submit(first);first={};entered.get_future().wait();assert(!weak.expired());
  for(int i=2;i<=6;++i)w.submit(sample(i));release.set_value();w.finish();assert(weak.expired());
  const auto s=load(p+"/jpeg_shadow_summary.json");assert(s.find("\"inputs\":6")!=std::string::npos);assert(s.find("\"completed\":5")!=std::string::npos);assert(s.find("\"rejected\":1")!=std::string::npos);assert(s.find("\"queue_peak\":4")!=std::string::npos);
  assert(load(p+"/jpeg_shadow_events.csv").find("QUEUE_FULL")!=std::string::npos);
 }
 {auto p=dir("encode_failure");capture::ShadowWorker w(p,[](const capture::ShadowInput&)->capture::ShadowEncoding{throw std::runtime_error("INJECTED_CODEC_FAILURE");});w.submit(sample(7));w.finish();assert(load(p+"/jpeg_shadow_events.csv").find("INJECTED_CODEC_FAILURE")!=std::string::npos);assert(load(p+"/jpeg_shadow_summary.json").find("\"encode_failed\":1")!=std::string::npos);}
 {auto p=dir("raw_rejected");capture::ShadowWorker w(p,[](const capture::ShadowInput&)->capture::ShadowEncoding{assert(false);return {};});auto x=sample(8);x.raw_queue_accepted=false;w.submit(x);w.finish();assert(load(p+"/jpeg_shadow_summary.json").find("\"rejected\":1")!=std::string::npos);}
 {auto p=dir("real_codec_synthetic_pixels");std::unique_ptr<capture::JpegShadow> w(create_jpeg_shadow(p.c_str()));auto x=sample(9,true);const auto before=x.left->data;const auto h=x.left->header;w->submit(x);w->finish();assert(x.left->data==before&&x.left->header.stamp==h.stamp&&x.left->header.seq==h.seq&&x.left->header.frame_id==h.frame_id);const auto s=load(p+"/jpeg_shadow_summary.json");assert(s.find("\"completed\":1")!=std::string::npos);assert(load(p+"/jpeg_shadow_events.csv").find("\"left,raw\"")!=std::string::npos);}
 {auto p=dir("stereo_mismatch");std::unique_ptr<capture::JpegShadow> w(create_jpeg_shadow(p.c_str()));auto x=sample(10,true);auto right=boost::make_shared<sensor_msgs::Image>(*x.right);right->header.seq++;x.right=right;w->submit(x);w->finish();assert(load(p+"/jpeg_shadow_events.csv").find("STEREO_HEADER_MISMATCH")!=std::string::npos);}
 std::cout<<"SYNTHETIC SOFTWARE TESTS PASS: preparation barrier/failure/shutdown/drain/queue_full/ownership/encoder_failure/raw_rejection/420/headers/pairing; no hardware opened\n";
}
