#pragma once
#include <atomic>
#include <condition_variable>
#include <deque>
#include <functional>
#include <mutex>
#include <algorithm>
namespace capture {
struct RecordingJob {size_t bytes;std::function<void()> work;};
enum class EnqueueResult {Accepted,Closed,Full};
// Shared by the production C5-F single writer and its offline bag integration test.
inline EnqueueResult recordingEnqueue(std::deque<RecordingJob>& q,size_t& bytes,size_t& peak,
 size_t capacity,bool closed,bool failed,size_t n,std::function<void()> work) {
 if(closed||failed)return EnqueueResult::Closed;
 if(n>capacity||bytes>capacity-n)return EnqueueResult::Full;
 q.push_back({n,std::move(work)});bytes+=n;peak=std::max(peak,bytes);return EnqueueResult::Accepted;
}
inline void recordingDrain(std::mutex& mutex,std::condition_variable& cond,
 std::deque<RecordingJob>& queue,size_t& queued,bool& closed) {
 for(;;){RecordingJob j;{std::unique_lock<std::mutex> lock(mutex);
  cond.wait(lock,[&]{return closed||!queue.empty();});if(queue.empty()&&closed)break;
  j=std::move(queue.front());queue.pop_front();}
  j.work();{std::lock_guard<std::mutex> lock(mutex);queued-=j.bytes;}
 }
}
}
