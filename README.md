# Jetson ZED 2i / MID-360 原始数据采集

状态：**SOFTWARE_TESTED；HARDWARE_PENDING；SYNC_PENDING**。开发和编译已完成，尚无真实采集通过结论。当前 Codex 执行沙箱无法访问相机设备节点或创建 ROS TCP socket；以下命令需要在 Jetson 的普通 SSH 终端执行。软件不需要 CUDA、ZED SDK、显示器或系统安装。

采集节点使用独立的 `LD_LIBRARY_PATH`，优先加载 Ubuntu 系统 libusb；管理器、ROS Master 和 Livox 保留原环境。预检在启动 ROS/驱动前执行同一节点环境的 `ldd -r`，同时检查缺库、缺失符号和实际 libusb 路径。不会修改 `.bashrc` 或 MVS SDK。每次成功进入会话后保存 `capture_loader.json` 作为库加载审计。参见 [libusb 冲突修复报告](jetson_libusb_fix_report.md)。

第一次真实采集分析与局部修复见 [真实测试分析报告](zed_capture_real_test_analysis.md)。当前仍保持 HD1080/30：V4L2 请求 4 个缓冲，锚点按绝对 1 ms 节拍读取。相机启动前最多等待 10 秒，争取 Livox 数据和有效锚点连续稳定 1 秒；准备阶段的雷达、IMU、锚点及漏读计数仍保存，不重置来制造 PASS。相机启动后计时 30 秒，因此 bag 可包含更长的准备阶段。`check_result` 分别输出 `anchor_history_acceptance` 和 `image_mapping_acceptance`；后者是输入覆盖评估，不是已完成 L2-B。新 `video_timing.csv`、`anchor_poll_events.csv` 和时间 CSV 扩展列用于定位短时阻塞，原始时间戳不变。

约 12 秒提前退出的分析及软件修复见 [停流误判修复报告](zed_capture_stall_fix_report.md)，修复后实机重测待执行。停流保护先固定四路到达时间，再取单调时钟，避免并发更新造成无符号减法下溢；原有启动 5 秒宽限及超过 3 秒停流即停止的规则保持不变。`capture_metrics.jsonl` 和 `/zed2i/diagnostics` 新增 `input_watchdog`，含逐流最后到达时间、年龄、状态及触发输入列表；保护触发时另外保存独立的 `input_timeout.json` 并在 `capture.log` 记录同一快照。`zed_video` 指视频 DQBUF 完成，`zed_hid` 指正长度 HID 原始报告到达，`livox_lidar`、`livox_imu` 指 ROS 回调到达；这些是主机接收活性诊断，不是曝光时间或物理同步验证。HID 报告有效性仍在 `zed_imu_raw.csv` 单独检查。

## 30 秒采集

```bash
/home/jetson/zed_capture_ws/scripts/start_capture.sh --preflight
/home/jetson/zed_capture_ws/scripts/start_capture.sh --duration 30
```

配置：[capture.yaml](src/zed_capture/config/capture.yaml)。默认序列号 38003368，每目 1920×1080、30 Hz，输出 `/home/jetson/zed_capture_data/日期时间_随机ID/`（本机是 NVMe）。图像原始 YUYV，未压缩；仅图像约 249 MB/s，30 秒约 7.46 GB，120 秒约 29.86 GB，300 秒约 74.65 GB，另外预留雷达、索引和磁盘余量。

脚本复用已有 ROS master 和 `/livox/lidar`、`/livox/imu`；二者均不存在时，启动现有 `livox_ros_driver2/msg_MID360.launch`，显式关闭 rviz 和该 launch 的 rosbag 功能。保留现有驱动及配置。发现 FAST-LIVO 节点、重复 ZED 发布者、Livox 非 CustomMsg 或不完整的 Livox 发布组合时停止启动，不终止既有进程。只想复用现有 Livox 时加 `--livox-mode reuse`。不会启动 STM32、GNSS/UWB 或修改已有 PPS/GPRMC 链路。

首次预检如果显示设备权限问题，需要在主机终端确认 `/dev/video*` 和 `/dev/bus/usb/*/*` 的实际权限。沙箱不可见与主机权限不足是不同问题。`docs/99-zed2i-capture.rules.proposed` 仅供审查，**未经明确批准不要安装**。不要运行上游一揽子 udev 安装脚本。

## 停止、检查与连续测试

到期自动停止；也可以在启动终端按 **Ctrl+C**，或在另一个终端执行：

```bash
python3 /home/jetson/zed_capture_ws/scripts/stop_capture.py /完整/会话目录
```

停止后允许队列排空、bag 关闭和 fsync。不要拔电或强制杀死进程。脚本只停止它启动的子进程，不停止复用的 Livox/master。中途停止会因时长不足而未通过完整测试，这是预期结果。

```bash
/home/jetson/zed_capture_ws/scripts/check_recording.sh /完整/会话目录
source /home/jetson/zed_capture_ws/scripts/env.sh
python3 /home/jetson/zed_capture_ws/scripts/analyze_timestamps.py /完整/会话目录
python3 /home/jetson/zed_capture_ws/scripts/imu_time_check.py /完整/会话目录 --window 10 --max-lag 2
```

