#pragma once
#include "jpeg_shadow.hpp"
#include "core.hpp"
#include <array>
#include <condition_variable>
#include <fstream>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>
#include <sstream>
#include <iomanip>
#include <unistd.h>
#include <memory>
#include <future>
namespace capture {
struct ShadowEncoding {
 uint64_t convert_ns=0,encode_ns=0,left_bytes=0,right_bytes=0;
 bool is420=false;
};
// The injected callable is used by hardware-free tests; production supplies the
// same explicit YUYV -> BGR -> TurboJPEG Q95/420 path validated in C3.
class ShadowWorker:public JpegShadow {
 public:
 using Encode=std::function<ShadowEncoding(const ShadowInput&)>;
 struct Event {
  uint64_t id=0,pair=0,raw_ns=0,copied=0,submitted=0,start=0,done=0;
  uint32_t sequence=0,type=0,source=0,flags=0;
  std_msgs::Header left,right;
  ShadowEncoding encoded;
  std::string status,reason;
  bool written=false;
  uint64_t notify_before=0,notify_after=0,unlock_after=0;
  uint64_t lock_before=0,lock_acquired=0,wait_before=0,wait_return=0;
  uint64_t cpu_start=0,cpu_end=0,log_before=0,log_after=0,tail_end=0;
  bool wait_was_empty=false;
 };
 private:
 // 4096 event slots > 136s at30Hz; C4 launch restricts requested duration to30s.
 // Event-capacity exhaustion explicitly fails evidence completeness, never blocks raw.
 std::vector<Event> events{4096};size_t inputs=0,unlogged=0,head=0,tail=0,count=0,peak=0;
 struct Task {ShadowInput in;size_t event=0;};std::array<Task,4> ring;
 std::mutex mutex;std::condition_variable condition;bool stopping=false,finished=false;
 Encode encode;std::function<void()> prepare;std::promise<void> ready;
 std::thread worker;std::ofstream csv;std::string dir,log_error;
 static std::string cell(const std::string& s){std::string out="\"";for(char c:s){if(c=='\"')out+='\"';out+=(c=='\n'||c=='\r')?' ':c;}return out+'\"';}
 void row(Event& e){
  csv<<e.id<<','<<e.pair<<','<<e.sequence<<','<<e.raw_ns<<','<<e.flags<<','<<e.type<<','<<e.source<<','
     <<e.left.seq<<','<<e.left.stamp.sec<<','<<e.left.stamp.nsec<<','<<cell(e.left.frame_id)<<','
     <<e.right.seq<<','<<e.right.stamp.sec<<','<<e.right.stamp.nsec<<','<<cell(e.right.frame_id)<<','
     <<e.copied<<','<<e.submitted<<','<<e.start<<','<<e.done<<','<<e.encoded.convert_ns<<','<<e.encoded.encode_ns<<','
     <<e.encoded.left_bytes<<','<<e.encoded.right_bytes<<','<<e.encoded.is420<<','<<e.status<<','<<cell(e.reason)<<'\n';e.written=true;
 }
 void loop(){
  // Constructor does not return until preparation on this actual worker ends.
  try{if(prepare)prepare();ready.set_value();}catch(...){ready.set_exception(std::current_exception());return;}
  for(;;){Task t;
   const auto lock_before=now(CLOCK_MONOTONIC);uint64_t lock_acquired,wait_before,wait_return;bool wait_was_empty;
   {std::unique_lock<std::mutex> lock(mutex);lock_acquired=now(CLOCK_MONOTONIC);wait_was_empty=count==0;wait_before=now(CLOCK_MONOTONIC);
    condition.wait(lock,[&]{return stopping||count;});wait_return=now(CLOCK_MONOTONIC);
    if(!count&&stopping)break;t=std::move(ring[head]);ring[head]=Task{};head=(head+1)%4;--count;}
   auto& e=events[t.event];e.start=now(CLOCK_MONOTONIC);
   e.lock_before=lock_before;e.lock_acquired=lock_acquired;e.wait_before=wait_before;e.wait_return=wait_return;e.wait_was_empty=wait_was_empty;e.cpu_start=now(CLOCK_THREAD_CPUTIME_ID);
   try{e.encoded=encode(t.in);if(!e.encoded.is420)throw std::runtime_error("JPEG_SOF_NOT_420");e.status="COMPLETED";}
   catch(const std::exception& x){e.status="ENCODE_FAILED";e.reason=x.what();}
   catch(...){e.status="ENCODE_FAILED";e.reason="unknown encoder exception";}
   e.done=now(CLOCK_MONOTONIC);
   e.cpu_end=now(CLOCK_THREAD_CPUTIME_ID);e.log_before=now(CLOCK_MONOTONIC);
   try{row(e);}catch(const std::exception& x){log_error=x.what();}
   e.log_after=now(CLOCK_MONOTONIC);
   t=Task{}; // Same ownership release as loop-scope destruction, now timestamped.
   e.tail_end=now(CLOCK_MONOTONIC);
  }
 }
 public:
 ShadowWorker(const std::string& directory,Encode fn,std::function<void()> preparation={}):encode(std::move(fn)),prepare(std::move(preparation)),dir(directory){
  for(const auto* n:{"jpeg_shadow_events.csv","jpeg_shadow_summary.json","jpeg_shadow_worker_timing.csv"})
   if(access((dir+"/"+n).c_str(),F_OK)==0)throw std::runtime_error("refusing existing JPEG shadow evidence");
  csv.exceptions(std::ios::badbit|std::ios::failbit);csv.open(dir+"/jpeg_shadow_events.csv");
  csv<<"input_id,pair_id,sequence,raw_ns,v4l2_flags,timestamp_type,timestamp_source,left_seq,left_sec,left_nsec,left_frame_id,right_seq,right_sec,right_nsec,right_frame_id,copied_ns,submitted_ns,worker_start_ns,completed_ns,convert_pair_ns,encode_pair_ns,left_jpeg_bytes,right_jpeg_bytes,sof_420,status,reason\n";
  csv.flush();auto prepared=ready.get_future();worker=std::thread(&ShadowWorker::loop,this);
  try{prepared.get();}catch(...){worker.join();throw;}
 }
 ~ShadowWorker(){try{finish();}catch(...){} }
 void submit(const ShadowInput& in) noexcept override {
  const size_t index=inputs++;
  if(index>=events.size()){++unlogged;return;}
  auto& e=events[index];e.id=index+1;
  try{
   e.pair=in.meta->pair_id;e.sequence=in.meta->v4l2_sequence;e.raw_ns=in.meta->header.stamp.toNSec();e.flags=in.meta->v4l2_flags;e.type=in.meta->timestamp_type;e.source=in.meta->timestamp_source;
   e.left=in.left->header;e.right=in.right->header;e.copied=in.copied_ns;e.submitted=now(CLOCK_MONOTONIC);
   if(!in.raw_queue_accepted||!in.meta->payload_valid){e.status="REJECTED";e.reason="RAW_QUEUE_REJECTED_OR_INVALID_PAYLOAD";return;}
   std::unique_lock<std::mutex> lock(mutex,std::try_to_lock);
   if(!lock.owns_lock()){e.status="REJECTED";e.reason="QUEUE_LOCK_BUSY";return;}
   if(stopping||count==4){e.status="REJECTED";e.reason=stopping?"SHUTTING_DOWN":"QUEUE_FULL";return;}
   e.status="QUEUED";ring[tail]={in,index};tail=(tail+1)%4;++count;peak=std::max(peak,count);
   e.notify_before=now(CLOCK_MONOTONIC);condition.notify_one();e.notify_after=now(CLOCK_MONOTONIC);
   lock.unlock();e.unlock_after=now(CLOCK_MONOTONIC);
  }catch(...){e.status="REJECTED";e.reason="SUBMIT_EXCEPTION";}
 }
 void finish() override {
  if(finished)return;
  {std::lock_guard<std::mutex> lock(mutex);stopping=true;}condition.notify_one();if(worker.joinable())worker.join();
  size_t completed=0,rejected=0,failed=0;uint64_t wait_max=0;
  for(size_t i=0;i<std::min(inputs,events.size());++i){auto& e=events[i];
   if(e.status=="COMPLETED")++completed;else if(e.status=="REJECTED")++rejected;else ++failed;
   if(e.start>=e.submitted&&e.start)wait_max=std::max(wait_max,e.start-e.submitted);
   if(!e.written)try{row(e);}catch(const std::exception& x){log_error=x.what();}
  }
  try{csv.close();}catch(const std::exception& x){log_error=x.what();}
  // Fixed-size in-memory timing data written only after producer stop + join.
  // unlock_after is an observed timestamp after unlock, not its exact instant.
  try{
   std::ofstream trace;trace.exceptions(std::ios::badbit|std::ios::failbit);trace.open(dir+"/jpeg_shadow_worker_timing.csv");
   trace<<"input_id,pair_id,notify_before_ns,notify_after_ns,producer_unlock_observed_ns,worker_lock_before_ns,worker_lock_acquired_ns,wait_before_ns,wait_return_ns,wait_was_empty,worker_start_ns,completed_ns,worker_cpu_start_ns,worker_cpu_end_ns,event_log_before_ns,event_log_after_ns,task_release_end_ns,status\n";
   for(size_t i=0;i<std::min(inputs,events.size());++i){const auto& e=events[i];trace<<e.id<<','<<e.pair<<','<<e.notify_before<<','<<e.notify_after<<','<<e.unlock_after<<','<<e.lock_before<<','<<e.lock_acquired<<','<<e.wait_before<<','<<e.wait_return<<','<<e.wait_was_empty<<','<<e.start<<','<<e.done<<','<<e.cpu_start<<','<<e.cpu_end<<','<<e.log_before<<','<<e.log_after<<','<<e.tail_end<<','<<e.status<<'\n';}trace.close();
  }catch(const std::exception& x){log_error=x.what();}
  if(!log_error.empty()){std::ofstream error(dir+"/jpeg_shadow_log_error.txt");error<<log_error<<'\n';}
  std::ofstream summary;summary.exceptions(std::ios::badbit|std::ios::failbit);summary.open(dir+"/jpeg_shadow_summary.json");
  summary<<"{\"enabled\":true,\"quality\":95,\"subsampling\":\"420\",\"queue_capacity\":4,\"inputs\":"<<inputs<<",\"completed\":"<<completed<<",\"encode_failed\":"<<failed<<",\"rejected\":"<<rejected<<",\"unlogged_inputs\":"<<unlogged<<",\"queue_peak\":"<<peak<<",\"max_queue_wait_ns\":"<<wait_max<<",\"worker_joined\":true,\"queue_drained\":"<<(count==0?"true":"false")<<",\"event_log_ok\":"<<(log_error.empty()?"true":"false")<<",\"jpeg_files_written\":0,\"conversion_reference\":\"OpenCV COLOR_YUV2BGR_YUY2 BT601 limited; actual colorimetry must be checked separately\"}\n";
  summary.close();finished=true;
 }
};
}
