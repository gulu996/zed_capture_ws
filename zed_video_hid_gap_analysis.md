# ZED 视频与 HID 短时缺口专项分析

日期：2026-10-17。历史输入：`/home/jetson/zed_capture_data/20261017_130643_750bf403`。本轮证据目录：`/home/jetson/zed_capture_ws/evidence/video_hid_gap_20261017_141528`。

**离线分析、局部诊断补充、编译及软件回归已完成；新 30 秒实测为 PENDING_HARDWARE / HARDWARE_PENDING。未确认导致丢帧的具体软件缺陷，因此没有实施猜测性采集优化。** 当前沙箱无法访问视频/HID，ROS AF_INET socket 被拒绝（EPERM）；没有启动新录制、没有新 bag。

## 结论及证据边界

| 问题 | 结论 | 分类 |
|---|---|---|
| 1. 10 次视频异常分布 | 下表列出全部事件；9 次约 66.9 ms，1 次 133.905 ms | VERIFIED |
| 2. pair 374 是否发生 select 超时 | 前一 QBUF 到下一条已记录 select 为 100.164483 ms；与一次 100 ms 超时相符，但原日志遗漏非成功循环，不能确定 | SUPPORTED_HYPOTHESIS（一次超时）；具体发生情况 UNRESOLVED |
| 3. DQBUF/QBUF 错误 | 887 个已记录成功帧的 QBUF 返回值均为 0；失败 DQBUF、EAGAIN/EINTR 原来没有落盘，历史次数 UNKNOWN | VERIFIED / UNRESOLVED |
| 4. 实际缓冲数量 | `device_settings.txt` 记录 requested=4、actual=4 | VERIFIED |
| 5. 用户态阻塞 | bag 写入任务最长 195.484 ms；图像复制最长 6.748 ms，帧回调最长 6.764 ms。未发现 100 ms 图像处理阻塞证据；等待就绪/调度与处理耗时不能混为一谈 | VERIFIED；具体停顿根因 UNRESOLVED |
| 6. HID 与视频关系 | 5 次 tick 缺口只有 sample 5101 的接收时刻位于 pair 374 的原始视频时间间隔内；其余 4 次不重合 | VERIFIED（时间关系，不是因果） |
| 7. 能否定位 USB/内核/采集程序 | 不能。缺少历史 select 非成功事件、libusb 回调到达和队列计数，设备内部/USB 物理包状态 UNKNOWN | UNRESOLVED |
| 8. 修复了什么 | 补齐两个已证实的诊断缺口：非成功 V4L2 循环、HIDAPI 排队/读取事件；未宣称修复真实丢帧原因 | VERIFIED（源码及软件测试） |
| 9. 新测试长间隔是否减少 | 没有新实机采集，无法比较 | PENDING_HARDWARE |
| 10. 尚未解决的数据缺口 | 历史 24 个驱动序号缺口、5 次 HID tick 缺口、419 次锚点更新漏读仍保留 | VERIFIED |
| 11. 工程级持续采集条件 | 可执行下一次受控 30 秒诊断录制；尚无充分证据保证持续无缺口采集，严格数据完整性仍未通过 | UNRESOLVED / PENDING_HARDWARE |

## 历史视频逐项核对

时间列为主机记录的接收 REALTIME（Asia/Shanghai），仅供定位日志；原始间隔直接用 V4L2 原始时间戳计算。不是曝光中心时刻。`前 QBUF→select` 是到**下一条已记录** select 开始的时间，历史文件可能跳过中间失败/超时循环。