`check_recording` 完整读取并反序列化所有 bag 消息，检查左右目与原始视频元数据逐项对应、真实 V4L2 序号、图像尺寸和字节长度、时间连续性、CustomMsg 点数及序号、双 IMU 连续性、锚点 bag/sidecar 一致性、队列失败和资源记录。不会用合成数据声明硬件通过。`PASS` 指可观察的数据完整性；不等于物理同步、标定或底层雷达 UDP 包零丢失。

30 秒实测 PASS 且配置不变后，运行 120 秒；需要 5 分钟时将 120 改为 300：

```bash
/home/jetson/zed_capture_ws/scripts/start_capture.sh --duration 120 --validated-short-session /完整/已通过的30秒会话目录
```

1080P30 无法稳定保存时先检查 `capture.log`、`capture_summary.json`、`check_result.json` 和 `resources.jsonl`。程序不会自动降分辨率、跳帧或压缩。确认瓶颈后才能显式将配置中的 `resolution` 改为 `HD720`，重新做 30 秒测试。队列默认 256 MiB，满时停止并标记失败，不隐瞒丢失。ROS 图像预览订阅可能额外占用带宽和内存，基准测试不要启动图像显示。

## 数据解释及回放

每个会话包含 `session.json`、实际配置和软件哈希清单、实际设备设置、`data.bag`、`video_timestamps.csv`、`zed_imu_raw.csv`、`anchors.jsonl`、资源及结果文件。唯一会话目录与会话 ID 将 sidecar 和 bag 关联。未完成的录包保留为 `.active`，不会覆盖历史会话。

| 话题 | 内容 |
|---|---|
| `/zed2i/left/image_raw`, `/zed2i/right/image_raw` | `sensor_msgs/Image`，同一次双目缓冲区，原始 YUYV 字节，encoding=`8UC2`，原始方向 |
| `/livox/lidar` | 原 `livox_ros_driver2/CustomMsg`，消息及时间戳不改写 |
| `/livox/imu` | 原 MID-360 `sensor_msgs/Imu` |
| `/zed2i/imu/data_raw` | 原始轴向、未额外标定的 ZED 加速度和角速度；不提供姿态 |
| `/zed2i/video_stamp` | V4L2 sec/usec、sequence、flags、类型/来源、布局、DQBUF 前后主机单调时钟等 |
| `/zed2i/imu_stamp` | 原始 HID 字节、设备 tick、同步计数字段、HID 读取前后主机时钟 |
| `/zed2i/time_anchor` | IMA1 原始 64 字节、完整解析、观察时刻、跳过更新数、有效性 |
| `/zed2i/diagnostics` | 录制计数、队列、锚点时效、`SYNC_PENDING` |
| `/livox_lidar_publisher2/timestamp_diagnostics` | 原驱动已有诊断，若发布则保存 |

`8UC2` 特意不伪装成 RGB 或 UYVY：每两个像素是 `Y0 U Y1 V`。离线显示/算法转换可使用已有 OpenCV 的 `cv::COLOR_YUV2BGR_YUY2`，**原 bag 保留不变**。本阶段不发布虚构 CameraInfo、TF 或单位外参。图像 header 是 V4L2 原时钟，ZED IMU header 是设备 tick 换算时钟，Livox header 保持原值；它们尚不在同一时间域。bag 的记录时刻是主机 wall clock 的采集/ROS 接收时间，不能解释为曝光时刻。

在独立 ROS master 下回放（已有安全 master 可复用），第二个终端执行：

```bash
source /opt/ros/noetic/setup.bash
roscore
# 另一 SSH 终端；启动后按空格播放
/home/jetson/zed_capture_ws/scripts/replay.sh /完整/会话目录
```

相当于 `rosbag play --pause data.bag` 加显式话题重映射到 `/replay/...`；脚本不会修改 `/use_sim_time`。不要直接给运行中的 FAST-LIVO 喂入未映射、未标定的数据。当前已验证离线反序列化；真实 ROS 回放仍待主机验证。

## 时间与 L2-B 接口

见 [L2-B 输入约定](docs/L2B_INPUT_CONTRACT.md)。当前只保留原始证据、读取锚点及检测异常；没有从零实现统一映射、漂移模型或 SDK 时间补偿。随后优先复用笔记本 L2-B 的 SDK 无关部分。

IMU 工具按各自原始时钟重采样角速度模长，使用多个重叠窗口估计相关峰。输出约定：`Livox时间 ≈ ZED原始IMU时间 + offset`，并报告峰值、次峰差、运动强度、时间步长和跨窗口分散程度。静止、周期性歧义、缺样和搜索边界会标为 LOW/PENDING。此为 IMU 一致性估计，**不能证明图像曝光同步精度**，也不会修改 bag。

## 本地构建与测试

```bash
/home/jetson/zed_capture_ws/scripts/build.sh
source /home/jetson/zed_capture_ws/scripts/env.sh
/home/jetson/zed_capture_ws/devel/lib/zed_capture/capture_core_test
/home/jetson/zed_capture_ws/devel/lib/zed_capture/capture_input_watchdog_test
python3 /home/jetson/zed_capture_ws/scripts/test_offline.py
```

仅构建独立工作空间，`catkin_make -j2`；不清理原工作空间。依赖已有 ROS/libusb，加工作空间内静态 HIDAPI 和 Open Capture。合成测试数据仅写入 `evidence/synthetic_tests_*`，带 `synthetic_fixture=true`，不能通过连续采集启动门槛。源码来源、限制及保护验证见 [开发与测试报告](jetson_open_capture_development_report.md)。
