#pragma once
#include <csignal>
namespace field_capture {
// Signal handler performs no ROS, allocation, locking, logging or filesystem work.
static volatile std::sig_atomic_t stop_requested = 0;
inline void request_stop(int) { stop_requested = 1; }
inline bool stopping() { return stop_requested != 0; }
inline void install() {
  struct sigaction sa{};
  sa.sa_handler=request_stop; sigemptyset(&sa.sa_mask);
  sigaction(SIGINT,&sa,nullptr); sigaction(SIGTERM,&sa,nullptr);
}
}
