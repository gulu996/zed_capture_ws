// SYNTHETIC accelerated metadata/small-file load; never sensor or JPEG performance evidence.
#include "zed_capture/jpeg_files.hpp"
#include "zed_capture/long_recording.hpp"
#include <boost/make_shared.hpp>
#include <cassert>
#include <iostream>
#include <sys/wait.h>
static capture::ShadowInput input(uint64_t id){
 auto m=boost::make_shared<zed_capture::VideoStamp>();m->pair_id=id;m->v4l2_sequence=uint32_t(id);m->header.seq=uint32_t(id);
 m->header.stamp.fromNSec(1792316492000000123ULL+id*33333333ULL);m->v4l2_sec=m->header.stamp.sec;m->v4l2_usec=m->header.stamp.nsec/1000;m->payload_valid=true;
 auto l=boost::make_shared<sensor_msgs::Image>(),r=boost::make_shared<sensor_msgs::Image>();l->header=r->header=m->header;
 return {m,l,r,capture::now(CLOCK_MONOTONIC),true};
}
static capture::FileEncoded fake(const capture::ShadowInput&){capture::FileEncoded x;x.left={255,216,255,217};x.right=x.left;x.timing={1,2,4,4,true};return x;}
static std::string read(const std::string&p){std::ifstream f(p);return {std::istreambuf_iterator<char>(f),{}};}
static void await(capture::JpegFiles& w,uint64_t n){auto until=capture::now(CLOCK_MONOTONIC)+10000000000ULL;while(w.recordedEvents()<n&&!w.failed()&&capture::now(CLOCK_MONOTONIC)<until)std::this_thread::sleep_for(std::chrono::microseconds(200));assert(w.recordedEvents()==n&&!w.failed());}
static long rss(){std::ifstream f("/proc/self/statm");long size,pages;f>>size>>pages;return pages*sysconf(_SC_PAGESIZE);}
int main(int argc,char**argv){assert(argc==2);std::string dir=argv[1];assert(!mkdir(dir.c_str(),0750));
 assert(capture::diskReserveReached(10000000000ULL,10000000000ULL,256*1024*1024));
 assert(!capture::diskReserveReached(12000000000ULL,10000000000ULL,256*1024*1024));
 bool refused=false;try{capture::validateLongRecording(true,true,false,"HD720",1200,10);}catch(...){refused=true;}assert(refused);
 capture::validateLongRecording(true,true,false,"HD720",300,10);
 auto path=dir+"/long";assert(!mkdir(path.c_str(),0750));
 std::ofstream mem(dir+"/rss.csv");mem<<"pairs,rss_bytes\n";
 capture::JpegFiles w(path,fake,[]{},1000,[](int f,const void* p,size_t n){return ::write(f,p,n);},true);
 for(uint64_t i=1;i<=9001;++i){w.submit(input(i));await(w,i);if(i%1000==0){mem<<i<<','<<rss()<<'\n';mem.flush();}}
 w.finish();assert(!w.failed());w.finish();
 auto text=read(path+"/frames.csv");assert(std::count(text.begin(),text.end(),'\n')==9002);
 assert(text.find(std::to_string(input(9001).meta->header.stamp.toNSec()))!=std::string::npos);
 assert(access((path+"/camera/right/000009/000000009001.jpg").c_str(),F_OK)==0);
 assert(read(path+"/jpeg_files_summary.json").find("\"completed\":9001")!=std::string::npos);
 assert(read(path+"/jpeg_files_summary.json").find("\"final_synced\":true")!=std::string::npos);
 // Explicit event-ledger exhaustion is fail-closed and accounted, never memory growth.
 path=dir+"/ledger_full";assert(!mkdir(path.c_str(),0750));
 {std::promise<void> entered,release;auto gate=release.get_future().share();std::atomic<int> calls{0};
 capture::JpegFiles q(path,fake,[]{},1000,[&](int fd,const void* p,size_t n){if(calls++==0){entered.set_value();gate.wait();}return ::write(fd,p,n);},true);
 q.submit(input(1));entered.get_future().wait();for(int i=2;i<80;++i)q.submit(input(i));release.set_value();q.finish();assert(q.failed());
 assert(read(path+"/jpeg_files_summary.json").find("\"inputs\":79")!=std::string::npos);}
 // Abrupt exit preserves already flushed index/files; no fabricated final success.
 path=dir+"/abrupt";assert(!mkdir(path.c_str(),0750));pid_t pid=fork();assert(pid>=0);
 if(pid==0){capture::JpegFiles q(path,fake,[]{},1000,[](int f,const void*p,size_t n){return ::write(f,p,n);},true);q.submit(input(1));await(q,1);_exit(99);}
 int status=0;assert(waitpid(pid,&status,0)==pid&&WEXITSTATUS(status)==99);
 assert(read(path+"/frames.csv").find("WRITTEN")!=std::string::npos);assert(access((path+"/jpeg_files_summary.json").c_str(),F_OK)!=0);
 std::cout<<"SOFTWARE_PASS: 9001 pairs, incremental index, shards, integer ns, bounded ledger, disk reserve, final sync, abrupt exit evidence. SYNTHETIC.\n";
}
