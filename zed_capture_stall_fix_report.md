# ZED 2i + MID-360 提前退出分析与修复

日期：2026-10-16。分析会话：`/home/jetson/zed_capture_data/20261015_201642_783281d7`。

结论：已确认并修复停流保护中的并发取时错误。旧代码先取得 `CLOCK_MONOTONIC`，随后读取采集线程持续更新的原子时间戳，可能对“旧当前时间 − 新到达时间”进行 `uint64_t` 减法，发生下溢并误判超过 3 秒。四路数据在错误前均有毫秒级到达记录，本次证据强烈支持该误判路径。旧日志没有保存保护判断的 `n` 和四个原子变量快照，因此不能逐分支证明最终是哪一个条件先触发；ZED HID 更新与最后一次诊断取时的交错是最直接的证据。

修复状态为 **SOFTWARE_TESTED / HARDWARE_PENDING**；本轮没有启动 ROS Master、Livox 或真实相机采集。原失败会话仍为 **FAIL**，时间映射及物理同步仍为 **SYNC_PENDING**。

**原始记录与到达时间**

已读取 `capture.log`、`capture_summary.json`、`manager_result.json`、`capture_metrics.jsonl`、`video_timestamps.csv`、`video_timing.csv`、`zed_imu_raw.csv`、`anchors.jsonl`、`resources.jsonl`、`startup_readiness.json`、`device_settings.txt`、`livox.log`、`session.json`、`check_result.json`，并重新只读反序列化整个 bag。修复前源码、上游副本及节点二进制与会话保存的软件哈希清单一致。

错误发生于主机时间 **2026-10-15 20:16:58.623053000（Asia/Shanghai）**，日志 epoch 为 `1792066618623053000 ns`。

| 输入 | 已保存数量 | 最后正常到达的主机时间（同日） | 距错误日志 | 全段最大接收到达间隔 |
|---|---:|---|---:|---:|
| ZED 左右目，同一个双目缓冲 | 各 270 | 20:16:58.605661288 | 17.391712 ms | 66.907808 ms |
| ZED IMU / HID | 3688 | 20:16:58.622768296 | 0.284704 ms | 4.269440 ms |
| MID-360 点云 | 106 | 20:16:58.589224936 | 33.828064 ms | 102.189952 ms |
| MID-360 IMU | 2135 | 20:16:58.619920360 | 3.132640 ms | 9.053952 ms |

ZED 使用 CSV 中 DQBUF/HID 完成时记录的主机实时钟；Livox 使用 bag 的记录时间，该值由本节点 ROS 接收回调获取，未使用 GPS 消息 header 与主机时间混算。以上不是曝光时间。ZED 同时保存的 realtime-minus-monotonic 偏移全段变化范围为 32.384 µs，未见足以解释 3 秒的主机时钟跳变。Livox 原回调的精确单调时钟当时未写盘，不用估算值伪装原始测量。

最后视频 DQBUF 单调时间为 `11168520868704 ns`，该帧 QBUF 完成于 `11168522926720 ns`，返回 0。最后有效 HID 报告完成于 `11168537975712 ns`。最后一条 `capture_metrics.jsonl` 的诊断取时为 `11168537975552 ns`，比 HID 完成时间早 **160 ns**；之后约 0.285 ms 就记录了错误。

**实际触发代码与输入条件**

旧版本位置：备份 [capture_node.cpp](evidence/stall_fix_20261016_123605/before/src/zed_capture/src/capture_node.cpp:232)。核心顺序为：

```cpp
uint64_t n = now(CLOCK_MONOTONIC);
if (n - last_diag > 1000000000ULL) diagnostic();
if (n - start_ns > 5000000000ULL &&
    (!last_video_ns || !last_hid_ns || !last_lidar_ns || !last_livox_imu_ns ||
     n-last_video_ns > 3000000000ULL || n-last_hid_ns > 3000000000ULL ||
     n-last_lidar_ns > 3000000000ULL || n-last_livox_imu_ns > 3000000000ULL))
    fail("required input missing/stalled for 3 seconds");
```

四个变量分别在视频 DQBUF 回调、正长度 HID 原始报告回调、`/livox/lidar` ROS 回调、`/livox/imu` ROS 回调更新。它们都是原子变量，但这不能使“取当前时间 + 多次读取变量”成为一个一致快照。`diagnostic()` 位于两者之间，进一步增加了交错机会。

以观察到的诊断取时和 HID 取时作演示，`uint64_t(11168537975552 - 11168537975712)` 等于 `18446744073709551456`，远大于 3 秒。真正的监控 `n` 在进入诊断前取得，日志未保存其精确值，不能把诊断时间直接称作原始监控 `n`。新增确定性软件测试验证了同一操作顺序可使新鲜输入触发旧保护，而修复后的顺序不会。

