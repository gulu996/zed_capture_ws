#include "zed_capture/long_recording.hpp"
#include "zed_capture/jpeg_files.hpp"
#include <cassert>
#include <limits>
int main(int argc,char**argv){assert(argc==2);std::string d=argv[1];assert(!mkdir(d.c_str(),0750));
 assert(capture::bagLimitReached(8000000000ULL));assert(!capture::bagLimitReached(7999999999ULL));
 assert(capture::diskReserveReached(0,10000000000ULL,256*1024*1024));
 assert(capture::diskReserveReached(10335544319ULL,10000000000ULL,256*1024*1024));
 assert(!capture::diskReserveReached(10335544320ULL,10000000000ULL,256*1024*1024));
 for(double sec:{0.,301.,1200.,std::numeric_limits<double>::infinity()}){bool caught=false;try{capture::validateLongRecording(true,true,false,"HD720",sec,10);}catch(...){caught=true;}assert(caught);}
 capture::validateLongRecording(true,true,false,"HD720",300.,10.);
 {std::ofstream f(d+"/jpeg_progress.jsonl");f<<"KEEP";}
 bool caught=false;try{capture::JpegFiles w(d,[](const capture::ShadowInput&){return capture::FileEncoded{};},[]{},1000,[](int f,const void*b,size_t n){return ::write(f,b,n);},true);}catch(...){caught=true;}assert(caught);
 std::ifstream f(d+"/jpeg_progress.jsonl");std::string v;f>>v;assert(v=="KEEP");
}
