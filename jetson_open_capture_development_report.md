# Jetson Open Capture 开发与测试报告

日期：2026-10-15；独立工作空间：`/home/jetson/zed_capture_ws`。

**最小采集软件链路已实现并编译，状态 SOFTWARE_TESTED；真实 30 秒及 2–5 分钟联合采集 HARDWARE_PENDING。** 当前工具的执行沙箱缺少 `/dev/video*`、USB 设备节点，创建 AF_INET TCP socket 返回 EPERM；启动在预检阶段阻止，未启动相机、雷达或建图。USB 枚举存在不能当作采集已通过。

## 交付与实际验证

| 项目 | 结果/状态 |
|---|---|
| Jetson / Ubuntu / L4T | Orin Nano，aarch64，Ubuntu 20.04.6，L4T 35.6.1 / JetPack 5.1.5 对应 BSP；VERIFIED |
| ROS | 既有 Noetic；原 catkin_ws 保留；VERIFIED（安装/文件） |
| CUDA / SDK | 原 CUDA Driver API 库存在，未发现完整 Runtime/Toolkit；本轮不需要且未安装 CUDA/ZED SDK；VERIFIED |
| USB3 | ZED 2i `2b03:f880`，sysfs speed 5000 Mbit/s；HID `2b03:f881`，序列号 38003368；VERIFIED（枚举） |
| 左右目 | 同一次 V4L2 DQBUF 拆分原始 YUYV，保留方向和全部像素字节；ARM64 构建及逐字节合成测试通过；SOFTWARE_TESTED，实机 HARDWARE_PENDING |
| MID-360 | 原 CustomMsg 与内置 IMU 的 ROS 原消息透明录制，不修改驱动及 header；SOFTWARE_TESTED（格式/离线 bag），实机 HARDWARE_PENDING |
| ZED IMU | 原 HID report、设备 tick、原轴向加速度/角速度、同步字段均保留；SOFTWARE_TESTED（编译/时间换算），实机 HARDWARE_PENDING |
| 锚点 | 只读 IMA1 v1 单槽文件，双次一致读取和偶数序号检查，所有观察到的新完整状态存入 bag 和 sidecar，记录漏读计数；SOFTWARE_TESTED |
| 统一时钟 | **SYNC_PENDING**；未从零实现完整映射，等待复用笔记本 L2-B 的通用模块 |
| 物理同步/标定 | **PENDING**；未验证图像曝光相位、未做相机内外参标定，不发布虚构外参 |
| CPU/GPU/内存/写速/FPS | 已实现真实采集时的统计，尚无实测值；HARDWARE_PENDING，不能用合成数据填充 |
| rosbag | 完整合成 bag 反序列化及错误检测通过；真实 bag 和在线回放 PENDING |
| FAST-LIVO2 回归 | 原文件、库、包、Git 状态无变化；未运行建图或重编原工作空间；运行回归 HARDWARE_PENDING |

操作入口：[README](README.md)，配置：[capture.yaml](src/zed_capture/config/capture.yaml)，时间适配：[L2-B 输入约定](docs/L2B_INPUT_CONTRACT.md)。

## 已实现的软件行为