错误使节点进入失败停止流程，采集回调停止接收、队列排空、bag 完成关闭；节点返回 2，管理器保留 `interrupted=false`。因此末尾诊断的 269 对图像、3681 条 ZED IMU 等计数可小于最终汇总；这是诊断时队列尚未排空，不是额外丢弃或伪造数据。

**四缓冲、线程、HID 和准备等待排查**

| 检查项 | 实际证据及边界 |
|---|---|
| V4L2 四缓冲 | 请求与实际均为 4；源码按驱动返回数量分配、映射和排队。270 条 timing 记录均 `qbuf_result=0`，无无效图像缓冲。保留四缓冲配置。 |
| 采集线程 / DQBUF | 最长 DQBUF 段 0.059136 ms，DQBUF 后到 QBUF 最长 5.315584 ms；回调最长 5.291360 ms。最后一帧正常归还缓冲。录像未支持 3 秒互锁。 |
| HID | 3688 条保存报告全部有效；最长一次已记录 HID 读取 4.264224 ms。源码原有 `hid_read_timeout(...,2000)` 为 2 秒，没有修改；本段不存在对应的 2 秒接收空洞。 |
| 准备等待 | 2.486853952 秒后成功，Livox 与锚点稳定检查通过；其后才初始化相机/HID，设置读取结束后重新设置正式采集 `start_ns`。没有用准备等待消耗 30 秒采集预算。 |
| 约 12 秒含义 | 第一条锚点观察到错误约 12.0068 秒，视频原始时间跨度仅 9.031368 秒，准备和设备初始化解释了两者差别；不是 30 秒计时正常完成。 |
| 写入队列 / 磁盘 | 峰值 17,041,290 字节，容量 256 MiB，溢出 0；视频任务最大排队等待 8.932384 ms，写入任务最长 43.627232 ms。末尾仍有持续输入。 |
| USB / 内核 | 会话记录视频 USB3 为 5000 Mbit/s，HID 为独立的 12 Mbit/s 接口。目标时段内核 journal 查询无条目；这不能作为底层 USB 完全无异常的证明。 |

这些结果不证明设备永远不会停流，但不支持把本次保护触发归因于新增缓冲死锁、HID 超时或磁盘队列阻塞。未修改 Open Capture 厂商源码或设备参数。

**最小修复与新增诊断**

| 文件 | 修改 |
|---|---|
| [capture_node.cpp](src/zed_capture/src/capture_node.cpp:180) | 四路心跳各读取一次，然后取单调时钟；对固定快照判断，判断移到周期诊断之前。准备检查同样先读输入再取时，避免并发更新误重置稳定等待。 |
| [input_watchdog.hpp](src/zed_capture/include/zed_capture/input_watchdog.hpp) | 新增小型、可独立测试的快照和判断函数；保留超过 3 秒停流、启动超过 5 秒开始保护的严格边界。真实未来时间标为 `CLOCK_INVALID` 并失败，不把它夹为零来隐瞒错误。 |
| [input_watchdog_test.cpp](src/zed_capture/test/input_watchdog_test.cpp) | 旧下溢重现、固定快照、四路逐一停流、缺失、未来时间、3 秒/5 秒边界、多流同时超时及 JSON 测试。 |
| [CMakeLists.txt](src/zed_capture/CMakeLists.txt) | 增加上述独立软件测试目标，Release 模式也启用断言。 |
| [README.md](README.md) | 新增诊断字段与重测说明。 |

另新增本报告，并更新 `evidence/software_manifest.json` 以供下一次会话保存准确源码和二进制哈希；旧清单已经备份，历史会话中的清单未改变。

`capture_metrics.jsonl` 和 `/zed2i/diagnostics` 的 `input_watchdog` 包含实际判断时刻、正式采集开始时刻、门限、启用状态、每路 `last_arrival_monotonic_ns` / `age_ns` / `state` / `triggered` 和 `triggered_inputs`。缺失或未来值的年龄为 `null`，不会输出下溢后的巨大伪年龄。

触发保护时，`capture.log`、`failure.txt` 保存原因和快照，另直接写入并 fsync `input_timeout.json`，不依赖已停止接收任务的录制队列。保存失败会明确写错误日志，原失败返回码仍保留。会话构造拒绝复用已有该 sidecar 的目录。

