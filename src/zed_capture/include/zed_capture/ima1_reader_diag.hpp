#pragma once
// L2-D2 observer only. No result from this class controls the original reader.
#include "zed_capture/core.hpp"
#include <cerrno>
#include <cstdio>
#include <fcntl.h>
#include <memory>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>
namespace capture {
struct Ima1DiagEvent {
 uint64_t poll=0,mono=0,interval=0,late=0,read_before=0,read_after=0;
 uint64_t a_before=0,a_after=0,b_before=0,b_after=0,generation=0;
 uint64_t last_success_poll=0,last_success_mono=0,last_failure_poll=0;
 uint64_t last_epoch=0,last_seq=0,last_stat_poll=0,stat_mono=0,stat_dev=0,stat_ino=0;
 int64_t stat_size=0;
 std::array<uint8_t,64> a{},b{};
 int32_t fd=-1,old_fd=-1,ar=0,br=0,ae=0,be=0,stat_ret=0,stat_errno=0,open_ret=-1,open_errno=0,close_ret=0,close_errno=0;
 uint32_t last_source=0,last_ready=0,reason=0;
 uint8_t attempted=0,stable=0,legacy_poll=0,duplicate=0,validity=0,stat_called=0,stat_known=0,open_called=0,close_called=0,reopen=0,clock_valid=0,legacy_validity_evaluated=0;
};
static_assert(sizeof(Ima1DiagEvent)<=512,"IMA1 diagnostic event budget");
class Ima1ReaderDiag {
 public:
 static constexpr size_t slots=8192;
 std::unique_ptr<Ima1DiagEvent[]> events;
 uint64_t stored=0,eligible=0,dropped=0,first_dropped=0,last_dropped=0,total=0,attempted=0,full=0,unstable=0,no_fd=0,semantic_invalid=0;
 uint64_t extra_clocks=0,clock_errors=0,observer_errors=0,category[10]{};
 uint64_t generation=0,last_success=0,last_success_mono=0,last_failure=0,last_health=0,last_stat=0;
 Ima1DiagEvent stat_context{};Anchor previous{};bool had_success=false,previous_stable=false,previous_valid=false;uint8_t previous_validity=0;
 int final_close_ret=0,final_close_errno=0;bool final_close_called=false,open_failed=false;
 bool allocation_failed=false;std::string error;
 Ima1ReaderDiag(){events.reset(new(std::nothrow) Ima1DiagEvent[slots]);allocation_failed=!events;}
 static const char* validityName(uint8_t n){static const char* names[]={"NOT_EVALUATED","BAD_PROTOCOL","TORN","NOT_READY","UNKNOWN_CLOCK","HOST_CLOCK_INVALID","STALE","HOST_ARRIVAL_ANCHOR"};return n<8?names[n]:"UNKNOWN";}
 static uint8_t code(const std::string& s){for(uint8_t n=1;n<8;++n)if(s==validityName(n))return n;return 0;}
 uint8_t observeValidity(const Anchor& a,uint64_t t) noexcept {
  int saved=errno;uint8_t result=0;try{result=code(capture::validity(a,t));}catch(...){++observer_errors;}errno=saved;return result;
 }
 uint64_t tick(uint8_t& bits,uint8_t mask) noexcept {int saved=errno;timespec t{};++extra_clocks;int rc=clock_gettime(CLOCK_MONOTONIC,&t);errno=saved;if(rc){++clock_errors;return 0;}bits|=mask;return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec;}
 void begin(Ima1DiagEvent& e,uint64_t p,uint64_t mono,uint64_t interval,uint64_t late,int fd){
  e.poll=p;e.mono=mono;e.interval=interval;e.late=late;e.old_fd=fd;e.fd=fd;e.generation=generation;
  e.last_success_poll=last_success;e.last_success_mono=last_success_mono;e.last_failure_poll=last_failure;
  e.last_epoch=previous.epoch;e.last_seq=previous.seq;e.last_source=previous.source;e.last_ready=previous.ready;
  e.last_stat_poll=last_stat;e.stat_mono=stat_context.stat_mono;e.stat_ret=stat_context.stat_ret;e.stat_errno=stat_context.stat_errno;e.stat_known=stat_context.stat_known;e.stat_dev=stat_context.stat_dev;e.stat_ino=stat_context.stat_ino;e.stat_size=stat_context.stat_size;
 }
 void pathStat(Ima1DiagEvent& e,int rc,int err,const struct stat& s){e.stat_called=1;e.stat_known=1;e.stat_ret=rc;e.stat_errno=rc<0?err:0;e.stat_mono=e.mono;e.last_stat_poll=e.poll;last_stat=e.poll;
  e.stat_size=rc==0?s.st_size:0;e.stat_dev=rc==0?s.st_dev:0;e.stat_ino=rc==0?s.st_ino:0;stat_context=e;
 }
 void finish(Ima1DiagEvent& e){
  ++total;e.generation=generation;uint32_t flags=0;
  if(!e.attempted){++no_fd;flags|=1;}else{
   ++attempted;bool both=e.ar==64&&e.br==64;if(both)++full;
   if(e.ar<0){++category[0];flags|=2;}if(e.br<0){++category[1];flags|=4;}
   if(e.ar==0){++category[2];flags|=8;}if(e.br==0){++category[3];flags|=16;}
   if(e.ar>0&&e.ar<64){++category[4];flags|=32;}if(e.br>0&&e.br<64){++category[5];flags|=64;}
   Anchor a{},b{};if(e.ar==64){std::memcpy(&a,e.a.data(),64);if(a.seq&1){++category[6];flags|=128;}}
   if(e.br==64){std::memcpy(&b,e.b.data(),64);if(b.seq&1){++category[7];flags|=256;}}
   if(both&&e.a!=e.b){++category[8];flags|=512;if(a.seq!=b.seq)flags|=1024;else flags|=2048;}
   if(e.stable){
    if(!previous_stable)flags|=4096;
    bool valid=e.validity==7;if(valid&&!previous_valid)flags|=8192;
    if(!valid)++semantic_invalid;
    if(had_success&&(e.validity!=previous_validity||a.epoch!=previous.epoch||a.source!=previous.source||a.ready!=previous.ready||a.magic!=previous.magic||a.version!=previous.version||a.device<previous.device||a.host<previous.host))flags|=16384;
    previous=a;had_success=true;last_success=e.poll;last_success_mono=e.read_after;previous_valid=valid;previous_validity=e.validity;
   }
  }
  if(!e.stable){++unstable;last_failure=e.poll;previous_valid=false;flags|=32768;}
  previous_stable=e.stable;
  if(e.open_called||e.close_called||(e.stat_called&&(e.stat_ret<0||e.stat_size!=64)))flags|=65536;
  if(!last_health||e.mono-last_health>=1000000000ULL){flags|=131072;last_health=e.mono;}
  if(e.attempted&&e.clock_valid!=15)flags|=262144;
  e.reason=flags;if(!flags)return;++eligible;
  if(stored<slots&&events){events[stored++]=e;}else{if(!dropped)first_dropped=e.poll;++dropped;last_dropped=e.poll;}
 }
 static void snapshot(std::ostream& o,const std::array<uint8_t,64>& bytes,int rc){
  int n=rc>0&&rc<=64?rc:0;o<<"{\"valid_bytes\":"<<n<<",\"raw_hex\":\""<<hex(bytes.data(),n)<<"\",\"full_snapshot\":";
  if(rc!=64){o<<"null}";return;}Anchor a{};std::memcpy(&a,bytes.data(),64);
  o<<"{\"magic\":"<<a.magic<<",\"version\":"<<a.version<<",\"seq\":"<<a.seq<<",\"odd\":"<<(a.seq&1)<<",\"writer_epoch\":"<<a.epoch<<",\"ready_u32\":"<<a.ready<<",\"clock_source\":"<<a.source<<",\"device_ns\":"<<a.device<<",\"host_ns\":"<<a.host<<",\"updated_ns\":"<<a.updated<<",\"uncertainty_ns\":"<<a.uncertainty<<"}}";
 }
 static std::string row(const Ima1DiagEvent& e){std::ostringstream o;
  o<<"{\"poll_id\":"<<e.poll<<",\"monotonic_ns\":"<<e.mono<<",\"interval_ns\":"<<e.interval<<",\"wake_lateness_ns\":"<<e.late<<",\"fd\":"<<e.fd<<",\"old_fd\":"<<e.old_fd<<",\"fd_generation\":"<<e.generation<<",\"read_attempted\":"<<int(e.attempted)
   <<",\"pread_a_ret\":";if(e.attempted)o<<e.ar;else o<<"null";
  o<<",\"pread_b_ret\":";if(e.attempted)o<<e.br;else o<<"null";
  o<<",\"pread_a_errno\":";if(e.attempted&&e.ar<0)o<<e.ae;else o<<"null";
  o<<",\"pread_b_errno\":";if(e.attempted&&e.br<0)o<<e.be;else o<<"null";
  o<<",\"read_before_ns\":"<<e.read_before<<",\"read_after_ns\":"<<e.read_after;
  const char* names[]={"pread_a_before_ns","pread_a_after_ns","pread_b_before_ns","pread_b_after_ns"};uint64_t ts[]={e.a_before,e.a_after,e.b_before,e.b_after};
  for(unsigned i=0;i<4;++i){o<<",\""<<names[i]<<"\":";if(e.clock_valid&(1<<i))o<<ts[i];else o<<"null";}
  o<<",\"a\":";snapshot(o,e.a,e.attempted?e.ar:0);o<<",\"b\":";snapshot(o,e.b,e.attempted?e.br:0);
  o<<",\"snapshots_equal\":";if(e.attempted&&e.ar==64&&e.br==64)o<<(e.a==e.b?"true":"false");else o<<"null";
  o<<",\"legacy_stable\":"<<int(e.stable)<<",\"validity\":\""<<validityName(e.validity)<<"\",\"validity_scope\":\"capture::validity_at_original_read_after; stable-only; not L2B approval\",\"legacy_poll_event_emitted\":"<<int(e.legacy_poll)<<",\"legacy_validity_evaluated\":"<<int(e.legacy_validity_evaluated)<<",\"duplicate_flag\":"<<int(e.duplicate)<<",\"reason_bits\":"<<e.reason;
  o<<",\"last_success_poll\":"<<e.last_success_poll<<",\"last_success_monotonic_ns\":"<<e.last_success_mono<<",\"last_failure_poll\":"<<e.last_failure_poll<<",\"last_success_epoch\":"<<e.last_epoch<<",\"last_success_seq\":"<<e.last_seq<<",\"last_success_source\":"<<e.last_source<<",\"last_success_ready_u32\":"<<e.last_ready;
  o<<",\"stat_called\":"<<int(e.stat_called)<<",\"stat_context\":";if(!e.stat_known)o<<"null";else{
   o<<"{\"scope\":\"PATH_STAT_OBSERVATION_NOT_FSTAT\",\"poll_id\":"<<e.last_stat_poll<<",\"poll_start_ns\":"<<e.stat_mono<<",\"ret\":"<<e.stat_ret<<",\"errno\":";if(e.stat_ret<0)o<<e.stat_errno;else o<<"null";
   o<<",\"size\":";if(e.stat_ret==0)o<<e.stat_size;else o<<"null";o<<",\"dev\":"<<e.stat_dev<<",\"ino\":"<<e.stat_ino<<'}';}
  o<<",\"open_called\":"<<int(e.open_called)<<",\"open_ret\":"<<e.open_ret<<",\"open_errno\":";if(e.open_called&&e.open_ret<0)o<<e.open_errno;else o<<"null";
  o<<",\"close_called\":"<<int(e.close_called)<<",\"close_ret\":"<<e.close_ret<<",\"close_errno\":";if(e.close_called&&e.close_ret<0)o<<e.close_errno;else o<<"null";
  static const char* reasons[]={"NONE","INITIAL_OR_NO_FD_OPEN","RETRY_AFTER_OPEN_FAILURE","PATH_IDENTITY_CHANGED","STAT_FAILED","SIZE_NOT_64"};
  o<<",\"reopen_reason\":\""<<reasons[e.reopen]<<"\"}\n";return o.str();
 }
 // Control-thread exporter: only after producer/writer joins and legacy finalization.
 bool dump(const std::string& dir,bool production_failed) noexcept {
  int fd=-1;uint64_t bytes=0;try{
   auto begin=now(CLOCK_MONOTONIC);
   auto writeAll=[&](const std::string& s){size_t at=0;while(at<s.size()){ssize_t n=::write(fd,s.data()+at,s.size()-at);if(n<0&&errno==EINTR)continue;if(n<=0)throw std::runtime_error("diagnostic write failed");at+=size_t(n);}bytes+=s.size();};
   fd=::open((dir+"/ima1_reader_diagnostics.jsonl").c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);if(fd<0)throw std::runtime_error("diagnostic exclusive create failed");
   for(uint64_t i=0;i<stored;++i){auto s=row(events[i]);if(s.size()>4096)throw std::runtime_error("diagnostic row budget exceeded");writeAll(s);}
   if(fsync(fd))throw std::runtime_error("diagnostic sync failed");if(::close(fd)){fd=-1;throw std::runtime_error("diagnostic close failed");}fd=-1;
   auto end=now(CLOCK_MONOTONIC);std::ostringstream s;
   s<<"{\"schema\":1,\"status\":\""<<(allocation_failed?"DISABLED_ALLOCATION_FAILURE":dropped?"DIAGNOSTIC_TRUNCATED":(clock_errors||observer_errors)?"DIAGNOSTIC_OBSERVER_ERROR":"DIAGNOSTIC_COMPLETE")<<"\",\"complete_export\":true,\"production_failed\":"<<(production_failed?"true":"false")<<",\"total_poll\":"<<total<<",\"attempted_read_poll\":"<<attempted<<",\"full_read_poll\":"<<full<<",\"unstable_poll\":"<<unstable<<",\"no_fd_poll\":"<<no_fd<<",\"semantic_invalid_stable_poll\":"<<semantic_invalid<<",\"eligible\":"<<eligible<<",\"stored\":"<<stored<<",\"dropped\":"<<dropped<<",\"first_dropped_poll\":"<<first_dropped<<",\"last_dropped_poll\":"<<last_dropped<<",\"slots\":"<<slots<<",\"event_bytes\":"<<sizeof(Ima1DiagEvent)<<",\"buffer_bytes\":"<<slots*sizeof(Ima1DiagEvent)<<",\"extra_clock_calls\":"<<extra_clocks<<",\"extra_clock_errors\":"<<clock_errors<<",\"observer_errors\":"<<observer_errors<<",\"events_file_bytes\":"<<bytes<<",\"event_export_ns\":"<<end-begin<<",\"category_counts\":[";
   for(unsigned i=0;i<10;++i){if(i)s<<',';s<<category[i];}
   s<<"],\"final_close_called\":"<<int(final_close_called)<<",\"final_close_ret\":"<<final_close_ret<<",\"final_close_errno\":"<<final_close_errno<<",\"power_loss_persistence\":false,\"physical_sync\":\"PENDING\"}\n";
   fd=::open((dir+"/ima1_reader_diagnostics_summary.json").c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);if(fd<0)throw std::runtime_error("diagnostic summary exclusive create failed");writeAll(s.str());if(fsync(fd))throw std::runtime_error("diagnostic summary sync failed");if(::close(fd)){fd=-1;throw std::runtime_error("diagnostic summary close failed");}fd=-1;return true;
  }catch(const std::exception& e){if(fd>=0)::close(fd);error=e.what();return false;}
 }
};
static_assert(Ima1ReaderDiag::slots*sizeof(Ima1DiagEvent)<=4*1024*1024,"IMA1 total event buffer budget");
}