- 在独立 catkin 工作空间构建 C++ 节点 `zed_capture_node`，`catkin_make -j2 -DCMAKE_BUILD_TYPE=Release`。仅依赖既有 ROS、libusb 和 C/C++ 运行库；HIDAPI/Open Capture 在本工作空间静态链接，没有 `/usr/local` 安装、ldconfig、全局环境修改或 ROS 原工作空间改动。
- 官方 Open Capture 的视频 latest-frame 接口改为每次 DQBUF 同步回调，在 QBUF 归还缓冲区前复制左右图像；记录真实 V4L2 sequence、原始 sec/usec、完整 flags、来源/类型、stride/格式/长度及主机时钟。双方共用一组采集标识和原始时间戳；无翻转、校正、立体匹配、深度、AI 或有损压缩。
- 图像 `sensor_msgs/Image` 使用 `8UC2` 原始 `Y0 U Y1 V` 布局，避免把 YUYV 误标成另一种颜色编码。仅去掉每行的对齐 padding，像素字节不变。后续算法需离线颜色转换、标定和时间域适配，当前不能直接接入 FAST-LIVO2。
- 同步双目图像和元数据作为一组进入 256 MiB 有界队列；队列满则停止并标记 INCOMPLETE/FAILED，不主动丢帧。录包使用 C++ rosbag API 和固定话题白名单，不调用 `rosbag record -a`，不压缩。无图像订阅者时不额外发送 ROS 图像副本。
- HID 每个成功读取的 report 在上游浮点换算、首样本处理和重基准前截获。设备原 tick 始终保留；精确尺度 39062.5 ns/tick，整数 header 向下取整。ZED IMU 不发布伪造姿态，也不调用上游 `enableSensorSync`。
- `timeshare_imu` 1 kHz 只读轮询；保留 writer_epoch、seqlock 序号、设备和主机时间、ready、source、uncertainty 及原始 64 字节。检测源文件更换、过期/未就绪/协议错误和可观察跳过更新。单槽协议无法追溯已覆盖的历史，因此不能保证零漏读；检测到漏读时检查脚本拒绝完整性 PASS。
- 自动管理自己启动的子进程和唯一会话目录；复用的 ROS/Livox 不被停止。到期或 Ctrl+C 后排空队列、关闭并 fsync 文件再完成 bag。每秒记录进程树 CPU/RSS、系统 CPU/内存、可读取的 GPU load、块写字节及 bag 增长；复用的既有 Livox 不计入自有进程树 CPU，但在全系统 CPU 中体现。
- 长采集需要相同配置的真实 30 秒会话完整性 PASS。不会依据合成测试解锁，不自动改为 720P，不增加 swap。

## 原始时间语义与笔记本代码复用