| pair_id | 接收时间 | sequence | 原始间隔 ms | 前 QBUF→select ms | 本次已记录 select 等待 ms |
|---|---|---|---:|---:|---:|
| 175 | 13:06:56.294755 | 173 → 176 | 66.877 | 0.002336 | 64.725922 |
| 223 | 13:06:57.933883 | 223 → 226 | 67.019 | 0.001729 | 65.157558 |
| 374 | 13:07:03.085680 | 376 → 383 | 133.905 | 100.164483 | 31.704061 |
| 464 | 13:07:06.129817 | 472 → 475 | 66.883 | 0.004224 | 65.000453 |
| 472 | 13:07:06.430849 | 482 → 485 | 66.993 | 0.003232 | 65.144689 |
| 495 | 13:07:07.233778 | 507 → 510 | 66.886 | 0.004225 | 65.075189 |
| 568 | 13:07:09.709250 | 582 → 585 | 66.884 | 0.004257 | 65.011266 |
| 615 | 13:07:11.315008 | 631 → 634 | 66.884 | 0.002305 | 63.856329 |
| 656 | 13:07:12.720035 | 674 → 677 | 66.889 | 0.002497 | 63.983163 |
| 861 | 13:07:19.611303 | 881 → 884 | 66.886 | 0.002401 | 65.106050 |

887 对图像左右目严格配对；876 次正常 sequence 递增、10 次向前 gap、0 duplicate、0 reset/backward。9 次 sequence delta=3、1 次 delta=7，因此可观察缺失驱动编号为 `9×2+6=24`。按约 33.45 ms 节拍推算有 12 个缺失采样周期，但这也**不是经过独立验证的物理曝光丢失数**。不补帧、不修改时间戳。

9 个较短异常中，前一 QBUF 后只经过 0.0017～0.0043 ms 就进入已记录 select，随后 select 内耗时约 63.86～65.16 ms。这不支持“用户态在进入 select 前进行长时间图像处理”作为这 9 次事件的共同解释；仍不能区分设备未提供可用帧、内核完成延迟和线程被唤醒后的调度延迟。

原 flags=73729（0x12001）：MONOTONIC 类型位 0x2000、SOE 来源位 0x10000，其语义沿用当前 V4L2 驱动声明；不能单靠 flags 认证真实曝光时刻。实际双目宽 3840、高 1080，原始 YUYV；相机序列号 38003368，HID 固件 3.11，自动曝光保留开启。曝光控制值 140 是控制单位，未解释成毫秒，也未改变设置。历史 USB 记录 video 5000 Mb/s、HID 12 Mb/s：HID 的低速率不是视频降为 USB2 的证据。

## pair 374 的共同时间轴

所有区间统一到已有 MONOTONIC 观察轴；原始值见 `pair374_timeline.json`。时钟监测 fsync 的 MONOTONIC 边界由 20 Hz 样本插值，仅作为近似关联。

| 事件 | MONOTONIC 区间 ns | 观测 |
|---|---|---|
| 时钟写盘线程 fsync | 1848383373804～1848613940494（插值） | RAW 测得 230.547168 ms；期间采样线程继续得到样本 701～704，无漏期限 |
| bag pair 367 写入任务 | 1848386932218～1848582416131 | 195.483913 ms；含该 writer 任务内的 bag/元数据/发布工作，不等同于单次磁盘 write 系统调用 |
| 视频原始时间缺口 | 1848553338000～1848687243000 | 133.905 ms，sequence 376→383 |
| bag pair 368 写入任务 | 1848585327419～1848621977510 | 36.650091 ms |
| pair 373 QBUF→下一条 select | 1848587596508～1848687760991 | 100.164483 ms，中间原来不可观测 |
| 锚点历史缺口 | 1848625621756～1848636596737 | 漏读 1 个更新 |
| HID sample 5099 接收间隔 | 1848626208174～1848636063924 | 9.855750 ms；该报告 tick 增量仍为正常 64 |
| HID sample 5101 接收间隔 | 1848637214069～1848638210954 | 主机 0.996885 ms，设备 tick 增量 192（标称 7.5 ms） |

pair 374 已记录 select 等待 31.704061 ms、DQBUF 调用边界耗时 0.020130 ms。**一次未记录的 100 ms 超时是合理候选，不能把这 100 ms 直接解释为用户态线程执行阻塞，更不能确认相机停止输出。**

