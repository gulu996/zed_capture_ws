#pragma once
#include "jpeg_shadow_worker.hpp"
#include <atomic>
#include <deque>
#include <set>
#include <sys/stat.h>
#include <fcntl.h>
#include <cerrno>
#include <cstring>
namespace capture {
struct FileEncoded {ShadowEncoding timing;std::vector<uint8_t> left,right;};
// Single producer, one encoder, one disk worker. Raw ownership ends after encode.
class JpegFiles:public JpegShadow {
 public:
 using Encoder=std::function<FileEncoded(const ShadowInput&)>;
 using Write=std::function<ssize_t(int,const void*,size_t)>;
 struct Event {ShadowInput metadata;std_msgs::Header left,right;uint64_t copy=0,submit=0,begin=0,end=0,write_begin=0,write_end=0;ShadowEncoding timing;std::string status="PENDING",reason,left_path,right_path;bool left_ok=false,right_ok=false,indexed=false;};
 private:
 std::string dir;Encoder encode;Write writefn;int sync_ms;bool streaming;std::vector<Event> events;std::array<std::atomic<unsigned>,32> slots{};size_t inputs=0,unlogged=0;
 size_t complete=0,ef=0,er=0,wr=0,wf=0,other=0;
 std::atomic<uint64_t> retired_count{0};
 struct Input {ShadowInput in;size_t id;};struct Output {FileEncoded data;size_t id;};
 std::deque<Input> eq;std::deque<Output> wq;std::mutex em,wm;std::condition_variable ec,wc;
 bool stop=false,encode_done=false,finished=false;std::atomic<bool> bad{false};
 size_t ep=0,wp=0,wb=0,wbpeak=0;static constexpr size_t bytes_limit=32*1024*1024;
 std::thread encoder,writer;std::promise<void> prepared;std::ofstream index,sync_log,progress;
 std::vector<std::string> pending;std::set<std::string> directories;uint64_t last_sync=0,sync_max=0,last_complete_pair=0;bool final_sync=false;std::string io_error;
 static std::string cell(const std::string& s){std::string r="\"";for(char c:s){if(c=='\"')r+='\"';r+=(c=='\n'||c=='\r')?' ':c;}return r+'\"';}
 static void mkdirNew(const std::string& p){if(mkdir(p.c_str(),0750))throw std::runtime_error("mkdir: "+p+": "+strerror(errno));}
 void row(Event& e){const auto& m=*e.metadata.meta;
  index<<m.pair_id<<','<<cell(e.left_path)<<','<<cell(e.right_path)<<','<<m.header.stamp.toNSec()<<','<<m.v4l2_sec<<','<<m.v4l2_usec<<','<<(m.timestamp_type==8192?"CLOCK_MONOTONIC":"UNKNOWN")<<','<<m.v4l2_sequence<<','<<m.v4l2_flags<<','<<m.timestamp_type<<','<<m.timestamp_source<<',';
  for(const auto* h:{&e.left,&e.right})index<<h->seq<<','<<h->stamp.sec<<','<<h->stamp.nsec<<','<<cell(h->frame_id)<<',';
  index<<"1280,720,95,420,"<<e.status<<','<<cell(e.reason)<<','<<e.left_ok<<','<<e.right_ok<<','<<e.copy<<','<<e.submit<<','<<e.begin<<','<<e.end<<','<<e.timing.convert_ns<<','<<e.timing.encode_ns<<','<<e.write_begin<<','<<e.write_end<<','<<e.timing.left_bytes<<','<<e.timing.right_bytes<<','<<(e.timing.is420?"ENCODED_420":"NOT_ENCODED_OR_FAILED")<<','<<e.status<<'\n';index.flush();e.indexed=true;
 }
 void terminal(size_t id){if(streaming){slots[id].store(2,std::memory_order_release);wc.notify_one();}}
 void retire(size_t id){auto& e=events[id];row(e);
  if(e.status=="WRITTEN")++complete;else if(e.status=="ENCODE_FAILED")++ef;else if(e.status=="ENCODE_QUEUE_REJECTED")++er;else if(e.status=="WRITE_QUEUE_REJECTED")++wr;else if(e.status=="WRITE_FAILED")++wf;else ++other;
  e=Event{};slots[id].store(0,std::memory_order_release);++retired_count;
 }
 void terminals(){if(streaming)for(size_t i=0;i<slots.size();++i)if(slots[i].load(std::memory_order_acquire)==2)retire(i);}
 void syncPath(const std::string& p,bool directory=false){int f=open(p.c_str(),O_RDONLY|O_CLOEXEC|(directory?O_DIRECTORY:0));if(f<0)throw std::runtime_error("sync open: "+p);int rc=fsync(f);int saved=errno;int cl=close(f);if(rc||cl)throw std::runtime_error("fsync/close: "+p+": "+strerror(saved));}
 void syncBatch(bool final=false){const auto b=now(CLOCK_MONOTONIC);index.flush();for(const auto& p:pending)syncPath(p);for(const auto& p:directories)syncPath(p,true);syncPath(dir+"/frames.csv");
  sync_log<<b<<','<<now(CLOCK_MONOTONIC)<<','<<pending.size()<<','<<final<<','<<last_complete_pair<<'\n';sync_log.flush();syncPath(dir+"/jpeg_file_sync.csv");syncPath(dir,true);pending.clear();if(streaming){directories={dir+"/camera",dir+"/camera/left",dir+"/camera/right"};
   size_t enc,encpeak,wrq,wrpeak,bytes;{std::lock_guard<std::mutex> l(em);enc=eq.size();encpeak=ep;}{std::lock_guard<std::mutex> l(wm);wrq=wq.size();wrpeak=wp;bytes=wb;}
   progress<<"{\"monotonic_ns\":"<<now(CLOCK_MONOTONIC)<<",\"completed\":"<<complete<<",\"encode_queue\":"<<enc<<",\"encode_queue_peak\":"<<encpeak<<",\"write_queue\":"<<wrq<<",\"write_queue_peak\":"<<wrpeak<<",\"write_bytes\":"<<bytes<<",\"event_slots\":32}\n";progress.flush();syncPath(dir+"/jpeg_progress.jsonl");
  }last_sync=now(CLOCK_MONOTONIC);sync_max=std::max(sync_max,last_sync-b);
 }
 void file(const std::string& rel,const std::vector<uint8_t>& data){std::string p=dir+'/'+rel;int fd=open(p.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0640);if(fd<0)throw std::runtime_error("open exclusive: "+rel+": "+strerror(errno));
  try{size_t off=0;while(off<data.size()){ssize_t n=writefn(fd,data.data()+off,data.size()-off);if(n<0&&errno==EINTR)continue;if(n<=0||size_t(n)>data.size()-off)throw std::runtime_error("write: "+rel+": "+(n==0?std::string("ZERO_SHORT_WRITE"):std::string(strerror(errno))));off+=size_t(n);}if(close(fd)){fd=-1;throw std::runtime_error("close: "+rel);}fd=-1;pending.push_back(p);}catch(...){if(fd>=0)close(fd);throw;}
 }
 void encodeLoop(std::function<void()> preparation){try{preparation();prepared.set_value();}catch(...){bad=true;prepared.set_exception(std::current_exception());{std::lock_guard<std::mutex> l(wm);encode_done=true;}wc.notify_all();return;}
  for(;;){Input t;{std::unique_lock<std::mutex> l(em);ec.wait(l,[&]{return stop||!eq.empty();});if(eq.empty()&&stop)break;t=std::move(eq.front());eq.pop_front();}
   auto& e=events[t.id];e.begin=now(CLOCK_MONOTONIC);
   try{auto data=encode(t.in);e.end=now(CLOCK_MONOTONIC);e.timing=data.timing;if(!data.timing.is420||data.left.empty()||data.right.empty())throw std::runtime_error("INVALID_JPEG_OUTPUT");
    std::unique_lock<std::mutex> l(wm,std::try_to_lock);const size_t bytes=data.left.size()+data.right.size();
    if(!l.owns_lock()||wq.size()>=4||bytes>bytes_limit||wb+bytes>bytes_limit){e.status="WRITE_QUEUE_REJECTED";e.reason="BOUNDED_WRITE_QUEUE_BUSY_FULL_OR_BYTES";bad=true;terminal(t.id);continue;}
    e.status="ENCODED";wb+=bytes;wbpeak=std::max(wbpeak,wb);wq.push_back({std::move(data),t.id});wp=std::max(wp,wq.size());wc.notify_one();
   }catch(const std::exception& x){e.end=now(CLOCK_MONOTONIC);e.status="ENCODE_FAILED";e.reason=x.what();bad=true;terminal(t.id);}
  }{std::lock_guard<std::mutex> l(wm);encode_done=true;}wc.notify_all();
 }
 void writeLoop(){try{for(;;){terminals();Output t;{std::unique_lock<std::mutex> l(wm);if(streaming)wc.wait_for(l,std::chrono::milliseconds(5),[&]{return encode_done||!wq.empty();});else wc.wait(l,[&]{return encode_done||!wq.empty();});if(wq.empty()&&encode_done)break;if(wq.empty())continue;t=std::move(wq.front());wq.pop_front();}
    auto& e=events[t.id];e.write_begin=now(CLOCK_MONOTONIC);
    try{std::ostringstream shard,name;shard<<std::setw(6)<<std::setfill('0')<<((e.metadata.meta->pair_id-1)/1000);name<<std::setw(12)<<std::setfill('0')<<e.metadata.meta->pair_id<<".jpg";
     for(const auto* eye:{"left","right"}){auto p=dir+"/camera/"+eye+'/'+shard.str();if(!directories.count(p)){struct stat st{};if(!streaming||stat(p.c_str(),&st))mkdirNew(p);else if(!S_ISDIR(st.st_mode))throw std::runtime_error("shard not directory");directories.insert(p);}}
     e.left_path="camera/left/"+shard.str()+'/'+name.str();e.right_path="camera/right/"+shard.str()+'/'+name.str();
     file(e.left_path,t.data.left);e.left_ok=true;file(e.right_path,t.data.right);e.right_ok=true;e.status="WRITTEN";last_complete_pair=e.metadata.meta->pair_id;
    }catch(const std::exception& x){e.status="WRITE_FAILED";e.reason=x.what();bad=true;}
    e.write_end=now(CLOCK_MONOTONIC);if(streaming)retire(t.id);else row(e);
    {std::lock_guard<std::mutex> l(wm);wb-=t.data.left.size()+t.data.right.size();}
    if(now(CLOCK_MONOTONIC)-last_sync>=uint64_t(sync_ms)*1000000ULL||pending.size()>=120)syncBatch();
   }}catch(const std::exception& x){bad=true;io_error=x.what();}
 }
 public:
 JpegFiles(const std::string& directory,Encoder fn,std::function<void()> prep,int ms=1000,Write wf=[](int fd,const void* b,size_t n){return ::write(fd,b,n);},bool incremental=false):dir(directory),encode(std::move(fn)),writefn(std::move(wf)),sync_ms(ms),streaming(incremental),events(incremental?32:4096){
  for(auto& state:slots)state.store(0);
  if(ms<100||ms>5000)throw std::runtime_error("sync_ms must be 100..5000");
  if(streaming&&access((dir+"/jpeg_progress.jsonl").c_str(),F_OK)==0)throw std::runtime_error("refuse existing C5G progress");
  mkdirNew(dir+"/camera");for(auto eye:{"left","right"})mkdirNew(dir+"/camera/"+eye);
  directories={dir+"/camera",dir+"/camera/left",dir+"/camera/right"};
  for(auto name:{"frames.csv","jpeg_file_sync.csv","jpeg_files_summary.json"})if(access((dir+'/'+name).c_str(),F_OK)==0)throw std::runtime_error("refuse existing C5F evidence");
  index.exceptions(std::ios::badbit|std::ios::failbit);sync_log.exceptions(std::ios::badbit|std::ios::failbit);index.open(dir+"/frames.csv");sync_log.open(dir+"/jpeg_file_sync.csv");
  if(streaming){progress.exceptions(std::ios::badbit|std::ios::failbit);progress.open(dir+"/jpeg_progress.jsonl");}
  index<<"pair_id,left_path,right_path,raw_ns,v4l2_sec,v4l2_usec,clock_domain,sequence,flags,timestamp_type,timestamp_source,left_seq,left_sec,left_nsec,left_frame_id,right_seq,right_sec,right_nsec,right_frame_id,width,height,quality,subsampling,status,reason,left_ok,right_ok,copied_ns,submitted_ns,encode_begin_ns,encode_end_ns,convert_ns,encode_ns,write_begin_ns,write_end_ns,left_bytes,right_bytes,encoding_status,write_status\n";index.flush();sync_log<<"begin_ns,end_ns,file_count,final,last_complete_pair_id\n";sync_log.flush();last_sync=now(CLOCK_MONOTONIC);
  auto future=prepared.get_future();writer=std::thread(&JpegFiles::writeLoop,this);try{encoder=std::thread(&JpegFiles::encodeLoop,this,prep);future.get();}catch(...){if(encoder.joinable())encoder.join();{std::lock_guard<std::mutex> l(wm);encode_done=true;}wc.notify_all();writer.join();throw;}
 }
 bool failed()const noexcept override{return bad;}
 uint64_t recordedEvents()const noexcept{return retired_count.load();}
 void submit(const ShadowInput& in)noexcept override{
  size_t id=inputs++;
  if(streaming){bool got=false;for(size_t k=0;k<slots.size();++k){size_t at=(id+k)%slots.size();unsigned free=0;if(slots[at].compare_exchange_strong(free,1,std::memory_order_acq_rel)){id=at;got=true;break;}}if(!got){++unlogged;bad=true;return;}}
  else if(id>=events.size()){++unlogged;bad=true;return;}auto& e=events[id];
  try{e.metadata.meta=in.meta;e.left=in.left->header;e.right=in.right->header;e.copy=in.copied_ns;e.submit=now(CLOCK_MONOTONIC);
   if(!in.raw_queue_accepted||!in.meta->payload_valid||!in.meta->pair_id){e.status="INPUT_REJECTED";e.reason="INVALID_PAYLOAD_OR_METADATA_QUEUE";bad=true;terminal(id);return;}
   std::unique_lock<std::mutex> l(em,std::try_to_lock);if(!l.owns_lock()||stop||eq.size()>=4){e.status="ENCODE_QUEUE_REJECTED";e.reason="BOUNDED_ENCODE_QUEUE_BUSY_FULL_OR_CLOSED";bad=true;terminal(id);return;}eq.push_back({in,id});ep=std::max(ep,eq.size());ec.notify_one();
  }catch(...){e.status="INPUT_REJECTED";e.reason="SUBMIT_EXCEPTION";bad=true;terminal(id);}
 }
 void finish()override{if(finished)return;{std::lock_guard<std::mutex> l(em);stop=true;}ec.notify_all();if(encoder.joinable())encoder.join();if(writer.joinable())writer.join();
  try{for(size_t i=0;i<(streaming?slots.size():std::min(inputs,events.size()));++i){if(streaming&&slots[i].load()==0)continue;auto& e=events[i];if(e.status=="ENCODED"||e.status=="PENDING"){e.status="WRITE_FAILED";e.reason="WRITER_ABORTED_OR_UNFINISHED";bad=true;}if(streaming){retire(i);continue;}if(e.status=="WRITTEN")++complete;else if(e.status=="ENCODE_FAILED")++ef;else if(e.status=="ENCODE_QUEUE_REJECTED")++er;else if(e.status=="WRITE_QUEUE_REJECTED")++wr;else if(e.status=="WRITE_FAILED")++wf;else ++other;if(!e.indexed)row(e);}syncBatch(true);final_sync=true;index.close();sync_log.close();if(streaming)progress.close();}catch(const std::exception& x){bad=true;io_error=x.what();}
  if(complete!=inputs||unlogged)bad=true;
  std::ofstream s;s.exceptions(std::ios::badbit|std::ios::failbit);s.open(dir+"/jpeg_files_summary.json");s<<"{\"mode\":\"jpeg_files\",\"inputs\":"<<inputs<<",\"completed\":"<<complete<<",\"encode_failed\":"<<ef<<",\"encode_queue_rejected\":"<<er<<",\"write_queue_rejected\":"<<wr<<",\"write_failed\":"<<wf<<",\"input_rejected\":"<<other<<",\"unlogged\":"<<unlogged<<",\"encode_queue_peak\":"<<ep<<",\"write_queue_peak\":"<<wp<<",\"write_queue_bytes_peak\":"<<wbpeak<<",\"queue_capacity\":4,\"write_bytes_limit\":"<<bytes_limit<<",\"final_synced\":"<<(final_sync?"true":"false")<<",\"failed\":"<<(bad?"true":"false")<<",\"workers_joined\":true,\"max_sync_ns\":"<<sync_max<<",\"sync_interval_ms\":"<<sync_ms<<",\"sync_error\":"<<cell(io_error)<<"}\n";s.close();syncPath(dir+"/jpeg_files_summary.json");syncPath(dir,true);finished=true;
 }
 ~JpegFiles(){try{finish();}catch(...){} }
};
using FilesFactory=JpegShadow* (*)(const char*,int);
}
