**C4 原生720P30 / Q95 4:2:0 实时影子编码——软件准备报告**

2026-10-17。软件准备、增量编译、离线测试完成；本轮未启动真实采集。状态 **SOFTWARE_TESTED / HARDWARE_PENDING**。C3 的900/900对离线结果只作为选型依据，不能证明C4并发通过。

**FAST-LIVO2 只读核对**

`/home/jetson/catkin_ws/src/FAST_LIVO2/launch/mapping_mid360.launch` 加载 `config/mid360.yaml`，其中点云为 `/livox/lidar`、IMU为 `/livox/imu`、图像为 `/left_camera/image`，未使用 `/zed2i/imu/data_raw`。HH配置也使用Livox IMU。没有启动ROS Master或FAST-LIVO2检查在线参数，因此结论针对已部署源码/配置，不冒充当前在线节点接线。

ZED IMU启动旧报告不是C4前置修复任务；继续保留其原始报告、分段及严格DATA_INTEGRITY错误。现有图像话题仍非ZED话题，故 `SLAM_REQUIRED_DATA_STATUS=PENDING_OFFLINE_INTEGRATION`，不能仅凭原始传感器连续就声称已具备建图条件。720P内参、外参、L2-B和物理同步没有在本轮解决。

**所有权及线程审计**

现有Open Capture在回调结束后才QBUF；回调里的splitYuyv已将左右目分别复制到独立sensor_msgs/Image::data。原始writer持有boost共享指针，执行bag.write及publish，不修改像素或Header。新增影子分支位于原始任务入队之后，仅传递ImageConstPtr、VideoStampConstPtr和复制完成的MONOTONIC时刻；不捕获f.data或MMAP指针，不额外复制整幅YUYV。

新增一个JPEG工作线程，队列容量固定4对，另有最多1对处理中，故影子持有的原始像素额外生命周期上界约18.432MB（通常与原writer共享，非新复制）；另有BGR/JPEG工作内存和有界轻量事件记录。队列采用固定数组。采集回调仅try_lock并尝试入队，不等待JPEG完成或队列空间；满队列、锁忙、停止中、原始任务拒收/无效像素均明确拒收影子任务。原始录包任务不被取消。

生命周期：摄像头reset先join采集线程，再STREAMOFF/解除MMAP；原始writer排空后，影子线程排空并join，释放所有共享缓冲，最后卸载插件。退出不detach编码线程、不引用失效缓冲、不强杀任务。正常排空最多4个待编码任务；native编码器自身若异常卡死，仍需外部诊断，不能保证任意底层故障下有限退出时间。

4096条事件预分配足以容纳当前30秒及启停余量；达到上限后记录unlogged_inputs且验收FAIL，不阻塞原始链路。每个完成/编码失败任务由工作线程写轻量CSV；回调拒收事件先存在有界内存，退出排空时落盘。未在回调执行文件写入、fsync或JPEG编码。若进程异常终止，未落盘/未排空证据必须判失败，不能宣称全部完成。

**编码及生产路径差异**

复用C3同一系统libturbojpeg 2.0.3 API及参数，在C++薄封装中执行OpenCV4.2 COLOR_YUV2BGR_YUY2 → BGR → tjCompress2(TJPF_BGR,TJSAMP_420,Q95,TJFLAG_ACCURATEDCT)。没有另行实现JPEG算法。每张实际JPEG用tjDecompressHeader3解析SOF，核对1280×720与TJSAMP_420；随后释放JPEG字节，本轮写入JPEG图像数为0，原始YUYV rosbag链路保持不变。

OpenCV固定1线程且关闭OpenCL；仅C4采集子进程设置OPENBLAS_NUM_THREADS=1、OMP_NUM_THREADS=1，父进程、ROS Master、Livox及全局环境不变。系统库由现有进程隔离LD_LIBRARY_PATH加载，未安装/升级依赖。

使用可选共享插件libcapture_jpeg_shadow.so，主节点仅新增dlopen接口。`readelf -d`确认主节点没有OpenCV/TurboJPEG DT_NEEDED；默认关闭时不加载这些编码库、不创建JPEG线程、不读取额外色彩元数据。默认1080P和C2启动命令显式传 `_jpeg_shadow_enable:=false`，避免之前C4在ROS参数服务器留下true而误开启；没有更改两个原配置文件。