录制队列峰值 50,844,662 B，配置上限 256 MiB，溢出 0；最大图像 writer 排队等待 166.440708 ms。写线程的任务执行位于队列锁之外，图像/HID 回调不等待磁盘 fsync，但仍可能受到共享 CPU、内存、内核或存储负载间接影响。资源采样约 1.03 s，不能排除 100 ms 级瞬态。pair 374 附近窗口系统 CPU 约 26.69%、Dirty 237.86 MiB，不足以证明或排除页回收/调度停顿。磁盘相关性归为 **SUPPORTED_HYPOTHESIS**，不是因果证明。

## HID 五次缺口

| sample_id | 主机接收时间 | tick 差 | 标称设备间隔 ms | 主机接收间隔 ms | 前 5 条中的最大接收间隔 ms | 与视频原始缺口重叠 pair |
|---|---|---:|---:|---:|---|---|
| 2931 | 13:06:57.642952 | 128 | 5.0 | 1.989762 | 6.646429（#2929） | 无 |
| 5101 | 13:07:03.004405 | 192 | 7.5 | 0.996885 | 9.855750（#5099） | 374 |
| 5940 | 13:07:05.077549 | 128 | 5.0 | 0.989847 | 6.221949（#5938） | 无 |
| 10169 | 13:07:15.520486 | 128 | 5.0 | 1.996218 | 6.280906（#10167） | 无 |
| 10556 | 13:07:16.480583 | 192 | 7.5 | 0.989308 | 10.707212（#10554） | 无 |

12190 条原始 HID 都是 62 字节，单一有效时间段，无启动 485 秒跳变、无 tick 回退/重复。5 次异常 tick 增量为 128/192；根据标称 64 tick 节拍，相当于 7 个未观测采样周期，**不是 7 个已确认丢失 USB 包**。TIME_VALIDITY_PASS 不等于 IMU 完整性 PASS。

每次异常的前两条附近都出现 6.22～10.71 ms 的主机接收长间隔，随后出现短接收间隔及 tick 缺口。支持“交付/处理不均匀”的观察，不能确定是设备未生成、USB/内核传输、HIDAPI 丢弃还是读取调度。全段最大接收间隔仅 10.707212 ms，也不能据此宣称 HIDAPI 一定没有积压，因为缺少入队到达历史。

HIDAPI 源码的有限链表在超限时删除最旧报告，旧代码没有记录此事。实测这个**软件逻辑**的保留上限为 32 条、插入后瞬时峰值 33（源码注释中的“30”不是实际精确容量）。本轮未改变上限、读超时 2000 ms、CLOCK_REALTIME 条件等待或 report 生命周期。SYNTHETIC 测试注入 80 个完成回调，观察 48 次队列丢弃，读取出的 32 个报告严格保持 FIFO 原始字节。该测试不能证明历史会话发生过这些丢弃。

## 源码审计与最小改动

V4L2 每次循环重新建立 fd_set 和 100 ms timeval；设备以 O_NONBLOCK 打开；DQBUF EAGAIN/EINTR 重试，其他错误退出；同步图像回调完成后再 QBUF。实际 4 缓冲区经 REQBUFS 返回值记录，没有发现可复现的生命周期、select 或 EAGAIN 处理错误。图像拆分/拷贝、原始 Header 和时间戳路径未改动。

HID libusb 读线程在打开设备时启动；Open Capture 读取队列，原始回调先保存报告，原有启动时间分段逻辑继续使用。关闭顺序仍是停止并 join Open Capture 线程，再停数据流、取消/join HIDAPI 线程。新诊断不新增采集线程、不修改调度策略。

新增文件在**每个新会话目录**自动生成：