上游 `Frame.timestamp` 以首帧主机 wall time 重基准，不等于原始 V4L2 缓冲区时间；上游 frame_id 也是软件计数。本地分开保存两者。V4L2 的时钟类型和事件来源由驱动标志定义；即使是 MONOTONIC，也不能推断曝光中心或物理同步精度。参考：[Open Capture 官方源码](https://github.com/stereolabs/zed-open-capture)、[Linux V4L2 文档](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/buffer.html)。

现有锚点路径 `/home/jetson/timeshare_imu` 已实际核实，协议来自原仓库 `livox_ros_driver2/include/livox_ros_driver2/imu_time_anchor.h`。原 Livox 主机时间在 SDK IMU 回调采样，仍有网络和调度延迟；默认 uncertainty=10,000,000 ns 为配置值，未当作实测精度。

本轮没有编写另一套漂移模型、统一时钟拟合或补偿器。`analyze_timestamps.py` 只审计原始输入；`imu_time_check.py` 只做多窗口角速度模长互相关。后者支持不等采样率、远隔时间原点、相关峰歧义和低运动拒绝；不代表图像曝光同步。L2-B 到来后按输入约定复用 SDK 无关部分，原始 bag 保持不变。

## 依赖来源与系统变化

Open Capture 是官方公开源码快照，自报版本 **0.6.0**，来自 `stereolabs/zed-open-capture/master`；HIDAPI 来自官方 **hidapi-0.14.0**。当前 shell 无外网 DNS，源码通过浏览工具读取官方 raw 文件并保存；**没有取得可证明的 Open Capture Git commit，不伪称是某个已固定 commit**。已保存未修改快照 SHA256、实际本地源码 SHA256 和补丁；实际复现依据为这些本地文件及哈希。公开源码 MIT / BSD 许可原文保留。

HIDAPI `libusb/hidapi_libusb.h` 是有注释的本地最小构建适配头，仅包含标准类型和上游 portable API；不是冒充官方完整扩展头。本节点不调用该扩展 API。HIDAPI 实现和 portable 头来自官方。[HIDAPI 官方版本](https://github.com/libusb/hidapi/tree/hidapi-0.14.0)

本机已有 libusb 开发包，缺系统 hidapi 开发包。曾执行只读 APT 模拟：

```bash
apt-get -s --no-upgrade --no-remove --no-install-recommends install libhidapi-dev libhidapi-libusb0
```

模拟结果：新增 3（libhidapi-dev、libhidapi-hidraw0、libhidapi-libusb0），升级 0，卸载 0；Ubuntu focal arm64，版本 0.9.0+dfsg-1，包元数据下载合计 47,248 字节、安装合计 184 KiB；不涉及 NVIDIA/L4T、CUDA、ROS、Eigen/PCL/OpenCV/GTSAM、BLAS 或网络服务。**没有实际执行安装**，最终采用私有静态 HIDAPI，因此本轮实际新增/升级/卸载系统包均为 0。APT 输出的 autoremove 建议未执行。

未安装 udev。官方规则中包含范围更宽的权限及 STM32 DFU 匹配，未采用。仅保存了针对 ZED 2i 和 jetson 组的 [规则提案](docs/99-zed2i-capture.rules.proposed)，若普通 SSH 的主机权限确实不足，须单独审查并取得批准；它不能解决当前沙箱隐藏设备的问题。

## 软件测试证据

- `evidence/build_shutdown_fix.log`：最终 ARM64 C++ 构建成功（含立即停止时的线程启动竞态修正）；`capture_core_test`：原始双目字节拆分（含 stride padding）、锚点合法性和整数 tick 换算通过。
- `evidence/offline_tests_validated.json`：7 项合成测试通过，包括完整 bag、丢失右目拒绝、锚点 sidecar 不一致拒绝、原始时钟审计、不等采样率多窗口已知偏移估计、静止低置信度拒绝、重复时钟拒绝。合成 IMU 已知偏移测试在 10 个窗口支持，误差 2 ms；**这只是算法夹具结果，不是本机硬件同步精度**。
- `evidence/capture_ldd.txt`：可执行文件动态依赖均可解析，不依赖 CUDA/ZED SDK；私有静态库不会替换系统 HIDAPI。
- `evidence/short_capture_attempt.json`：30 秒真实采集命令在预检退出 2，原因是设备节点不可见及 TCP EPERM；没有生成真实数据会话，未声称采集了 300 帧或完成长测试。
- `evidence/protected_state_final.json`：4,495 条原文件记录、848 个文件 SHA256、276 个动态库哈希不变；原软件包清单和完整 Git status 不变，HEAD 仍为 `d62f4ca38b9dea19041919de090e5d4d7d36d1ea`；BLAS/LAPACK 仍为系统 reference 实现。中间 Git 比较曾使用默认折叠未跟踪目录的显示格式，最终按基线同样的 `--untracked-files=all` 复核一致。

## 六个最终问题

| 问题 | 当前诚实结论 |
|---|---|
| 双目图像完整吗？ | **HARDWARE_PENDING**。实现了同缓冲区拆分和逐帧一致性检查，未取得真实 bag。 |
| 雷达与 IMU 完整吗？ | **HARDWARE_PENDING**。已实现原消息录制和结构/连续性检查；CustomMsg 本身不能证明所有底层 UDP 包零丢失。 |
| 时间戳可追溯吗？ | **SOFTWARE_TESTED**：元数据、原始 HID 和锚点持久化及离线一致性检查已实现；实机记录仍 PENDING。 |
| 已建立统一时钟吗？ | **SYNC_PENDING**，没有宣称成功；等待复用笔记本 L2-B。 |
| 物理同步精度已验证吗？ | **PENDING**，未验证；IMU 相关不能替代曝光同步验证。 |
| 可离线用于 FAST-LIVO2 吗？ | 设计上保留了后续离线处理所需原始数据。**目前不能宣称可直接建图**：真实数据完整性、统一时间域、相机内参和雷达相机外参仍待完成。 |

## 限制、后续步骤与回退

下一步是在普通 SSH 终端执行 README 的 30 秒命令，检查真实 USB/权限、帧率、左右一致、双 IMU、锚点漏读和 NVMe 持续写入；通过后运行 120–300 秒。必要时分析瓶颈后显式评估 720P30，不自动牺牲数据。真实 ROS 回放需在安全 master 下完成，工具默认重映射为 `/replay/...`。

当前仅新建独立工作空间、源码、构建产物和证据；没有修改 `/etc`、原源码/编译目录、网络、驱动或持久 shell 环境，没有 Git commit。回退是停止本工具自己的进程并结束该局部 shell，不再启动独立节点；无需卸载或降级系统包。保留工作空间和数据供审查，不删除历史文件。原环境初次审计报告仍保留在 `/home/jetson/jetson_zed_environment_audit.md`，其 CUDA/SDK 安装路线已被本次无 SDK 采集方案取代。
