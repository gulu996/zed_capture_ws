#pragma once
// Interface only: no OpenCV/TurboJPEG dependency in the default capture process.
#include <sensor_msgs/Image.h>
#include <zed_capture/VideoStamp.h>
#include <cstdint>
#include <string>
namespace capture {
struct ShadowInput {
 zed_capture::VideoStamp::ConstPtr meta;
 sensor_msgs::Image::ConstPtr left,right;
 uint64_t copied_ns=0;
 bool raw_queue_accepted=false;
};
class JpegShadow {
 public:
 virtual ~JpegShadow()=default;
 // Single video producer. Never waits for queue space or encoder completion.
 virtual void submit(const ShadowInput&) noexcept=0;
 // Caller must stop/join the video producer first. Drains at most 4 queued pairs.
 virtual void finish()=0;
 virtual bool failed() const noexcept {return false;}
};
using ShadowFactory=JpegShadow* (*)(const char*);
}
