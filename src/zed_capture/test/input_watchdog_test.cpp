#include "zed_capture/input_watchdog.hpp"
#include <cassert>
#include <iostream>

int main() {
 using namespace capture;
 const uint64_t start=100000000000ULL, n=start+9000000000ULL;
 std::array<std::atomic<uint64_t>, input_count> inputs{};
 std::array<const std::atomic<uint64_t>*, input_count> refs{};
 for(size_t i=0;i<input_count;++i) {inputs[i]=n-1000000;refs[i]=&inputs[i];}

 // Deterministic reproduction of the old ordering: monitor samples now,
 // callback stores a later timestamp, then monitor reads the live atomic.
 inputs[1]=n+160;
 assert(n-inputs[1].load()>input_timeout_ns); // OLD code falsely stops
 auto fresh=snapshotInputs(refs,start,[&]{return n+1000;});
 assert(!fresh.failed()); assert(fresh.last_ns[1]==n+160);
 assert(fresh.now_ns-fresh.last_ns[1]==840);

 // Clock callback represents an update after the heartbeat snapshot. Do not
 // reread that atomic when evaluating or serializing the captured decision.
 auto fixed=snapshotInputs(refs,start,[&]{inputs[1]=n+2000;return n+3000;});
 assert(fixed.last_ns[1]==n+160); assert(!fixed.failed());
 inputs[1]=n+4000;assert(!fixed.failed());

 InputSnapshot s; s.start_ns=start;s.now_ns=n;s.last_ns.fill(n-1000000);
 assert(!s.failed());
 for(size_t i=0;i<input_count;++i) {
  auto test=s;test.last_ns[i]=n-input_timeout_ns;
  assert(!test.failed()); // Original strict > 3 s retained
  --test.last_ns[i];assert(test.failed());
  for(size_t j=0;j<input_count;++j) assert(test.triggers(j)==(j==i));
  assert(std::string(test.state(i))=="STALE");
  test.last_ns[i]=0;assert(test.failed());assert(std::string(test.state(i))=="MISSING");
  test.last_ns[i]=n+1;assert(test.failed());assert(std::string(test.state(i))=="CLOCK_INVALID");
  assert(test.json().find("\"age_ns\":null")!=std::string::npos);
 }
 InputSnapshot missing;missing.start_ns=start;missing.now_ns=start+input_startup_grace_ns;
 assert(!missing.failed());++missing.now_ns;assert(missing.failed());
 for(size_t i=0;i<input_count;++i) assert(missing.triggers(i));
 auto both=s;both.last_ns[0]=both.last_ns[2]=n-input_timeout_ns-1;
 assert(both.json().find("\"triggered_inputs\":[\"zed_video\",\"livox_lidar\"]")!=std::string::npos);
 // Machine-readable fixture also checked by Python json.loads in validation.
 std::cout<<both.json()<<'\n';
 std::cerr<<"SOFTWARE_TESTED: old unsigned-underflow reproduction, ordered snapshot, frozen decisions, four stream timeouts, strict 3 s/5 s boundaries, missing/future timestamps, multi-stream diagnostics\n";
}
