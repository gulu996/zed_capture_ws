**C5-F软件准备与预检 — 2026-10-18**

结论：SOFTWARE_TESTED。已实现显式独立的720P30、Q95/420双目JPEG文件直存及sensors.bag模式，并完成编译、故障注入、旧模式回归和3对真实C2图像测试。C5-F实时联合采集为PENDING_HARDWARE，本轮没有启动相机/雷达、没有重复采集。C5-E CompressedImage bag路线未实施。

**独立模式与实际数据路径**

配置：`/home/jetson/zed_capture_ws/src/zed_capture/config/capture_hd720_c5f.yaml`，显式storage_mode=jpeg_files、jpeg_shadow_enable=false、原生HD720/30、YUYV、Q95/420。原capture.yaml、C2、C4及C4.1 OFF/ON配置内容均未修改；所有旧配置通过启动器显式传_storage_mode:=raw_bag，避免继承上次ROS私有参数。

调用链：`diagnostics/zed_jpeg_c5f/run_c5f.sh` → run_c5f.py → 原run_joint_test.sh --config C5F → session.py → zed_capture_node。只有C5F走新文件插件工厂；其他配置继续原raw_bag/影子路径。节点启动打印ACTUAL_STORAGE_MODE与bag名，session.json保存实际配置、源路径/哈希、存储模式及bag名，c5f_software.json保存本次相关源码/可执行文件哈希。

```text
V4L2 DQBUF → 一次安全左右目拆分复制 → 立即返回以供QBUF
                      ├→ VideoStamp/原始时间与底层诊断 → sensors.bag及sidecar
                      └→ 编码队列（最多4对等待）→ 单JPEG工作线程
                             → 写盘队列（最多4对等待且总字节受限）→ 单文件工作线程
MID点云、MID IMU、ZED IMU、原始锚点与诊断 → 原传感器bag writer → sensors.bag
```

复用原Codec及Q95/420参数、YUYV→BGR转换、实际JPEG SOF检查、录制前同编码线程3对SYNTHETIC预热。没有新增JPEG编码算法。JPEG编码和文件写入均不在V4L2回调中执行；原驱动4个MMAP及采集线程逻辑不变。

C5F不向bag写入Image/CompressedImage，也不发布左右原始图像。为避免无依据重构，仍复用sensor_msgs/Image作为已有不可变像素及Header容器；这不是ROS原始图像任务：不序列化、不发布，传感器writer闭包也不持有像素。左右目安全复制一次后只由JPEG队列共享持有，编码结束释放。当前没有尝试零拷贝或让JPEG持有已QBUF的MMAP指针；不能宣称已达到最小可能复制/内存开销。

编码队列4对，文件队列4对；各另有最多1个正在处理的任务。写盘总在途字节上限32MiB（包括写入中的任务），原非图像writer仍沿用256MiB上限。原始像素约3.6864MB/对，存在转换/编码临时内存及固定4096事件槽；当前实验限制≤30秒，不支持将固定槽当无限历史。主线程每10ms检查文件管线失败，失败会请求正常停止和排空，禁止静默减去失败输入数。未更改实时优先级、CPU绑定或系统调度。

**文件、索引与失败记录**

每1000对一个分目录，例如pair1：

```text
SESSION/camera/left/000000/000000000001.jpg
SESSION/camera/right/000000/000000000001.jpg
SESSION/frames.csv
SESSION/sensors.bag
SESSION/video_timestamps.csv
SESSION/anchors.jsonl
SESSION/anchor_poll_events.csv
SESSION/zed_imu_raw.csv
SESSION/zed_imu_time_validity.csv
SESSION/video_io_events.csv
SESSION/hid_io_events.csv
SESSION/jpeg_files_summary.json
SESSION/jpeg_file_sync.csv
```

frames.csv包含pair_id、相对文件路径、原始整数raw_ns和V4L2 sec/usec、时钟域、sequence、flags/type/source、左右Header.seq/sec/nsec/frame_id、1280×720、Q95/420、编码及写盘状态、成功位、字节数、排队/转换/编码/写盘时刻及失败原因。时钟域仅在V4L2标志支持时写CLOCK_MONOTONIC，否则UNKNOWN并使检查失败。编码完成时间仅作性能统计，绝不改Header/raw_ns。

相机原始间隔/驱动编号缺口、编码失败、编码队列拒收、写盘队列拒收、输入异常和文件写入失败分别统计。左右按同pair_id命名；仅两张文件都完整write并成功close后才记录WRITTEN。任一目失败保留现存完整/部分文件和失败索引，不把该pair当完整。创建目录拒绝已存在目标，JPEG使用O_EXCL、不覆盖历史；短write循环补写，EINTR重试，0字节write/磁盘错误明确失败。