C4独立配置：
`/home/jetson/zed_capture_ws/src/zed_capture/config/capture_hd720_c4.yaml`
与C2内容唯一参数差异为 `jpeg_shadow_enable: true`。Q95、420及队列4在此次实验中固定；开启时只允许HD720/30、时长≤30秒，不静默回退。

**元数据与色彩**

jpeg_shadow_events.csv逐输入保存pair_id、原sequence、整数raw_ns、左右Header sec/nsec/frame_id、V4L2 flags/时间域/来源、复制/入队/开始/完成时刻、转换和纯编码耗时、每眼JPEG大小、SOF420及状态原因。编码时刻仅作性能诊断。分析脚本逐项连接原video_timestamps.csv，并利用原完整bag检查结果检查双目一致性，不以JPEG完成时间代替采集时间。

C4在相机初始化后，使用实际camera->getDeviceName()打开独立O_RDONLY描述符，仅执行VIDIOC_G_FMT/G_PARM，不STREAMON、不分配缓冲、不更改控件。保存实际width/height/stride/fourcc、colorspace/ycbcr_enc/quantization/xfer_func及帧率分数到jpeg_shadow_color.json。接口失败则UNKNOWN并保留errno；0(DEFAULT)仅按驱动报告记录，不伪称已确认色度。当前沙箱未获得实机字段，故实际色彩元数据仍PENDING_HARDWARE。

转换继续使用C3已声明的BT.601 limited软件参考，不根据猜测改规则。实机字段若与参考不符，应在后续颜色审查中明确指出；本轮性能通过不能等同真实色彩准确。

**修改文件与备份**

现有文件仅修改：

- `src/zed_capture/src/capture_node.cpp`：默认关闭的分流、插件生命周期及只读G_FMT/G_PARM。
- `src/zed_capture/CMakeLists.txt`：可选插件与独立测试目标；现有capture_oc/HID实现不改。
- `scripts/session.py`：开启参数传递、插件预检、子进程线程环境、实际命令及软件哈希记录。

新增：jpeg_shadow.hpp、jpeg_shadow_worker.hpp、jpeg_shadow.cpp、jpeg_shadow_test.cpp、scripts/jpeg_shadow_config.py、独立C4 YAML，以及 `diagnostics/zed_jpeg_shadow/` 内的一键运行器、验收器和软件测试。增量构建更新zed_capture_node并新增插件及测试可执行文件。

修改前源码、启动器、CMake和节点二进制备份位于：
`/home/jetson/zed_capture_ws/diagnostics/zed_jpeg_shadow/before/`
变更diff、前后SHA256、编译及测试日志都保存在该诊断目录。此工作空间不是Git仓库，使用文件哈希和备份审计；原FAST-LIVO2 Git HEAD/status保持不变，未commit/push。

**软件验证结果**

| 验证 | 结果 |
| --- | --- |
| catkin_make -j2 Release增量编译 | PASS |
| 影子C++测试 | PASS：空队列退出、排空、容量4/第6输入拒收、共享缓冲存活与释放、编码异常、原始拒收、实际编码420、像素/Header不变、双目错配拒绝 |
| 既有5个C++测试程序 | PASS：core、input_watchdog、IMU分段、V4L2 IO、HID IO |
| C4配置/mock启动回归6项 | PASS：默认关闭/C2清除遗留true、C4参数至真实Popen边界、空格路径、独立配置及错误拒绝 |
| 原joint配置回归6项 | PASS |
| 原动态库隔离回归5项 | PASS，包括MVS覆盖检测 |
| C4验收器合成回归3项 | PASS：原始完整性FAIL与JPEG区分、33.333ms不放宽、拒收使影子失败 |
| 节点及插件ldd -r | SOFTWARE_TESTED，无缺失符号；系统libusb/OpenCV/TurboJPEG |
| Python语法检查 | PASS |

首次构建的测试文件缺boost/weak_ptr头已补齐；首次新增mock用例缺dynamic_dependencies字段已修正。失败和后续通过日志均保留，不隐瞒。这些是软件准备阶段问题，未进行硬件测试或将其计为硬件失败。

**保护检查**

修改前19个受保护快照中，变化仅上述3个既有源码文件和重编译节点；其余15个（含C2/1080P YAML、Open Capture/HID静态库、vendor实现、IMU分段和时钟脚本等）哈希不变。C2历史25个sidecar与C3保存哈希一致，原bag大小仍3,460,013,078 bytes；未以写模式打开bag。未清理工作空间、修改FAST-LIVO2/Livox/STM32/GNSS/UWB/NTP/CUDA/JetPack/USB权限或系统网络。