- `video_io_events.csv`：逐循环 event_id，select 起止/结果/errno，DQBUF 是否调用及结果/EAGAIN/锁等待，QBUF 起止/结果，原始 sequence、timestamp、flags、buffer index，成功帧间隔、线程 CPU 时间及累计错误计数。无成功帧的事件 pair_id=0；不能把其零值原始时间戳当真实帧。旧 `video_timing.csv` 仍只记录成功取帧。
- `hid_io_events.csv`：每次读取 read_id、原始报告 sample_id/tick、读取起止、主机接收间隔、libusb 完成回调进入时刻、出队时刻、队列深度/峰值/累计丢弃、读超时/错误和 libusb completion status。libusb 时刻是**用户态回调到达**，不是 USB 硬件时间戳；transfer_status 是传输完成状态计数，**不是物理包计数**。物理 USB 丢包和固件内部状态始终 UNKNOWN。
- `capture_summary.json` 增加诊断版本及两类已写事件数量。检查器自动检查事件序号、行数、原始 V4L2 元数据、实际 HID 字节长度及 tick、一致性和可观察错误，结果进入 `check_result.json.low_level_io_diagnostics`。旧会话明确 `UNAVAILABLE_IN_LEGACY_SESSION`，不能借缺失证据判定无错误。

诊断使用原有有界 writer 队列（每事件计入 768 B），没有新增后台线程或无界缓存，新增采集回调不做文件写入/flush/fsync。CSV 由原写线程写入，正常结束时 drain 后统一关闭/fsync；已有失败和队列溢出保护仍有效。约 430 事件/s 对应新增队列计费约 0.33 MB/s，实际 CSV 大小及 CPU 影响须新实机确认，不能据软件测试声称零开销。异常退出仍保留已写证据，不能承诺 SIGKILL/断电下未落盘缓冲绝不丢失。

所有已返回给原始回调的 HID 字节继续存入原 `zed_imu_raw.csv` 与 bag。HIDAPI 在原始回调之前可能删除的报告，不会被虚构为已保存；现在能观察丢弃计数与最近被弃报告到达时间，但不能恢复其原始字节，也不能据最后一次读取快照保证关闭后的队列完全没有未消费数据。

修改文件（均在独立 zed_capture_ws 内）：

- `vendor/zed-open-capture/src/videocapture.cpp`
- `vendor/zed-open-capture/include/videocapture.hpp`
- `vendor/zed-open-capture/src/sensorcapture.cpp`
- `vendor/zed-open-capture/include/sensorcapture.hpp`
- `vendor/hidapi/libusb/hid.c`
- `src/zed_capture/src/capture_node.cpp`
- `src/zed_capture/CMakeLists.txt`
- `scripts/check_recording.py`

新增文件：

- `vendor/hidapi/hidapi/hidapi_capture_trace.h`
- `src/zed_capture/test/video_io_test.cpp`
- `src/zed_capture/test/hid_io_test.c`
- `scripts/analyze_io_diagnostics.py`
- `scripts/test_io_diagnostics.py`

此外更新 `evidence/software_manifest.json`，增量重建采集二进制及测试目标。`start_capture.sh`、`capture.yaml`、`run_joint_test.sh`、三时钟监测和 L2-B 核心没有修改。

## 软件测试与保护检查

- `catkin_make -j2 -DCMAKE_BUILD_TYPE=Release` 成功，未清理工作空间；首次构建发现新增 memcpy 缺少 `<cstring>`，已补齐，最终构建日志无 error/warning。
- 5 个 C/C++ 测试可执行程序通过：新增真实 V4L2 循环的模拟 select/ioctl 分支、真实私有 HIDAPI 队列的模拟 completion；原核心、3 秒 watchdog、IMU 时间分段回归继续通过。
- Python：诊断 10 项（含历史 sidecar 只读回归）、动态库隔离 5 项、原分析 5 项、离线 bag/时间工具 9 项通过。模拟输入明确为 SYNTHETIC，不能计作实机验证；新解析器专门覆盖实际 62 字节 HID，未假设固定 64 字节。
- `ldd -r` 通过，无未解析符号；进程局部 libusb 路径仍为 `/usr/lib/aarch64-linux-gnu/libusb-1.0.so.0.2.0`。没有修改全局 LD_LIBRARY_PATH、MVS SDK、系统库。
- 原保护基线 4495 条文件记录、848 个文件 hash、276 个动态库 hash 无变化，软件包与原 catkin Git status 不变。旧会话/三时钟 37 个 sidecar 或诊断文件 hash 一致；bag 大小 7,492,237,985 B、mtime 不变。bag 修改前 hash 原值为 null，因此不宣称前后 bag SHA 一致。
- 检查辅助过程曾错误用 read_bytes 读取大 bag 被终止（137），随后分块比较又因将 null 基线误当 hash 报告不匹配。两者均为本轮辅助核验错误，原日志保留；最终按有效 hash 与 size/mtime 分别验证，见 `original_data_preservation_final.json`，并非采集程序失败或 bag 被修改的证据。

