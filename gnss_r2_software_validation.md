# GNSS-R2 software validation

状态：**SOFTWARE_VALIDATED，下一次联合实机仍HARDWARE_PENDING**。本轮不把软件回放写成实机采集通过。

## 可复核证据

- 迁移清单：79/79文件SHA256/大小一致；原R1测试9/9通过。
- `/home/jetson/zed_capture_ws/diagnostics/gnss_r2/python_tests_validated.log`：8/8，包含真实15秒输入53472字节完整重建、546个分区、544个校验有效、78个UNIHEADINGA、截断AGRICA后RMC恢复、NO_FIX、历史Fixed/Float与FINE/NO_FIX、整数UTC、100ms回退/重复、旧MD5及未知字段、短写和/dev/full失败、有界缓存和旧配置关闭回归。
- `/home/jetson/zed_capture_ws/diagnostics/gnss_r2/receiver_failure_tests.log`：3/3，发布序列化失败保留原始字节且有逐话题错误、串口忙拒绝open、断开残留保存后重置日期状态。
- `/home/jetson/zed_capture_ws/diagnostics/gnss_r2/receiver_lifecycle_tests_final.log`：2/2，真实旧字节输入、SYNTHETIC串口/ROS/接收时钟服务；NO_FIX正常停止/flush及断开失败退出。没有打开tty。
- `/home/jetson/zed_capture_ws/diagnostics/gnss_r2/session_tests_final.log`：3/3，mock启动验证显式GNSS只新增一个读取进程、关闭无依赖、已有GNSS发布者拒绝；不启动第二Master/Livox/writer。
- `/home/jetson/zed_capture_ws/diagnostics/gnss_r2/old_c5f_regression.log`：原C5-F Python7/7，包括旧配置透传、原三对真实JPEG解码/配对/时间戳、原非图像bag和未映射拒绝接口。
- C++既有core/watchdog/IMU分段/V4L2/HID五个测试通过（`cpp_regression.json`）；JPEG shadow/files两个测试通过（`jpeg_regression.json`）。仅模拟syscall/failure及小图软件测试，不访问相机。
- `build.log`和`build_roundtrip_fix.log`：catkin_make -j2完成；未清理工作空间。`dynamic_dependencies.json`：节点、JPEG插件、writer测试的ldd -r均0，无缺失符号；capture进程libusb继续使用Ubuntu系统目录。

## 真正经过生产writer的离线测试

最终目录：`/home/jetson/zed_capture_ws/diagnostics/gnss_r2/offline_integration_20261018_171257_d0acc610`。

测试数据包含历史真实质量/UTC代表报文与完整真实室内原始流；范围和原文件SHA见provenance.json。测试拼接输入的接收时钟为**SYNTHETIC**，只用于软件接口验证，测量UTC和原报文字节来自真实输入。完整原15秒输入的原始SHA不变另有独立单测；本测试的子集不是一次真实连续采集。

原始拼接输入58863 bytes，SHA256 `716bb8315a263242e4524d01710876be482946bb344abbe05a24a761de572fe4`。源码R1及原始输入只读。1683条ROS消息通过生产共用recordingEnqueue/recordingDrain和GnssIngress中的实际rosbag::Bag::write闭包写入并读取。不是仅内存序列化，也不是由Python写出最终待验bag：Python仅生成输入fixture，最终sensors.bag由C++同一writer代码写出。完整Recorder硬件启动/ROS网络交互尚未实测。

| 话题 | received=enqueued=written=bag读取数 | 拒绝/错误 |
|---|---:|---:|
| /gnss/raw | 578 | 0 |
| /gnss/status_v2 | 578 | 0 |
| /gnss/pvt_local | 253 | 0 |
| /ublox_driver/receiver_pvt | 253 | 0 |
| /sensor_time/utc_observation | 21 | 0 |

五种datatype/MD5与旧生成消息一致。逐话题顺序、bag时间及序列化字节全部一致。错误MD5、空序列化消息、队列满/关闭、bag写入失败、退出排空及非GNSS FIFO均有显式断言测试。

最终sensors.bag为634933 bytes。raw分区、五类消息计数、UTC observation顺序、原始接收时间与无映射标志再次通过gnss_recording_check。保存21条有效测量UTC；测试子集中的UTC回退/重复保留，不能把子集统计当成原完整历史统计。原完整历史100ms异常的根因仍UNRESOLVED。

校验失败/无定位报文均保留，不把协议有效、定位有效、UTC有效或映射有效合并为一个标志。R1原始parse_reason/time_reason分布保留；NO_FIX缺少UTC字段可能产生旧字段解析失败计数，但不会丢原始数据或伪造PVT。

## 测试中发现并修正的测试问题

首次writer测试把相同bag时间的跨话题读取排序当成写入顺序，断言失败；改为逐话题有序、精确时间与字节比对。未改测量时间或降低数据完整性判定。两项JPEG测试初次遗漏必需输出目录参数；按实际CLI重跑通过。模拟接收器测试的sys.modules隔离导致重复导入numpy错误，修正测试加载顺序后通过。失败日志均保留，未删除历史记录。

## 性能和影响边界

新增一个Python GNSS子进程、五个轻量订阅和原writer里的GNSS任务；不加JPEG线程/第二writer，不占4096 JPEG事件槽。读取4096B、分帧8192B、ROS每话题128条、单入bag消息64KiB；原writer256MiB不扩容。新增真实CPU/RSS/磁盘吞吐与GNSS并发对JPEG/MID的影响：**PENDING_HARDWARE**。

离线生成文件可统计实际字节，但不是30秒联合实测吞吐，不能用其推算已通过30FPS。当前只能确认原JPEG代码/库未变、既有回归通过及writer测试通过，不能宣称真实JPEG/MID完全无影响。资源日志在下一次真实会话会包含GNSS子进程。

## 分项结论

| 项目 | 本轮结论 |
|---|---|
| GNSS_RAW_RECEPTION | SOFTWARE_TESTED：真实旧字节完整性；新实时接收PENDING_HARDWARE |
| GNSS_PROTOCOL_VALIDITY | SOFTWARE_TESTED：R1 CRC/恢复/分类保留，坏报文仍可追溯 |
| GNSS_POSITION_QUALITY | SOFTWARE_TESTED：真实NO_FIX/Single/Float/Fixed；不要求Fixed |
| GNSS_UTC_VALIDITY | SOFTWARE_TESTED：整数UTC与原顺序保留，缺失则无效 |
| GNSS_RECEIVE_CLOCK_VALIDITY | 真实旧接收时钟重放已检查；新串口/三时钟联合结果PENDING_HARDWARE |
| GNSS_MEASUREMENT_MAPPING | PENDING，未实现UTC→MID映射 |
| READY_FOR_C5F_INTEGRATION | 软件集成完成，可申请一次30秒实机验证 |
| 新联合CAPTURE_RUNTIME/DATA_INTEGRITY/CLOCK | PENDING_HARDWARE；原FAIL不变 |
| PHYSICAL_SYNC | PENDING |

本轮到此停止，不自动运行硬件测试，不延长到5分钟。
