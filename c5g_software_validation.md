# C5-G 软件验证

结论：SOFTWARE_TESTED。没有新的实机采集。5分钟稳定性HARDWARE_PENDING；20分钟PENDING且入口拒绝。所有合成或重复输入测试只证明相应软件性质。

证据：`/home/jetson/zed_capture_ws/diagnostics/zed_c5g/preparation_20261018_181957`；构建日志在`/home/jetson/zed_capture_ws/diagnostics/zed_c5g/build_delivery.log`。

## 编译和依赖

- `catkin_make -j2`通过，没有清理build/devel。
- 最终node及JPEG插件`ldd -r`均返回0；仍使用系统libusb。
- 新增`create_jpeg_files_incremental`导出符号可见。
- 所有修改Python文件语法检查通过。

## Python回归（67项）

| 套件 | 通过数 |
|---|---:|
| 新C5-G策略、300秒mock启动GNSS开/关、真实GNSS重复输入、同步失败、时长验收 | 6 |
| GNSS-R2.1 | 8 |
| GNSS-R2 | 8 |
| GNSS接收失败 | 3 |
| GNSS生命周期 | 2 |
| GNSS session | 3 |
| 原C5-F | 7 |
| joint配置透传 | 6 |
| 原GNSS-R1 | 9 |
| 三时钟原算法离线回归 | 15 |

日志包括`c5g_delivery.log`、`c5f_delivery.log`、`python_first.json`、`final_tests.json`。这些测试未打开真实串口或启动硬件录制。旧配置门禁、默认模式及GNSS关闭回归通过，不代表所有旧模式重新实机测试。

## C++事件和故障验证

- 9001对**合成极小JPEG/元数据**通过新增量路径，超出4096旧限制；9001行索引、最终同步、整数时间戳大于2^53及每1000对分目录边界通过。
- 该轻量测试RSS：第1000对2,449,408 bytes，第2000至9000对均3,194,880 bytes，显示事件历史不再线性增长。它不是1280×720真实JPEG压力的RSS预测。
- 32槽耗尽压力明确失败，未记录事件unlogged=47；总输入79，完成5、编码队列拒收19、写入队列拒收8，其余47明确计数，未静默PASS。
- 增量故障测试覆盖短写、零写、磁盘写失败、左右目一侧失败、队列满、退出排空、预热失败、拒绝覆盖及分目录；旧文件模式及影子模式测试通过。
- long_guards验证磁盘余量边界、8GB预算、300秒接受、1200秒拒绝、已有progress拒绝覆盖。
- 子进程`_exit(99)`模拟异常停止：已有JPEG/index保留，无最终summary，检查工具不认定完整会话。该测试不是断电/fs故障实测。

## 真实历史数据重放

从C2原始bag只读抽取3对720P图像，在新独立目录通过真实libturbojpeg增量工厂；Q95/420、解码尺寸、左右目和Header/整数时间检查通过。原bag未复制或修改。

GNSS用最新会话111,834原始字节重复11次，保存1,230,174 bytes，SHA与重复输入一致。输入时钟明确SYNTHETIC，逻辑跨度约338.8秒；测量UTC不伪造。5类发布累计为12,562 / 12,562 / 5,379 / 5,379 / 0，周期同步超过50次，零UTC消息符合无UTC事实。不是338秒真实串口实验。

## 唯一writer真实bag回读

将历史GNSS五类消息fixture重复60次，产生100,980条输入，通过production RecordingQueue/GnssIngress及同一rosbag writer写入新的测试sensors.bag后回读。所有序列化字节完全一致，五类消息类型/MD5保持兼容。错误MD5、满队列、序列化错误、写盘错误、退出排空、旧模式FIFO均测试通过。

输入ROS载荷保持原历史值，测试bag接收时间为人工逻辑300秒；不是新传感器数据，也不能用于证明测量时间连续性。证据：`repeated_bag_paced_output/test_result.json`。

## 保留的测试失败和修正

1. 首次未限速大批量writer压力向有界队列瞬时灌入数据，触发拒收并使测试断言失败，原日志和部分bag保留。仅将离线测试生产者改为等待队列有余量后提交；生产回调及其非阻塞拒收策略没有修改。单独队列满失败验收仍通过。最终测试证明长序列正确写入/回读，不证明任意输入速率可实时处理。
2. 首次3对JPEG检查fixture缺少video_timestamps.csv，检查按预期失败。只在新测试目录补入原sidecar对应3行后通过；没有改历史数据或放宽检查。

## 文件保护

78个修改前文件已备份及哈希记录；7份旧配置、GNSS-R2.1核心和三时钟采样/计算文件哈希均不变。catkin_ws Git状态与R2.1基线相同。最新历史会话1851个文件的size/mtime不变；这不是对每个大文件重新完整SHA扫描。GNSS原始SHA256再次核对为：

`dbdf7922bac9a73e9d9f1ca1a153bc0e2ac2515a4242617f266d58a141483a51`

没有修改FAST-LIVO2/Livox/STM32/L2-B/NTP，没有删除历史文件，无commit/push。构建产物更新清单见`changed_original_files.json`。

## 验收边界与下一步

| 项目 | 状态 |
|---|---|
| 有界JPEG事件、增量索引、故障记录、软件编译 | SOFTWARE_TESTED |
| GNSS-R2.1原始字节/解析回归、五类消息writer回读 | SOFTWARE_TESTED |
| 5分钟实机JPEG/MID/GNSS并发与正常退出 | HARDWARE_PENDING |
| 真实CPU/RSS/温度/吞吐/队列趋势 | PENDING_HARDWARE |
| 断电后完整bag恢复能力 | UNVERIFIED，可能丢失未同步尾部 |
| IMA1历史无漏读 | 未保证；单槽漏读继续严格记录 |
| 新会话L2-B/GNSS→MID映射 | PENDING |
| PHYSICAL_SYNC | PENDING |
| 20分钟 | PENDING，未开放 |

5分钟软件入口已准备好。真实JPEG与bag能否长期稳定写入，需要用户手动执行implementation报告中的一次300秒测试。后续先核对退出/各数据流数量、JPEG索引、bag完整可读、磁盘保护、三时钟和资源曲线，再决定是否推进20分钟；不把本轮离线通过写成实机通过。