诊断语义保持原保护契约：`zed_video` 是 DQBUF 心跳，`zed_hid` 是正长度 HID 报告心跳，后者不等同于有效 IMU 样本保证；有效性由原 CSV/完整性检查继续验收。本会话 HID 报告均有效。未改原始采集或消息时间戳，未增加超时门限，未移除保护，未改变完整性阈值。

**软件验证及保护结果**

| 验证 | 结果 |
|---|---|
| 独立工作空间 `catkin_make -j2 -DCMAKE_BUILD_TYPE=Release` | SOFTWARE_TESTED，返回 0，无编译错误或警告 |
| 新 watchdog 测试及 JSON 解析 | SOFTWARE_TESTED，返回 0；真正停流/缺失仍失败，新鲜输入交错不误报 |
| 原 `capture_core_test` | SOFTWARE_TESTED |
| 动态库环境测试 5 项 | SOFTWARE_TESTED |
| 真实记录分析工具测试 5 项 | SOFTWARE_TESTED |
| 合成 bag / 时间分析测试 7 项 | SOFTWARE_TESTED，仅合成，不代表实机通过 |
| 新节点 `ldd -r` | SOFTWARE_TESTED，无缺库、缺符号；实际 libusb 为 `/usr/lib/aarch64-linux-gnu/libusb-1.0.so.0.2.0`，仍采用原有仅子进程隔离策略 |
| 原 bag 只读完整检查 | 所有消息可反序列化、左右目数量和时间戳一致；完整性继续 FAIL |
| 原环境基线 | VERIFIED：4495 项文件状态、848 个文件 SHA256、276 个链接库 SHA256 未变化；原工作空间 Git 状态、软件包清单未变化 |
| 历史数据保护 | VERIFIED：55 个已有文件；所有 sidecar 哈希/大小/mtime/inode 不变，bag 大小/mtime/inode 不变。未写入原 bag；未以全 bag 哈希比对冒充已执行检查。 |
| 修复后真实 30 秒 | HARDWARE_PENDING，按用户要求留给普通 SSH 终端执行 |

完整证据目录：[stall_fix_20261016_123605](evidence/stall_fix_20261016_123605)。其中保存修改前源码/二进制、`changes.patch`、构建日志、测试日志、`offline_findings.json`、`bag_input_timeline.json`、原 bag 只读检查结果、动态依赖及保护检查结果。原 FAST-LIVO2、Livox、STM32、GNSS/UWB、系统依赖、CUDA/JetPack、网络和 SSH 配置均未修改，无 Git commit。没有进行原工作空间编译或硬件运行回归。

**保留的真实失败项和同步边界**

原会话第 172 对图像（主机 epoch `1792066615327557576 ns`）从 V4L2 sequence 172 跳到 175，可观察序号缺失 2 个；原始时间间隔 66.886 ms，约对应一个 30 Hz 采样周期空缺。这两个计数的语义不同，不能直接把序号差当作已证实的物理曝光丢失数。没有 duplicate/reset。该间隔与 3 秒保护不是同一门限或同一问题，仍报告 FAIL。

锚点记录 2177 个状态、可观察漏读 401 次，现有完整性检查继续 FAIL；图像锚点包围覆盖为 270/270，仅是 L2-B 输入候选覆盖，统一时钟映射没有执行或验证。未改单槽共享状态或 Livox 写入架构。

bag 的 22 条 MID-360 时间诊断均为 `time_type=2`、GPS，时钟源切换计数均为 0；点云及 MID IMU header 无回退、重复。仅能确认已保存时段的设备时间连续和驱动报告同步；没有原始 GPRMC 串口记录，不能单独证实所有 GPRMC 报文，更不能据此声明图像物理同步已验证。

本次修复解决提前退出的软件缺陷，不将已有短录像升级成完整 30 秒测试。120 秒测试条件仍未满足，先验收新的 30 秒会话，保留图像间隔与锚点完整性失败项。

**用户普通 SSH 终端重测**

```bash
/home/jetson/zed_capture_ws/scripts/start_capture.sh --duration 30
```

命令会执行原有预检、创建新的唯一会话目录，停止后自动检查。不要复用旧目录。如果仍提前退出，保留新会话全部内容，重点查看 `input_timeout.json`、`capture.log`、`capture_metrics.jsonl`、`video_timing.csv` 和 `livox.log`。未出现超时时 `input_timeout.json` 不生成，这是正常的；实际成功仍以时长、逐流完整性和原检查结果为准。

回退仅涉及本独立工作空间：本轮覆盖文件的原版及旧节点二进制在证据目录的 `before/` 中，可按审核需要恢复并在独立工作空间重新编译。新增测试和报告可原样保留；无需删除历史数据、清理构建目录或修改系统库。未自动执行回退。
