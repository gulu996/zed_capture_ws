// SYNTHETIC syscall fault injection around the actual extracted Recorder reader.
#include "zed_capture/core.hpp"
#include "zed_capture/ima1_reader_diag.hpp"
#include <fstream>
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <fcntl.h>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>
using capture::now;
static uint64_t stamp(uint64_t n){return n;}
namespace boost {using std::make_shared;}
namespace zed_capture {
struct TimeAnchor {
 struct {uint64_t stamp=0;} header;
 uint64_t reader_monotonic_ns=0,writer_epoch=0,write_sequence=0,imu_stamp_ns=0,host_monotonic_ns=0,update_monotonic_ns=0,uncertainty_ns=0,skipped_updates=0;
 uint32_t clock_source=0,ready=0;std::vector<uint8_t> raw_state;std::string validity;
};
}
struct Scenario {std::string name;ssize_t a=64,b=64;int ae=0,be=0,stat_rc=0,stat_errno=0,open_rc=73;uint64_t inode=1;int size=64;uint64_t seq=2,epoch=1;uint32_t source=2,ready=1;bool unequal=false;bool payload_only=false;bool bad_protocol=false;};
static std::vector<Scenario> scenarios;static size_t current=0;static int reads=0;
static uint64_t mono=1000000000,clock_calls=0;static std::vector<std::string> calls;
static std::function<void()> finish_poll;
extern "C" int __wrap_clock_gettime(clockid_t id,timespec* t){++clock_calls;if(std::getenv("IMA1_DIAG_CLOCK_FAILURE")&&reads==1){errno=EINVAL;return -1;}uint64_t n=mono+(id==CLOCK_REALTIME?1700000000000000000ULL:0);t->tv_sec=n/1000000000;t->tv_nsec=n%1000000000;return 0;}
extern "C" int __wrap_stat(const char*,struct stat* st){const auto& s=scenarios.at(current);calls.push_back("stat");if(s.stat_rc<0){errno=s.stat_errno;return s.stat_rc;}st->st_ino=s.inode;st->st_dev=9;st->st_size=s.size;return 0;}
extern "C" int __wrap___xstat(int,const char* p,struct stat* st){return __wrap_stat(p,st);}
extern "C" int __wrap_open(const char*,int,...){const auto& s=scenarios.at(current);calls.push_back("open");if(s.open_rc<0)errno=EACCES;return s.open_rc;}
extern "C" int __wrap_close(int){calls.push_back("close");return 0;}
extern "C" ssize_t __wrap_pread(int fd,void* p,size_t n,off_t at){
 const auto& s=scenarios.at(current);if(n!=64||at!=0||fd!=73)throw std::runtime_error("unexpected read arguments");
 bool b=reads++==1;calls.push_back(b?"preadB":"preadA");auto rc=b?s.b:s.a;
 if(rc<0){errno=b?s.be:s.ae;return rc;}
 static capture::Anchor prev{};capture::Anchor v{};v.magic=s.bad_protocol?0:0x31414d49;v.version=1;v.seq=s.seq+(b&&s.unequal?2:0);v.epoch=s.epoch;v.device=123456789+(b&&s.payload_only?1:0);v.host=mono-100;v.updated=mono-50;v.source=s.source;v.ready=s.ready;
 if(s.name=="duplicate")v=prev;else if(b)prev=v;
 std::memcpy(p,&v,size_t(rc));errno=ERANGE; // stale errno deliberately retained on successful reads
 return rc;
}
extern "C" int __wrap_clock_nanosleep(clockid_t,int,const timespec*,timespec*){finish_poll();++current;reads=0;mono+=101000000;return 0;}
struct Recorder {
 std::unique_ptr<capture::Ima1ReaderDiag> ima1_diag{new capture::Ima1ReaderDiag};
 std::atomic<bool> done{false},failed{false};std::string anchor_path="SYNTHETIC_NOT_A_DEVICE";std::mutex mutex;
 std::atomic<uint64_t> poll_count{0},poll_max_interval{0},poll_max_lateness{0},poll_torn_reads{0},poll_duplicate_reads{0},skipped_anchors{0},anchor_count{0};
 capture::Anchor anchor_snapshot{};bool anchor_available=false;
 std::ostringstream anchors,poll_events;
 struct Bag {std::vector<zed_capture::TimeAnchor> messages;void write(const char*,uint64_t,const zed_capture::TimeAnchor& m){messages.push_back(m);}} bag;
 struct Pub {void publish(const std::shared_ptr<zed_capture::TimeAnchor>&){}} anchor_pub;
 bool push(size_t,std::function<void()> f){f();return true;}void fail(const std::string& e){failed=true;throw std::runtime_error(e);}
#include "reader_body.inc"
};
int main(int argc,char** argv){
 auto add=[](const char* name){Scenario s;s.name=name;scenarios.push_back(s);};
 add("open_and_equal");add("duplicate");add("odd");scenarios.back().seq=3;
 add("unequal");scenarios.back().unequal=true;
 add("A_EBADF");scenarios.back().a=-1;scenarios.back().ae=EBADF;
 add("B_EIO");scenarios.back().b=-1;scenarios.back().be=EIO;
 add("both_errors");scenarios.back().a=scenarios.back().b=-1;scenarios.back().ae=EINTR;scenarios.back().be=EIO;
 add("A_zero");scenarios.back().a=0;add("B_zero");scenarios.back().b=0;
 add("A_short_17");scenarios.back().a=17;add("B_short_63");scenarios.back().b=63;
 add("payload_changed_same_seq");scenarios.back().payload_only=true;
 add("bad_protocol_but_stable");scenarios.back().bad_protocol=true;
 add("seq_jump");scenarios.back().seq=10;
 add("epoch_change");scenarios.back().epoch=2;scenarios.back().seq=2;
 add("clock_unknown");scenarios.back().epoch=2;scenarios.back().source=7;
 add("ready_false");scenarios.back().epoch=2;scenarios.back().ready=0;
 add("stat_ENOENT");scenarios.back().stat_rc=-1;scenarios.back().stat_errno=ENOENT;
 add("open_denied");scenarios.back().open_rc=-1;
 add("reopen");scenarios.back().inode=2;
 add("bad_size");scenarios.back().size=63;
 add("reopen_after_bad_size");scenarios.back().inode=3;
 Recorder r;finish_poll=[&]{
  const auto& s=scenarios.at(current);std::cout<<s.name<<" reads="<<reads<<" stable_snapshot="<<r.anchor_available<<" snapshot_seq="<<r.anchor_snapshot.seq<<" torn="<<r.poll_torn_reads<<" duplicate="<<r.poll_duplicate_reads<<" skipped="<<r.skipped_anchors<<" anchors="<<r.anchor_count<<" calls=";for(auto& c:calls)std::cout<<c<<',';std::cout<<'\n';calls.clear();
  if(current+1==scenarios.size())r.done=true;
 };
 r.anchorLoop();if(argc>1){std::ofstream f(argv[1]);for(size_t i=0;i<r.ima1_diag->stored;++i)f<<capture::Ima1ReaderDiag::row(r.ima1_diag->events[i]);}std::cout<<"ANCHORS\n"<<r.anchors.str()<<"POLL_EVENTS\n"<<r.poll_events.str();
 if(r.poll_torn_reads!=10||r.skipped_anchors!=3||r.anchor_count!=8) {std::cerr<<"summary check: torn="<<r.poll_torn_reads<<" skipped="<<r.skipped_anchors<<" anchors="<<r.anchor_count<<'\n';return 2;}
}