测试证据：`build_initial.log`、`build.log`、`software_tests.json`、`analyzer_final_tests.json`、`dynamic_dependencies.json`、`protection_after.json`、`original_data_preservation_final.json`。历史复核与本轮补充时间轴见 `historical_analysis.json`、`historical_review.json`、`historical_timeline.csv/json`、`event_details.json`、`pair374_timeline.json`。

## 新一次 30 秒实测

**PENDING_HARDWARE / HARDWARE_PENDING。** 本轮只执行一次只读 `run_joint_test.sh --preflight-only`，预检结果目录：

`/home/jetson/clock_diag/runs/joint_20261017_142346_d5997393`

按 VID/PID 实际身份匹配到视频 2b03:f880 与 HID 2b03:f881，但设备节点在当前沙箱中不可访问，ROS socket EPERM；MID 未探测，不把权限限制归因于硬件断电。未请求绕过沙箱、未改 udev、未启动 ROS Master 或 Livox、未重复尝试采集。

在普通 **jetson 用户 SSH 终端**确保 MID-360/STM32 供电、ZED 保持连接后，只执行一次：

```bash
/home/jetson/clock_diag/run_joint_test.sh
```

脚本保留原 15 秒前监测 → `start_capture.sh --duration 30` → 至少 15 秒后监测及完整 bag 检查流程。自动创建唯一 clock run 与 `/home/jetson/zed_capture_data/` 会话；新诊断已接入原自动检查，不需要协调额外后台进程。用 Ctrl-C 正常停止；不要在完整性检查仍运行时重复启动。若视频 gap 或锚点漏读继续存在，脚本仍可因严格检查返回非零，必须查看 manager 与 integrity 各自状态。

| 指标 | 历史 20261017_130643_750bf403 | 本轮新实测 |
|---|---|---|
| CAPTURE_RUNTIME | PASS；887 对、316 点云、6322 MID IMU、12190 ZED IMU | PENDING_HARDWARE |
| DATA_INTEGRITY | FAIL：10 视频长间隔、24 驱动编号缺口、5 HID tick 缺口、419 锚点漏读 | PENDING_HARDWARE |
| ZED_IMU_TIME_VALIDITY | PASS，仍不是完整性 PASS | PENDING_HARDWARE |
| CLOCK_DIAGNOSTIC | PASS，20 Hz 样本 1365，漏期限 0 | PENDING_HARDWARE |
| L2-B | 用户提供的笔记本结果 873/887 有效；本轮未重跑、未改门限 | 未执行新的映射验证 |
| PHYSICAL_SYNC | PENDING，未验证曝光物理同步 | PENDING |

419 个锚点更新漏读（401 启动、18 稳态）、约 1.275% ZED/MID 设备时间比例差、内外参未知继续保留。后续一次实测应优先用新诊断分开判断：select 实际超时、DQBUF EAGAIN、锁等待/循环调度间隔、HIDAPI 实际丢弃、libusb 交付延迟；若仍不能定位则继续 UNRESOLVED，不能通过放宽门限制造 PASS。

## 回退

修改前源文件、CMake、检查器、manifest 和采集二进制备份在 `/home/jetson/zed_capture_ws/evidence/video_hid_gap_20261017_141528/before/`，差异在 `changes.patch`，路径清单在 `changed_files.json`。如需回退，先确认没有采集进程，保存当前版本，再逐一恢复本轮修改的已有文件并在独立工作空间增量编译；新增测试/诊断文件可保留为未引用文件，无需删除任何数据。旧二进制只用于核对，不改系统动态库。禁止 clean、删除历史记录、Git reset/commit/push。
