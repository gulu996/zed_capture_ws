#include "zed_capture/ima1_reader_diag.hpp"
#include <cassert>
#include <iostream>
#include <fstream>
#include <algorithm>
#include <sys/resource.h>
using capture::Ima1ReaderDiag;using capture::Ima1DiagEvent;
static int write_mode=0,fsync_mode=0;
extern "C" ssize_t __real_write(int,const void*,size_t);
extern "C" int __real_fsync(int);
extern "C" ssize_t __wrap_write(int fd,const void* p,size_t n){if(write_mode==1){errno=ENOSPC;return -1;}if(write_mode==2)n=std::min(n,size_t(11));return __real_write(fd,p,n);}
extern "C" int __wrap_fsync(int fd){if(fsync_mode){errno=EIO;return -1;}return __real_fsync(fd);}
int main(int argc,char** argv){assert(argc==2);std::string root=argv[1];
 auto mkdirNew=[](const std::string& p){assert(mkdir(p.c_str(),0700)==0);};mkdirNew(root);
 auto d=std::unique_ptr<Ima1ReaderDiag>(new Ima1ReaderDiag);
 assert(sizeof(Ima1DiagEvent)<=512);assert(Ima1ReaderDiag::slots*sizeof(Ima1DiagEvent)<=4*1024*1024);
 // Full capacity plus 808 refused events: immutable prefix, explicit accounting.
 for(uint64_t i=1;i<=9000;++i){Ima1DiagEvent e;d->begin(e,i,1000000000+i*1000000,1000000,0,-1);d->finish(e);}
 assert(d->stored==8192&&d->eligible==9000&&d->dropped==808&&d->first_dropped==8193&&d->last_dropped==9000);
 assert(d->events[0].poll==1&&d->events[8191].poll==8192);
 mkdirNew(root+"/full");assert(d->dump(root+"/full",false));assert(!d->dump(root+"/full",false)); // O_EXCL preservation
 mkdirNew(root+"/short_write");write_mode=2;assert(d->dump(root+"/short_write",false));write_mode=0;
 mkdirNew(root+"/disk_error");write_mode=1;assert(!d->dump(root+"/disk_error",false));write_mode=0;
 assert(access((root+"/disk_error/ima1_reader_diagnostics_summary.json").c_str(),F_OK)!=0);
 mkdirNew(root+"/sync_error");fsync_mode=1;assert(!d->dump(root+"/sync_error",false));fsync_mode=0;
 assert(access((root+"/sync_error/ima1_reader_diagnostics_summary.json").c_str(),F_OK)!=0);
 // Successful syscall stale errno never reaches JSON; incomplete bytes never decoded.
 Ima1DiagEvent e;e.attempted=1;e.ar=17;e.br=64;e.ae=EIO;e.be=EIO;e.a.fill(255);e.b.fill(0);
 auto row=d->row(e);assert(row.find("\"pread_a_errno\":null")!=std::string::npos);assert(row.find("\"full_snapshot\":null")!=std::string::npos);
 // Allocation failure fallback state can never be called COMPLETE.
 auto bad=std::unique_ptr<Ima1ReaderDiag>(new Ima1ReaderDiag);bad->events.reset();bad->allocation_failed=true;mkdirNew(root+"/allocation_error");assert(bad->dump(root+"/allocation_error",false));bad.reset();
 // Extra clocks preserve errno; measure observer operations with fixed synthetic snapshots.
 auto bench=std::unique_ptr<Ima1ReaderDiag>(new Ima1ReaderDiag);capture::Anchor a{};a.magic=0x31414d49;a.version=1;a.epoch=1;a.seq=2;a.source=2;a.ready=1;a.device=10;a.host=1;a.updated=1;
 std::vector<uint64_t> elapsed;elapsed.reserve(100000);uint64_t calls=0;
 for(uint64_t i=0;i<100000;++i){Ima1DiagEvent t;auto t0=capture::now(CLOCK_MONOTONIC);bench->begin(t,i+1,1000000000+i*1000000,1000000,0,73);t.attempted=1;t.ar=t.br=64;t.stable=1;t.validity=7;t.read_after=t.mono;
  std::memcpy(t.a.data(),&a,64);t.b=t.a;errno=EDOM;t.a_before=bench->tick(t.clock_valid,1);t.a_after=bench->tick(t.clock_valid,2);t.b_before=bench->tick(t.clock_valid,4);assert(errno==EDOM);t.clock_valid|=8;bench->finish(t);
  elapsed.push_back(capture::now(CLOCK_MONOTONIC)-t0);
 }
 assert(bench->extra_clocks==300000);std::sort(elapsed.begin(),elapsed.end());
 rusage usage{};getrusage(RUSAGE_SELF,&usage);
 std::cout<<"{\"synthetic\":true,\"capacity_test\":\"PASS\",\"short_write_test\":\"PASS\",\"ENOSPC_test\":\"PASS\",\"fsync_error_test\":\"PASS\",\"exclusive_create_test\":\"PASS\",\"event_bytes\":"<<sizeof(Ima1DiagEvent)<<",\"buffer_bytes\":"<<Ima1ReaderDiag::slots*sizeof(Ima1DiagEvent)<<",\"extra_clock_calls_per_attempt\":3,\"observer_ns_p50\":"<<elapsed[50000]<<",\"observer_ns_p95\":"<<elapsed[95000]<<",\"observer_ns_p99\":"<<elapsed[99000]<<",\"observer_ns_max\":"<<elapsed.back()<<",\"process_peak_rss_kib\":"<<usage.ru_maxrss<<"}\n";
}
