# 笔记本 L2-B 复用输入约定

此文档定义适配边界，不实现另一套时间映射算法。

1. `VideoStamp` 和 `video_timestamps.csv` 是视频时间的权威原始输入。保存 `v4l2_sec/usec`（CSV 合成为整数 `raw_ns`）、真实 `v4l2_sequence`、完整 `flags`、`timestamp_type`、`timestamp_source`、`pair_id`，以及 DQBUF 前后的 CLOCK_MONOTONIC 和随后一次 CLOCK_REALTIME。左右目从同一 mmap 缓冲区复制，使用同一 raw stamp 和 V4L2 sequence；`pair_id` 是会话内每次 DQBUF 的软件计数，不能代替硬件/驱动序号。
2. 上游 `Frame.timestamp` 是首帧主机 wall time 加 V4L2 相对时间；其 `frame_id` 是软件计数。当前保留这个重基准结果作为 `oc_rebased_ns` 辅助字段，不把它输入统一映射作为原始时间。去掉轮询 latest-frame 的使用，改为每次 DQBUF 的同步回调，避免 latest-slot 覆盖无法追踪。
3. 当 `flags & 0xe000 == 0x2000` 时，V4L2 声明 CLOCK_MONOTONIC，可与同机主机单调时钟比较；UNKNOWN/COPY 不允许默认当作单调时钟。`flags & 0x70000` 的 EOF=0、SOE=0x10000 是驱动声明的采样事件；都不能直接声称为双目曝光中心或实际物理精度。V4L2 sequence 能看见的丢帧范围不一定覆盖相机端及所有 USB 丢失。[Linux V4L2 buffers](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/buffer.html)
4. `ImuStamp`、`zed_imu_raw.csv` 保留完整 HID report（在上游第一次丢弃、浮点转换、时间重基准、漂移修正之前）。`device_ticks` 使用上游定义的 39062.5 ns/tick；ROS header 采用整数 `ticks*78125/2` 向下取整，原 tick 保留了 0.5 ns 量化余数。保留 `frame_sync`、`sync_capabilities`、`frame_sync_count`，不调用 Open Capture `enableSensorSync`，不声明这些字段已经建立视频-IMU物理对应。[官方传感器定义](https://github.com/stereolabs/zed-open-capture/blob/master/include/sensorcapture_def.hpp)
5. `/home/jetson/timeshare_imu` 使用现有 Livox 代码的 IMA1 v1 小端 64 字节 ABI，结构 `<IIQQQQQIIQ`：magic、version、writer_epoch、write_sequence、imu_stamp_ns、host_monotonic_ns、update_monotonic_ns、clock_source、ready、uncertainty_ns。双次 pread 一致且序号为偶数才保存。原文件只读，遇 inode 替换重开。所有观察到的完整新状态逐条保存，含未就绪、异常状态。1 kHz 轮询不能保证读出单槽文件的所有历史；`skipped_updates` 据序号差统计可观察漏读，检测到漏读时完整性检查失败。不可声称恢复了未读到的旧锚点。
6. 现有 Livox `host_monotonic_ns` 在 SDK IMU 回调处采样，经现有通路发布，不是 rosbag 接收时间。它仍包含网络和软件传输延迟。默认 10 ms 的 `uncertainty_ns` 是配置值，不是本次测出的精度。当前只输出 `HOST_ARRIVAL_ANCHOR` 有效性及 `SYNC_PENDING`，不复制最近的雷达时间戳到图像。
7. `session.json` 有 boot_id、会话起始 CLOCK_MONOTONIC/REALTIME、配置、序列号、校准未知值；bag 和 sidecar 同目录唯一会话 ID。重启、回退、重复、源切换、锚点过期、wall clock 跳变在后续 L2-B 中必须按各自原始时钟处理。本地审计工具仅做检测和输入摘要，不输出统一时钟拟合。
8. L2-B 同步后优先复用协议解析、锚点筛选、漂移/异常/重启处理、左右目共用映射及测试框架。新增 Open Capture 适配器，将上述原始输入送入通用接口；不得复用 SDK 4.1.4 的原始时间语义、自动偏移或海康 0.1 秒补偿。保留原始 bag，统一时间可生成新的离线派生结果，不覆盖原数据。

源码证据保留在 `evidence/upstream_snapshot` 和 `evidence/open_capture.patch`。当前两路 IMU 的模长互相关只是离线校验；没有相机内参、雷达相机外参和曝光时间验证，不能声明数据已能直接进入 FAST-LIVO2。

2026-10-15 首次实机后补充：新采集的 `reader_monotonic_ns` 在双次 pread 完成后采样，sidecar 同时保存 `read_before_ns/read_after_ns`、`poll_interval_ns` 和 `wake_lateness_ns`。旧会话该字段在读取前采样，存在少量更新落在读取期间导致的 HOST_CLOCK_INVALID 误判；旧数据及标签不重写，适配时必须结合软件清单识别语义。A=锚点历史完整性与 B=图像映射输入覆盖独立报告；B 的前后锚点覆盖仅是必要条件，不能替代 L2-B 漂移、误差、重启及物理时延验证。