不逐张立即fsync。jpeg_sync_ms默认1000（允许配置100～5000）；由文件writer按时间或累计120个待同步文件触发批次同步，正常结束完成最终文件、索引、目录及总结同步。jpeg_file_sync.csv保留批次时间、文件数和last_complete_pair_id；验收还要求final_synced=true。WRITTEN仅表示两目已close，不能单独当作耐掉电保证。**突然断电时最近未同步的数据和索引可能丢失；1秒是触发目标，不是磁盘阻塞情况下的最大丢失窗口保证。** SIGKILL/掉电导致缺少最终证据必须FAIL/待恢复，不能伪造完整关闭。慢fsync可能积压写盘队列，必须在实机记录max_sync_ns及队列拒收，不靠增大无界缓存消除。

**分开的验收**

原DATA_INTEGRITY检查规则没有放宽。文件模式新增逐文件SOF/解码、完整路径集、整数Header及原始VideoStamp匹配、最终同步检查；实际bag消息counts仍只统计bag，JPEG图像数量/连续性另由文件索引统计，报告明确其来源。文件损坏、缺一目、不完整索引/多余文件、编码/写盘失败均严格失败。

SLAM_REQUIRED_DATA_STATUS独立评价当前MID点云+MID IMU+图像证据。独立配置的初始应用策略为：30秒最多3次相机长间隔、按时间周期估计的缺失比例≤1%、单次最大间隔≤100ms。此为显式可配置的实验策略，不改变严格DATA_INTEGRITY；驱动sequence缺号与物理曝光缺失不等价，周期估计也不是物理丢帧实测。编码/队列/写盘失败不属于可接受相机缺口。

MID连续性/结构/rate、GPS type2与无源切换、图像时间合法性、配对、持久化等失败直接FAIL。即使这些通过，未提供已验证L2-B和物理同步时，SLAM_REQUIRED_DATA_STATUS只能为PENDING_L2B_AND_PHYSICAL_SYNC，其子字段required_sensor_recording可描述记录层PASS_WITH_RECORDED_GAPS，不能宣称整体SLAM可用。ZED IMU继续原始保存及分段检查，不作为JPEG研发的前置修复；其失败仍影响原严格DATA_INTEGRITY。

**少量真实数据与软件测试**

真实测试数据集：`/home/jetson/zed_capture_ws/diagnostics/zed_jpeg_c5f/real3_1792302704853895840`。输入只读来自C2会话20261017_162911_883e3a79，取原始3对720P YUYV，及以首个视频记录为起点的0.5秒非图像bag片段；没有复制整个bag、没有新硬件采集、没有写回原始数据。

- 3/3对JPEG完整写出，6张全部420、1280×720、可解码；左右Header、原始整数时间及sequence与源视频CSV一致，顺序正确。
- 3对原始像素11,059,200bytes，JPEG638,071bytes：小样本图像载荷压缩比17.332:1，减少94.230%。这是软件样本结果，不是30秒整会话节省率或持续实时吞吐。
- sensors.bag片段2,164,432bytes，包含5帧MID CustomMsg、100条MID IMU、原ZED IMU/元数据/时间分类、100个时间锚点及诊断；没有sensor_msgs/Image或CompressedImage。这个片段覆盖0.5秒而JPEG仅3对，不能用合计大小推算一场30秒真实容量。
- JPEG成功/最终同步通过，编码队列及写盘队列峰值均1；这不是新30FPS硬件并发验收。
- 解码为Image bgr8，step3840、data长度2764800，原Header保持；能够序列化为ROS1消息。不将其原始MONOTONIC时刻当MID设备时间。

编译catkin_make -j2 Release成功，不清理目录。8项C++程序的最新结果通过（新文件故障测试、旧shadow、真实3对回放、core、watchdog、IMU分段、V4L2、HID）。新文件故障测试覆盖短写入、0写入、ENOSPC单目失败保留、编码异常、两种队列满、所有权、排空/join、预热失败、不覆盖、1000/1001分目录边界。

7项C5F Python测试通过：默认模式、显式参数和错误配置、实际mock启动边界/含空格路径、真实JPEG/ROS Header、截断文件/时间篡改拒绝、独立应用验收和采集分流。另有严格checker文件模式SYNTHETIC集成测试通过、旧离线bag检查/IMU软件测试通过、6项旧JPEG配置+6项joint配置+5项动态加载环境测试通过。主节点和插件ldd -r通过，仍使用隔离后的系统libusb/OpenCV/turbojpeg。

最初回放测试工具错误地按bag起点选窗口，且假设同记录时刻不同topic遍历有序，造成样本不足；已修正为按视频起点和原sequence/pair元数据关联。失败日志保留，最终真实回放returncode=0，见real_replay_result.json；不是通过丢帧或改时间戳修复。最终结果索引为software_validation.json。

**离线兼容与GNSS扩展**

接口说明：`diagnostics/zed_jpeg_c5f/offline_conversion_contract.md`；少量可执行接口：offline_interface.py。只读核对当前FAST_LIVO2/config/mid360.yaml，图像=/left_camera/image，雷达=/livox/lidar，IMU=/livox/imu。没有改原配置或运行SLAM。