**实机预检边界**

只执行一次无采集预检。sysfs显示视频2b03:f880为5000Mb/s，HID2b03:f881为12Mb/s；二者不能混为视频USB2。剩余磁盘147.147GB，满足本次预计原始图像3.31776GB×1.15和10GB安全余量。节点及插件符号检查通过。

当前运行环境无法访问/dev/video*及HID USB节点，ROS AF_INET socket返回EPERM。这是执行环境访问限制，不是相机/雷达故障证明。未反复尝试、未申请绕过、未修改权限；未探测或反复启动断电雷达。根据用户要求，软件准备完成后停止，由普通SSH终端执行一次实机测试。

**唯一实机命令**

确认ZED连接、MID-360与STM32供电、其他采集已自然退出后，在普通jetson SSH终端执行：

```bash
/home/jetson/zed_capture_ws/diagnostics/zed_jpeg_shadow/run_c4.sh
```

该命令只调用一次现有run_joint_test.sh并显式传入capture_hd720_c4.yaml。保留原15秒前监测、30秒录制、录制完成后15秒监测及严格bag检查。不自动重试。Ctrl-C经运行器转发到原联合管理器，沿既有正常退出流程处理，不强杀其他进程。

原始会话仍写 `/home/jetson/zed_capture_data/` 唯一目录；三时钟仍写 `/home/jetson/clock_diag/runs/joint_*/`；C4运行器另建 `diagnostics/zed_jpeg_shadow/runs/c4_*/`，保存terminal.log、thermal.jsonl、c4_result.json及验证报告。终端打印C4_DIR、TEST_DIR、SESSION和C4_RESULT，保持关联。

自动分析逐项报告CAPTURE_RUNTIME、VIDEO_CONTINUITY、JPEG_SHADOW_COMPLETION、JPEG_SHADOW_QUEUE、JPEG_SHADOW_LATENCY、MID360_CONTINUITY、CLOCK_DIAGNOSTIC、DATA_INTEGRITY、L2B_MAPPING、PHYSICAL_SYNC。JPEG完成要求所有原始视频对均有唯一对应事件且全部完成/SOF验证；队列拒收或丢失事件使其FAIL。延迟采用原始图像复制完成→JPEG完成≤33.333333ms的逐对严格门限，包含原始入队及影子等待，不能解释为曝光延迟；转换、纯编码和worker处理耗时另报分位数。

保存视频异常前后原始writer/V4L2/JPEG事件，按pair_id及MONOTONIC关联；1Hz CPU/温度采样不保证捕获瞬态抢占。MID360_CONTINUITY仅评价可见ROS消息，不能证明底层网络包完全或物理同步；GPS/type=2和时钟切换另列。原DATA_INTEGRITY保持原检查结果，不因JPEG成功而升级。

CPU/RSS/磁盘统计复用原会话资源检查，与C2同口径比较；复用的外部Livox进程不一定计入owned-child CPU。温度、频率/冷却状态由独立运行器1Hz只读记录，不改变三时钟算法。不同时间实验的相关性不能直接证明JPEG是任何新间隔的唯一原因。

**目前能回答与尚待回答**

| 问题 | 当前状态 |
| --- | --- |
| 完整联合采集与JPEG能否并发且保持30FPS | PENDING_HARDWARE |
| C4实际Q95编码P50/P95/P99 | PENDING_HARDWARE，不能引用C3冒充 |
| 是否产生新66.9ms视频间隔 | PENDING_HARDWARE |
| 队列积压/拒收、CPU/RSS增量 | PENDING_HARDWARE |
| MID360与原bag是否受影响 | PENDING_HARDWARE |
| 是否进入真正JPEG压缩录包 | 尚不能批准，需要C4真实结果及色彩元数据复核 |
| L2B / 物理同步 / SLAM精度 | PENDING |

实机完成后，运行器生成本次独立目录中的 `zed_720p_jpeg_c4_validation.md`；顶层同名报告不存在时另存一份，绝不覆盖已有报告。当前不生成伪实机验证报告。

回退：正常继续使用原C2或默认入口即可，启动器显式关闭影子功能。若需要精确恢复旧二进制/源码，可在确认无采集进程后按before备份与SHA256恢复上述修改文件；本轮不自动执行恢复或删除任何新旧证据。全部准备完成，等待用户执行一次C4。
