# GNSS-R2.1 离线验证报告

状态：SOFTWARE_VALIDATED。所有运行是离线测试；没有新硬件验证。证据：`/home/jetson/zed_capture_ws/diagnostics/gnss_r2/r21_20261018_180214`。

## 真实最新会话重放

输入原始serial_raw.bin：111834 bytes；SHA256：
`dbdf7922bac9a73e9d9f1ca1a153bc0e2ac2515a4242617f266d58a141483a51`。
重放使用原750个chunk的字节边界及原三种接收时钟，未生成替代接收时间。输入、重放bin及/gnss/raw全消息拼接相同；输出chunk记录与原chunk记录逐项一致。原session不写入，新增数据仅在独立软件测试目录。

| 指标 | 原实机记录 | R2.1离线重放 |
|---|---:|---:|
| 原始字节 | 111834 | 111834 |
| 分区记录 | 1141 | 1142 |
| RMC分类数 | 162 | 163 |
| 校验通过 | 1140 | 1141 |
| 校验失败 | 1（复合GGA） | 1（原损坏GGA前缀） |
| 旧字段解析失败计数 | 162 | 163 |
| 有效定位 | 0 | 0 |
| 有效测量UTC | 0 | 0 |

解析失败计数增加1是恢复RMC自身V/缺日期时间造成的原字段解析拒绝，不是回退。checksum失败与NO_FIX分别保留。其余所有父记录的原始字节、范围、chunk、接收时间、解析字段和UTC顺序逐项不变。缺失UTC没有被伪造。

## 回归测试

| 测试 | 通过数 | 覆盖 |
|---|---:|---|
| 新R2.1 | 8/8 | 真实范围/chunk/接收时间；合法父报文不拆；错误或缺失XOR；任意负载/多起始标记拒绝；结构错误；全部42个双chunk分界；8192项上界；旧AGRICA；NO_FIX/MD5 |
| 原R1 | 9/9 | AGRICA独立CRC、截断恢复、UNIHEADINGA、Fixed/Float、整数UTC、100ms回退及重复原序列 |
| 原R2 | 8/8 | 完整真实旧字节、质量/UTC、消息语义、有界残留、磁盘故障、GNSS关闭配置 |
| 接收失败 | 3/3 | 发布失败、独占/忙拒绝、断开残留 |
| 接收生命周期mock | 2/2 | NO_FIX正常退出和断开，未打开真实tty |
| 会话启动mock | 3/3 | 单读取器、GNSS关闭无依赖、已存在发布者拒绝 |
| 旧C5-F | 7/7 | 默认配置、参数透传、真实三对JPEG及元数据、无映射不伪造PASS |

合计40项通过，失败日志也保留。初次新测试对比了内存NaN和历史JSON null，产生断言失败；按既有clean序列化规则归一后通过，未改变生产解析/字段语义。该日志r21_tests.log与通过日志r21_tests_final.log均保留。
新增/修改Python通过compile检查，不产生保护目录pycache。生产C++没有修改，无需重编整个采集工作空间；独立writer测试夹具编译成功，ldd -r无缺失依赖/符号。

## 真正经过C5-F writer的离线bag验证

最新真实重放目录：`/home/jetson/zed_capture_ws/diagnostics/gnss_r2/r21_20261018_180214/latest_real_replay`。
最终测试bag：`/home/jetson/zed_capture_ws/diagnostics/gnss_r2/r21_20261018_180214/latest_real_replay/writer/sensors.bag`。
Python仅生成输入消息fixture，最终bag由C++现有RecordingQueue / GnssIngress / recordingDrain及rosbag::Bag::write路径写入，再逐话题读取检查时间、datatype/MD5及序列化字节。

| 话题 | received=enqueued=written=bag读回 |
|---|---:|
| /gnss/raw | 1142 |
| /gnss/status_v2 | 1142 |
| /gnss/pvt_local | 489 |
| /ublox_driver/receiver_pvt | 489 |
| /sensor_time/utc_observation | 0 |
| 总计 | 3262 |

全部原始字节、消息顺序/source_sequence及接收时间一致。恢复RMC source_sequence=22进入raw/status；损坏前缀仍有错误原因，未生成有效PVT。writer拒绝/序列化/写盘错误均0，排空完成。

既有测试夹具原先要求五类话题各至少1条，与真实NO_FIX无UTC输入不相符。本次在独立证据目录生成r21_writer_fixture.cpp，仅将该测试断言改为各话题写入数严格等于输入数，并将结果字段改为all_input_topic_counts_match；差异见writer_harness.diff。**没有修改生产writer、原测试源码或二进制，也没有伪造UTC。** 编译命令、依赖及运行日志均保存。

另运行未修改的原all-five writer回归，目录：`/home/jetson/zed_capture_ws/diagnostics/gnss_r2/offline_integration_20261018_180502_4ad8bc5b`。
该fixture复用真实历史有效UTC/质量记录和旧室内数据，接收时钟明确SYNTHETIC；不是新实测。实际写入/读回1683消息：raw578、status578、PVT253、兼容PVT253、UTC21。五类MD5与旧定义一致、精确序列化字节一致；UTC回退3与重复2保留（此为选取子集统计，不替代完整历史统计）。
两个writer测试都覆盖错误MD5、空序列化消息、满队列、已关闭队列、bag写入异常、退出排空和原非GNSS FIFO；未创建第二套生产录包系统，无ROS网络或串口访问。

## 保护与结果解释

protection_final.json：受保护71项SHA一致；原会话1851项文件大小/mtime一致；原GNSS原始文件SHA一致；catkin状态不变。原1080P/C2/C4.1/C5-F配置、JPEG编码器/队列/33.333ms时限、MID驱动、IMA1、三时钟、L2-B、NTP、STM32均未修改。
历史实测仍为902对JPEG、零视频长间隔/序号缺口、MID316/6342；原3260条ROS消息不会被本次重放3262条覆盖。JPEG两次超期和401个启动锚点漏读仍保留，原严格DATA_INTEGRITY FAIL不变。

| 结论 | 状态 |
|---|---|
| 真实GGA→RMC恢复 | SOFTWARE_VERIFIED |
| 原始字节保存及时间来源追溯 | PASS |
| 合法父报文/合成反例误拆 | 已测试样例中0；不宣称覆盖所有协议损坏 |
| 旧AGRICA、CRC、质量码、整数UTC回归 | PASS |
| 五类ROS消息兼容及实际writer读写 | PASS（分两种离线fixture覆盖） |
| GNSS关闭及旧C5-F软件回归 | PASS |
| 新补丁在真实采集时的CPU/时延 | PENDING_HARDWARE，本轮未测试 |
| GNSS_MEASUREMENT_MAPPING | PENDING |
| PHYSICAL_SYNC | PENDING |

本次已完成软件任务并停止；不自动进行新的联合采集。若后续授权实机验证，沿用既有GNSS显式配置即可，无须为本修复更改采集架构。
