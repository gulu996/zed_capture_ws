**C5-F实际验证（自动记录，仍需复核）**

原始YUYV未写入本实验bag；JPEG文件与sensors.bag独立保存。编码、写盘失败及原始视频缺口分别保留。L2-B和物理同步不由存储通过推导。

```json
{
  "session": "/home/jetson/zed_capture_data/20261018_141750_265b3cbf",
  "test_dir": "/home/jetson/clock_diag/runs/joint_20261018_141734_2ce3bbf7",
  "CAPTURE_RUNTIME": "CAPTURE_RUNTIME_PASS",
  "JPEG_FILE_STORAGE": "PASS",
  "DATA_INTEGRITY": "FAIL",
  "SLAM_REQUIRED_DATA_STATUS": {
    "status": "FAIL",
    "required_sensor_recording": "PASS",
    "reasons": [
      "runtime/clock/GPS source not validated"
    ],
    "image_gap_policy": {
      "max_events": 3,
      "max_missing_period_ratio": 0.01,
      "max_interval_ms": 100.0
    },
    "cadence_missing_periods_estimate": 0,
    "missing_period_ratio": 0.0,
    "warning": "cadence estimate is not physical exposure loss count; driver sequence missing is separate",
    "L2B_MAPPING": "PENDING",
    "PHYSICAL_SYNC": "PENDING"
  },
  "CLOCK_DIAGNOSTIC": "CLOCK_DIAGNOSTIC_FAIL",
  "L2B_MAPPING": "PENDING",
  "PHYSICAL_SYNC": "PENDING",
  "jpeg_files": {
    "mode": "jpeg_files",
    "inputs": 903,
    "completed": 903,
    "encode_failed": 0,
    "encode_queue_rejected": 0,
    "write_queue_rejected": 0,
    "write_failed": 0,
    "input_rejected": 0,
    "unlogged": 0,
    "encode_queue_peak": 1,
    "write_queue_peak": 2,
    "write_queue_bytes_peak": 509308,
    "queue_capacity": 4,
    "write_bytes_limit": 33554432,
    "final_synced": true,
    "failed": false,
    "workers_joined": true,
    "max_sync_ns": 89318089,
    "sync_interval_ms": 1000,
    "sync_error": ""
  },
  "performance": {
    "encoding_latency_ms": {
      "p50": 25.62574,
      "p95": 28.9349639,
      "p99": 29.38366844,
      "max": 30.253254
    },
    "encode_queue_wait_ms": {
      "p50": 0.019515,
      "p95": 0.07184209999999998,
      "p99": 0.24297153999999999,
      "max": 0.252095
    },
    "writer_queue_wait_ms": {
      "p50": 0.021405,
      "p95": 0.0526445,
      "p99": 19.19272318,
      "max": 56.641357
    },
    "write_ms": {
      "p50": 0.636738,
      "p95": 0.9391347,
      "p99": 1.1487466000000004,
      "max": 1.40273
    },
    "conversion_ms": {
      "p50": 7.370073,
      "p95": 8.1857609,
      "p99": 8.457365120000002,
      "max": 9.502738
    },
    "jpeg_encode_ms": {
      "p50": 18.14709,
      "p95": 20.640397800000002,
      "p99": 20.88447864,
      "max": 21.856244
    }
  },
  "video": {
    "count": 903,
    "fps": 30.003911485533905,
    "duration_s": 30.062747,
    "backwards": 0,
    "duplicates": 0,
    "median_interval_ms": 33.363,
    "max_interval_ms": 33.479,
    "long_intervals": 0
  },
  "v4l2_driver_ids_missing": 0,
  "raw_queue_peak_bytes": 392661,
  "raw_queue_overflows": 0,
  "resources": {
    "status": "OBSERVED",
    "children_peak_cpu_percent_one_core_100": 128.87698739518623,
    "children_peak_rss_mb": 242.184192,
    "system_peak_cpu_percent": 41.17647058823529,
    "gpu_peak_load_percent": 0.0,
    "peak_block_write_MBps": 13.457271073668872,
    "bag_growth_MBps": 4.062807831451201,
    "peak_dirty_mb": 134.67578125,
    "note": "block writes may lag due to page cache; capture node fsyncs the closed bag; reused Livox process is not included in owned-child CPU figures"
  },
  "errors": [
    "observed skipped anchor updates; saved history is incomplete"
  ],
  "sizes": {
    "jpeg_bytes": 236011265,
    "sensors_bag_bytes": 134446178,
    "all_session_bytes": 381832498,
    "vs_C2_3460013078_reduction_percent": 88.96442038245961,
    "observed_total_bytes_per_video_second": 12701184.559082374
  },
  "comparison_limits": "C2 has different scene/counts; no CompressedImage bag experiment performed. Per-file metadata/IO syscall overhead exists but difference not measured.",
  "anchors": {
    "status": "FAIL",
    "skipped_updates": 402,
    "complete_history_guaranteed": false
  },
  "MID_clock_types": [
    "2"
  ],
  "MID_clock_switch_counts": [
    "0"
  ],
  "temperature_C_whole_test": {
    "min": 47.281,
    "max": 49.0
  }
}
```
