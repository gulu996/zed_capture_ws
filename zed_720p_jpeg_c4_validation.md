**C4 720P Q95/420 实机影子验证**

会话：`/home/jetson/zed_capture_data/20261017_201258_9aeecafa`；联合诊断：`/home/jetson/clock_diag/runs/joint_20261017_201242_1eec78f5`。

| 验收 | 状态 |
| --- | --- |
| CAPTURE_RUNTIME | CAPTURE_RUNTIME_PASS |
| VIDEO_CONTINUITY | FAIL |
| JPEG_SHADOW_COMPLETION | PASS |
| JPEG_SHADOW_QUEUE | PASS |
| JPEG_SHADOW_LATENCY | FAIL |
| MID360_CONTINUITY | PASS |
| CLOCK_DIAGNOSTIC | CLOCK_DIAGNOSTIC_PASS |
| DATA_INTEGRITY | FAIL |
| L2B_MAPPING | PENDING |
| PHYSICAL_SYNC | PENDING |

原始YUYV仍写入bag；JPEG仅编码并记录尺寸/时序/SOF，未写图像或替换原Header。
图像：{'count': 901, 'fps': 29.933296641763494, 'duration_s': 30.066852, 'backwards': 0, 'duplicates': 0, 'median_interval_ms': 33.37, 'max_interval_ms': 66.751, 'long_intervals': 2}。Bag：3456347881 bytes。
JPEG统计：`{'enabled': True, 'quality': 95, 'subsampling': '420', 'queue_capacity': 4, 'inputs': 901, 'completed': 901, 'encode_failed': 0, 'rejected': 0, 'unlogged_inputs': 0, 'queue_peak': 1, 'max_queue_wait_ns': 5747883, 'worker_joined': True, 'queue_drained': True, 'event_log_ok': True, 'jpeg_files_written': 0, 'conversion_reference': 'OpenCV COLOR_YUV2BGR_YUY2 BT601 limited; actual colorimetry must be checked separately'}`。
双目纯编码(ms)：{'p50': 18.121576, 'p95': 20.516543, 'p99': 21.129055, 'max': 22.171824}；完整worker(ms)：{'p50': 25.524758, 'p95': 28.736412, 'p99': 29.607613, 'max': 35.985907}；复制完成至编码完成(ms)：{'p50': 25.566655, 'p95': 28.765539, 'p99': 30.087247, 'max': 36.030802}。
超期pair_id：[1, 2, 257]。原因计数：{}。
资源：{'status': 'OBSERVED', 'children_peak_cpu_percent_one_core_100': 140.61575155494762, 'children_peak_rss_mb': 246.034432, 'system_peak_cpu_percent': 36.065573770491795, 'gpu_peak_load_percent': 0.0, 'peak_block_write_MBps': 118.23395679471035, 'bag_growth_MBps': 104.04542336760461, 'peak_dirty_mb': 570.5546875, 'note': 'block writes may lag due to page cache; capture node fsyncs the closed bag; reused Livox process is not included in owned-child CPU figures'}。
C2资源：{'status': 'OBSERVED', 'children_peak_cpu_percent_one_core_100': 70.52412090086845, 'children_peak_rss_mb': 225.087488, 'system_peak_cpu_percent': 25.669291338582678, 'gpu_peak_load_percent': 0.0, 'peak_block_write_MBps': 116.53265269099711, 'bag_growth_MBps': 104.55810453683924, 'peak_dirty_mb': 590.51953125, 'note': 'block writes may lag due to page cache; capture node fsyncs the closed bag; reused Livox process is not included in owned-child CPU figures'}。
原始队列峰值：4092373，C2：7885273 bytes。

温度/频率时间序列见同目录thermal.jsonl（1Hz）；既有resources.jsonl及check_result提供CPU/RSS/磁盘统计。不得凭一次不同时间实验认定JPEG是异常唯一原因。
ZED IMU既有异常和锚点漏读保持严格DATA_INTEGRITY结论。MID360这里只评价ROS可观测连续性，时钟源/同步须独立复核。
全部原始与影子异常按pair_id连接在c4_result.json/video_anomaly_timeline，可继续对齐CPU、writer、V4L2。
L2B、物理同步、720P标定及真实JPEG录包均未在本轮完成。是否进入正式压缩录包需复核本报告及色彩元数据后另行授权，不自动实施。

温度/频率：{'samples': 30, 'CPU_C_first_last_max': [48.0, 48.5, 48.5], 'nonzero_cooling_states': [], 'scaling_kHz_observed': ['1036800', '1267200', '1344000', '729600', '806400', '883200', '960000'], 'interpretation': '1Hz samples; DVFS is not proof of thermal throttling; power not measured'}。
C4−C2同口径资源差：{'children_peak_cpu_percent_one_core_100': 70.09163065407917, 'children_peak_rss_mb': 20.946944000000002, 'system_peak_cpu_percent': 10.396282431909118, 'gpu_peak_load_percent': 0.0, 'peak_block_write_MBps': 1.701304103713241, 'bag_growth_MBps': -0.5126811692346251, 'peak_dirty_mb': -19.96484375}。CPU单位为单核=100%，复用的外部Livox进程可能不计入owned-child统计。
