# Header stamp = raw device ticks * 78125 / 2 ns, integer floor.
std_msgs/Header header
uint64 sample_id
uint64 device_ticks
uint64 read_monotonic_before_ns
uint64 read_monotonic_after_ns
uint64 read_realtime_ns
bool imu_valid
uint8 frame_sync
uint8 sync_capabilities
uint32 frame_sync_count
uint8[] raw_hid_report
string sync_status
