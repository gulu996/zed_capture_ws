**C5-F离线转换接口（设计与少量真实图像测试，非完整SLAM导出器）**

输入：camera/left、camera/right、frames.csv、sensors.bag、anchors.jsonl、anchor_poll_events.csv、video_timestamps.csv、原配置和通过验证的L2-B输出。仅完整双目对可进入转换；原始文件不改写。

复核当前 `/home/jetson/catkin_ws/src/FAST_LIVO2/config/mid360.yaml`：img_topic=/left_camera/image，lid_topic=/livox/lidar，imu_topic=/livox/imu。没有修改这些配置。真正导出时需明确指定所使用的FAST-LIVO2配置，右目可独立保留诊断话题，不能假设FAST-LIVO2使用双目算法。

offline_interface.decode_original() 已用3对C2真实图像测试：输出sensor_msgs/Image、bgr8、1280×720、step3840、2764800bytes，原始Header不变。此对象保留CLOCK_MONOTONIC时间，仅用于解码/格式诊断，不允许直接作为MID设备时钟下的融合输入。

未来L2-B适配器应复用已验证通用映射核心，不新增拟合算法。conversion_plan()接口要求validation_status=VALIDATED、target_clock=MID360_DEVICE_GPS、frames与anchors文件SHA256及model_report_sha256；每对需原pair_id/raw_ns/sequence匹配、status=VALID及整数mapped_mid_ns。拒绝无映射、失败映射、时间回退、重复、输入错配和不完整双目。当前没有真实C5-F映射输入，3对测试均生成L2B_MAPPING_UNVALIDATED_OR_REJECTED拒绝项，未伪造设备时间。

最终导出的Image Header.stamp必须是经过验证的映射值；原始Header、整数V4L2时刻及pair_id必须在不可变元数据中完整保留，两者不可混称“原Header时间没变”。Header.seq、frame_id、左右对应关系保持。MID CustomMsg/IMU原消息与原Header保持不变；目标bag记录时间与各Header的策略另行明确，不能把主机接收时间当曝光时间。GNSS保留其原始测量和时间来源，未验证前不改成MID时间。

当前没有输出正式派生bag，没有运行FAST-LIVO2建图。GNSS扩展设计：沿用传感器writer中的显式topic/type白名单或独立原始文件记录接口，独立接收队列和源时钟标签；不经JPEG编码/文件writer，也不因影像失败覆盖GNSS数据。当前配置没有新增GNSS订阅，实际话题与类型需设备接入时确认，不擅自修改后端或PPS。