conversion_plan要求未来通过验证的L2-B输出、输入文件哈希绑定、pair/raw_ns/sequence匹配及单调的整数MID时间。没有有效映射的3对测试全部输出拒绝清单，未写正式派生bag。未来导出时将映射值用于目标Image Header.stamp，原Header必须另存不可变元数据；不能同时宣称统一时间轴和Header.stamp逐位未变。最终全bag转换、映射有效性及SLAM精度仍PENDING。

GNSS不经JPEG队列；未来可在现有非图像ShapeShifter/显式topic-type白名单或独立原始文件接口接入，保留源时钟与原测量。当前未新增GNSS订阅、修改解算后端或STM32 PPS；实际话题类型及接入验证待后续确认。

**实际修改与保护**

修改前源码及二进制备份：`diagnostics/zed_jpeg_c5f/before/`，哈希清单before_sha256.json。既有文件修改：

- src/zed_capture/src/capture_node.cpp：显式模式分支、只传元数据到传感器writer、文件插件失败停止、bag文件名路由；原相机/HID采集核心未重构。
- src/zed_capture/src/jpeg_shadow.cpp：在同一Codec后可选取回JPEG字节，新增文件模式工厂；旧影子输出不改变。
- src/zed_capture/include/zed_capture/jpeg_shadow.hpp：可选failed()接口，旧shadow默认false。
- src/zed_capture/CMakeLists.txt：新文件故障测试与小型真实回放目标。
- scripts/session.py：新配置验证/传参、sensors.bag路由、软件哈希；C5F检查子进程局部使用既有库隔离环境，未改全局环境。
- scripts/check_recording.py：C5F文件输入检查，旧raw路径与严格门限保留。
- /home/jetson/clock_diag/joint_test.py：仅读取bag的路径路由到sensors.bag；采样、拟合、时钟质量算法、门限、15秒前后监测全部不改。
- 构建产物zed_capture_node和libcapture_jpeg_shadow.so更新。

新增jpeg_files.hpp、storage_mode.py、jpeg_file_check.py、C5F配置、测试、diagnostics/zed_jpeg_c5f工具及报告。保护检查确认旧5份配置、vendor视频/HID静态库、clock_monitor及analyze.py保持原哈希；C4.1历史输入小文件哈希及bag大小/mtime未变。未修改catkin_ws、FAST-LIVO2、Livox、STM32、L2-B、NTP或系统依赖，无commit/push。

回退时无需清理数据；默认/C2配置仍选择原始模式。若需完全回退二进制/源码，应在本次采集自然结束后按diff恢复本轮修改文件并增量编译，节点及插件接口必须配套，不能只换其中一个。备份不覆盖用户后续修改，不执行git reset/clean，不删除历史或失败测试记录。

**一次实机命令与待验证结果**

确保ZED、MID-360及STM32正常连接/供电，并在普通jetson SSH终端执行：

```bash
/home/jetson/zed_capture_ws/diagnostics/zed_jpeg_c5f/run_c5f.sh
```

仅一次30秒，继承原设备/USB3/ROS/动态依赖/空间严格预检及15秒前后时钟监测，不自动重试。保守空间预估暂按原始720P负载加10GB余量，避免用尚未实测的压缩率降低安全预留；本次只读df显示约128GiB可用，不等于已做设备实机预检。

终端打印C5F_DIR、TEST_DIR、SESSION。原始新会话位于zed_capture_data唯一目录；C5F结果在diagnostics/zed_jpeg_c5f/runs唯一目录，包含thermal.jsonl、terminal.log、c5f_result.json及验证报告，时钟结果仍在clock_diag/runs。正常停止可等待自动结束；Ctrl-C只转发给本次管理器以有序退出，不杀已有其他进程。严格DATA_INTEGRITY仍可能返回2，必须查看分项结果，不能因此把运行成功误判为中途退出，也不能忽略真正的文件管线失败。

实机后自动检查全部JPEG、sensors.bag、配对/时间、MID及锚点/原诊断，报告编码/写盘耗时P50/P95/P99、两队列峰值、同步耗时、CPU/RSS/温度、块写入吞吐及总会话大小。实际总大小与C2/C4.1不同场景/帧数对比仅为观察，不能证明唯一因果。

JPEG直存的小规模软件验证成功；实际30秒空间、CPU、RSS、持续吞吐和采集线程影响仍PENDING_HARDWARE。相对CompressedImage bag存在更多文件open/write/close、目录项和同步操作；本轮未做同场景两种容器对照，不能定量声称文件模式CPU或文件系统开销更低。C5F的潜在主要收益来自停止原始YUYV序列化和大流量写盘，是否真正更省资源由下一次实测判断。

偶发相机缺口允许按独立应用策略记录评价，但根因未定位，不能宣称消失。编码/写盘错误仍失败。完成30秒复核之前不启动5分钟或更长录制。L2B_MAPPING_PENDING、SLAM_ACCURACY_PENDING、PHYSICAL_SYNC_PENDING保持。
