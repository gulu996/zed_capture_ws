#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <sstream>
#include <string>

namespace capture {
constexpr uint64_t input_timeout_ns = 3000000000ULL;
constexpr uint64_t input_startup_grace_ns = 5000000000ULL;
constexpr size_t input_count = 4;
inline const char* inputName(size_t i) {
 const char* names[] = {"zed_video", "zed_hid", "livox_lidar", "livox_imu"};
 return names[i];
}
struct InputSnapshot {
 uint64_t now_ns = 0, start_ns = 0;
 std::array<uint64_t, input_count> last_ns{};
 bool enabled() const {
  return now_ns >= start_ns && now_ns - start_ns > input_startup_grace_ns;
 }
 const char* state(size_t i) const {
  if (!last_ns[i]) return "MISSING";
  // A true future value is a clock error, never an unsigned stale age.
  if (last_ns[i] > now_ns) return "CLOCK_INVALID";
  return now_ns - last_ns[i] > input_timeout_ns ? "STALE" : "FRESH";
 }
 bool triggers(size_t i) const {
  return enabled() && (!last_ns[i] || last_ns[i] > now_ns ||
                      now_ns - last_ns[i] > input_timeout_ns);
 }
 bool failed() const {
  for (size_t i=0; i<input_count; ++i) if (triggers(i)) return true;
  return false;
 }
 std::string json() const {
  std::ostringstream s;
  s << "{\"evaluation_monotonic_ns\":" << now_ns << ",\"capture_start_monotonic_ns\":" << start_ns
    << ",\"timeout_ns\":" << input_timeout_ns << ",\"startup_grace_ns\":" << input_startup_grace_ns
    << ",\"enabled\":" << (enabled()?"true":"false") << ",\"streams\":{";
  for (size_t i=0; i<input_count; ++i) {
   if (i) s << ',';
   s << '"' << inputName(i) << "\":{\"last_arrival_monotonic_ns\":" << last_ns[i] << ",\"age_ns\":";
   if (!last_ns[i] || last_ns[i]>now_ns) s << "null"; else s << now_ns-last_ns[i];
   s << ",\"state\":\"" << state(i) << "\",\"triggered\":" << (triggers(i)?"true":"false") << '}';
  }
  s << "},\"triggered_inputs\":[";
  bool comma=false;
  for (size_t i=0; i<input_count; ++i) if (triggers(i)) {
   if (comma) s << ',';
   s << '"' << inputName(i) << '"'; comma=true;
  }
  s << "]}";
  return s.str();
 }
};

// Read each heartbeat ONCE, then sample CLOCK_MONOTONIC. A callback may run
// between these operations; its later update cannot alter this local snapshot.
// Reading 'now' first allowed a fresh callback timestamp to underflow now-last.
template<class ReadClock>
InputSnapshot snapshotInputs(const std::array<const std::atomic<uint64_t>*, input_count>& inputs,
                             uint64_t start, ReadClock clock) {
 InputSnapshot s; s.start_ns=start;
 for (size_t i=0; i<input_count; ++i) s.last_ns[i]=inputs[i]->load();
 s.now_ns=clock();
 return s;
}
}
