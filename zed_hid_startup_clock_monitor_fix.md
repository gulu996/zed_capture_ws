# ZED HID 启动时间分段与三时钟监测修复

日期：2026-10-17。软件状态：SOFTWARE_TESTED；新 30 秒联合实测：**HARDWARE_PENDING**。

历史输入：`/home/jetson/zed_capture_data/20261016_203823_3c52dfa4`；三时钟输入：`/home/jetson/clock_diag/runs/joint_20261016_203807_3652b40b`。本报告所有历史派生分析写到 `/home/jetson/zed_capture_ws/evidence/hid_clock_fix_20261017_124656`，没有修改历史 bag 或 sidecar。旧 bag 仍为 7,530,959,895 字节；本轮未创建新采集 bag。

## 1. HID 启动异常：已验证事实与边界

- VERIFIED：原始 HID 小端字段解析出的全部 12186 个 tick 与 CSV 相同。第一条 tick=17005120，第二条=29429285；按既有整数换算 `ticks*78125/2`，相差 **485.318945312 秒**，主机接收间隔仅 **0.864830 毫秒**。
- VERIFIED：此前 `20261016_143401_7174fbf5` 最后 tick=17005056；新会话第一条恰好为它加 64。第一条 `hid_read_timeout` 实际调用只耗时 1.761 微秒。两份原始报告字节并非同一条记录的复制。
- SUPPORTED_HYPOTHESIS：启动时得到了一条滞留的旧报告；证据很强，但不能仅凭 tick 和调用耗时确定它来自哪个缓存层，也不能绝对排除设备内部时间状态切换。
- UNRESOLVED：设备端端点/FIFO、在途 USB 传输与新句柄打开后的 HIDAPI 队列各自的贡献；没有 USB 抓包/设备固件事件，不能声称定位到具体层。

源码路径：`vendor/zed-open-capture/src/sensorcapture.cpp` 的 `open → initializeSensors → startCapture → grabThreadFunc`；`vendor/hidapi/libusb/hid.c` 的 `hid_open_path/read_callback/hid_read_timeout/hid_close`。

HIDAPI 在打开句柄时已启动 libusb 读取线程，早于 Open Capture 启用数据流、启动自己的 grab 线程。报告先进入 HIDAPI 队列；`hid_read_timeout` 会立即返回队列第一项，否则使用 CLOCK_REALTIME 条件变量等待，当前超时 2000 ms。该超时不是报告的采集时刻；本轮没有修改超时或系统时钟。

关闭顺序为停止并 join Open Capture grab 线程、关闭数据流、`hid_close` 取消 USB transfer 并 join HIDAPI 线程、释放报告队列。因此旧进程的用户态队列并不会直接保留到下一进程。停止时在途报告、端点或新句柄启动期间入队仍是可能解释。上游 `initializeSensors` 的返回行为也已检查，但本轮没有更改 vendor 初始化/关闭实现，以免用未经实机验证的清空队列掩盖问题。

HIDAPI 上游队列在消费者严重落后时存在丢弃旧元素的逻辑；本轮未改动它。因此“保留全部 raw HID”严格指保留所有实际交付给采集回调的正长度报告，不能保证 USB 物理链路上每个报告都曾到达回调。

## 2. 最小修复：显式分段，不改原始时轴

新增 `imu_time_segments.hpp`，并接入现有 bag 写入线程。原 `zed_imu_raw.csv`、`/zed2i/imu_stamp`、`/zed2i/imu/data_raw`、原始 HID 字节、tick、Header 均保持原样。**原始 IMU 话题仍可能包含真实的 485 秒跳变；修复的是把它未经分段当作正式有效时轴的错误用法，不是伪造一条连续原始时轴。**

新增 `zed_imu_time_validity.csv` 和 `/zed2i/imu/time_validity`，以 sample_id 关联 raw 报告，保存 segment_id、判定触发样本、状态及原因。启动至少观察 8 条连续报告和 10 ms 接收时间跨度才确认连续性；最多暂存 32 条判定元数据。回退、重复及设备/接收增量相差超过 100 ms 会分段。这是粗大异常检测，不是新的同步精度门限，也未修改 L2-B 门限。候选段遇到跳变标记 INVALID_SUSPECT；结束前未确认或缓冲上限情形标记 UNCONFIRMED，全部保留并参与验收。

历史真实数据回归：

| 段 | sample_id | 数量 | 结论 |
|---|---|---:|---|
| 1 | 1 | 1 | INVALID_SUSPECT，UNCONFIRMED_BEFORE_DEVICE_HOST_DELTA_DISAGREEMENT |
| 2 | 2–12186 | 12185 | VALID_CONTIGUOUS，仅可在段内诊断 |

12186 条全部恰好分类一次，没有静默丢弃。段 2 接收时间跨度约 30.078449 秒，设备标称时间跨度约 30.463555 秒。`VALID_CONTIGUOUS` 不验证 tick 换算比例、绝对时间、L2-B 或物理同步。

`analyze.py` 拒绝对无分段证据的大幅前跳做整段拟合；有分段时输出所有段，并仅选择最大已确认连续段计算诊断关系。历史全流仍为 **ZED_IMU_TIME_VALIDITY_FAIL**。原严格数据完整性检查不因分段而改为 PASS；新增检查确保 bag/sidecar 分类一致、所有 raw sample_id 均有且仅有一条分类。

## 3. 历史三时钟缺口

旧采样线程每约一秒直接执行 CSV 写入、fflush、fsync，确实存在自身磁盘同步阻塞采样的路径。历史没有逐次 fsync 起止记录、采样线程缺页/调度计数，无法断定 216 ms 缺口全部由该路径造成。

- sample 538：RAW 夹取 108096 ns（108.096 µs），超过原 100 µs 门限。
- sample 840→841：间隔约 216.439 ms，跨过 3 个采样期限。
- 后者与视频 pair 570 的 bag 写入重叠：MONOTONIC 30248702495222–30248879891551 ns，耗时 177.396329 ms。存在 I/O/调度相关性，尚无因果证明。
- `resources.jsonl` 有系统 CPU/内存/进程统计，但不足以复原采样线程那一刻的页面回收或被抢占原因。

禁止桥接区间（用相邻观测样本界定保守边界，不假称这是内核故障的精确起止）：

| 原因 | 样本边界 | MONOTONIC 起止 ns |
|---|---|---|
| 宽夹取 | 537–539 | 30233491289052–30233591234793 |
| 缺口及漏期限 | 840–841 | 30248642438720–30248858895952 |

完整 RAW/REALTIME 起止及关联写入事件见 `historical_audit.json`、`historical_schedule_evidence.json`。其余三个连续区间分别为 sample 0–537、539–840、841–1361，约 26.850/15.050/25.984 秒，均具备 **CONDITIONAL_DIAGNOSTIC_ONLY** 价值。不得跨上述缺口拼接成完整有效桥接；旧全段仍为 **CLOCK_DIAGNOSTIC_INCONCLUSIVE**。

## 4. 监测局部优化与退出保护

保持 20 Hz 和 RAW_before → MONOTONIC → REALTIME → RAW_after 的顺序。保持原 RAW 固定 deadline 推进策略：相对休眠后重新检查 RAW deadline，不累积写盘耗时。顺序读数仍非精确同时采样，原夹取和缺口门限不变。

采样线程只做时钟、每约一秒 `adjtimex(modes=0)`/线程 rusage 读取及有界 SPSC 入队；格式化、CSV 写入和 fsync 移至写入线程。队列最多 256 个事件，ARM64 实际存储 116752 字节。满队列立即明确失败，summary 保留采样数/写出数差异；不会用丢弃数据维持表面正常。SIGINT/SIGTERM 排空已入队事件后同步文件；写盘错误明确失败。SIGKILL/断电无法保证内存队列持久化，缺失结束 summary 必须标记不完整。

新增 `monitor_io.csv` 记录 fsync 的 RAW 起止、耗时和队列占用；sample CSV 增加唤醒迟到、采样线程 CPU 时间；每秒保存该线程 minor/major fault、主动/被动上下文切换计数。未设置实时优先级、未改调度参数、未安装依赖。

## 5. 软件与无设备测试结果

| 测试 | 结果 |
|---|---|
| 独立 catkin 工作空间增量编译 `-j2` | PASS，未清理 build/devel |
| 原核心/输入停流 watchdog C++ 测试 | PASS，3 秒保护和启动边界不变 |
| 新 IMU 分段 C++ 回归 | PASS：485 秒跳变、连续约 1.28% 比例差、reset、duplicate、有限缓冲、结束未确认 |
| 真实历史 12186 条回放分类 | 全部分类，1 条疑似旧段、12185 条连续段 |
| 时钟 Python 测试 | 15 项 PASS，包括缺口边界、条件区间、SIGTERM 排空、SIGKILL 留存前缀及拒绝覆盖 |
| 异步队列 SYNTHETIC 压力测试 | PASS：消费者暂停 220 ms、顺序、满/空和排空 |
| 动态加载隔离测试 | 5 项 PASS；实际 ldd -r 无缺失符号 |
| 原会话分析测试 | 5 项 PASS |
| rosbag/IMU 离线测试 | 9 项 PASS，新增分类 bag/CSV 对照、漏分类必须 FAIL |

当前 libusb 仍解析为 `/usr/lib/aarch64-linux-gnu/libusb-1.0.so.0.2.0`，只在 zed_capture_node 子进程隔离加载；没有改变 MVS、系统库或全局环境。

无设备测量（不是实机采集验证）：

| 指标 | 新 5 秒测试 | 新 60 秒测试 |
|---|---:|---:|
| 保存样本 | 100/100 | 1200/1200 |
| 漏采期限 | 0 | 0 |
| 最大采样间隔 | 50.069584 ms | 50.201424 ms |
| 最大 RAW 夹取 | 0.832 µs | 17.664 µs |
| 队列峰值/溢出 | 1 / 0 | 1 / 0 |
| 最大写入线程同步耗时 | 29.454080 ms | 29.679680 ms |
| 全段 CLOCK_DIAGNOSTIC | PASS | **FAIL（真实非线性，不是采样丢失）** |

60 秒测试与部分软件编译检查重叠，没有 246 MB/s 真实图像写盘负载；不能由此证明实机下缺口已永久消失。该次采样线程 major fault=0、minor fault 计数未增加、involuntary switch=0，未观察到这一测试段中的相应异常。

**新测得主机时钟事实**：约 59.950 秒内 MONOTONIC−RAW 变化 **−31.326144 ms**；REALTIME−MONOTONIC 变化仅约 1 ns。5 秒分段速率从 −1097.297 到 −178.736 ppm，范围 918.561 ppm；全局仿射 RMS 2.137025 ms，最大残差 5.717303 ms，严格触发原门限。内核只读状态 freq 固定 +15.579071 ppm，offset 从 −37.829629 ms 收敛到 −5.630345 ms，status=8193，constant=3，time_state=0。

这直接证明本次 MONOTONIC 相对 RAW 存在共同速率变化，并支持内核相位调速解释。正常时间同步调速本身不等于系统故障；不能只看 freq 字段估算总瞬时速率。当前 D-Bus 查询受沙箱限制；可读 journal 显示本次启动 12:41:18 从 `162.159.200.1 (1.pool.ntp.org)` 首次同步成功。时钟源为 `arch_sys_counter`。没有停止 timesyncd，也没有改 NTP/RTC/系统时间。新 boot_id 不同于旧联合会话，禁止跨 boot 拼接。

本次未复现原 **309 ms** 幅度的异常；新证据进一步支持主机调速机制可能性，但不能证明旧事件由某次 NTP 测量引起。旧记录没有 RAW，旧事件根因仍需同会话设备/RAW 联合证据。

## 6. 新真实 30 秒采集：HARDWARE_PENDING

仅执行一次只读预检，目录 `/home/jetson/clock_diag/runs/joint_20261017_125242_cec7b7a5`。ZED VID/PID 与序列号在 sysfs 可见，视频接口枚举速度 5000 Mbit/s；当前沙箱没有对应 `/dev/video*` 节点，HID USB 节点不可访问，AF_INET/ROS socket 返回 EPERM。不能将此写成传感器损坏。MID 未探测，没有启动 ROS Master、Livox 或采集节点，没有生成新 bag，没有自动重试。

开启 MID-360 和 STM32 同步板、保持 ZED 2i 连接，在普通 jetson SSH 终端执行这一条命令即可：

```bash
/home/jetson/clock_diag/run_joint_test.sh
```

流程保持 15 秒预监测 → 原命令 `start_capture.sh --duration 30` → 实际录制结束后至少 15 秒后监测，等待 bag 完整检查。按 Ctrl+C 请求正常停止。脚本只尝试一次并创建唯一采集/诊断目录，自动输出六类验收；因原严格完整性问题返回 2 不代表采集节点必然提前退出，应分别查看 manager 和完整性结果。

| 验收维度 | 旧会话复核 | 本轮新实机 |
|---|---|---|
| CAPTURE_RUNTIME | PASS：returncode=0、failed=false、bag_finalized=true | HARDWARE_PENDING |
| DATA_INTEGRITY | FAIL：6 长间隔、12 缺失驱动序号、444 锚点漏读等 | PENDING |
| ZED_IMU_TIME_VALIDITY | FAIL：启动疑似旧段；后续 12185 条可分段分析 | PENDING |
| CLOCK_DIAGNOSTIC | INCONCLUSIVE：夹取/采样缺口 | PENDING；无设备 60 秒为 FAIL |
| L2B_MAPPING | PENDING | PENDING |
| PHYSICAL_SYNC | PENDING | PENDING |

## 7. 未解决事项与下一阶段

旧视频 6 次长间隔、12 个 V4L2 缺失驱动序号、444 个锚点更新漏读（历史复核中 400 启动、44 稳态）均保留为未解决；未放宽任何验收阈值。单槽锚点全部历史保存与图像可映射覆盖仍分别验收。

分段后的 ZED 标称 tick 秒/MID 秒比例仍为 **1.012815530**（约 +1.281553%）；没有改 tick 常数，没有将其归因于晶振漂移。物理曝光同步、相机/LiDAR 外参、完整 L2-B 接入均未验证。双设备诊断残差不能当作曝光同步精度。

目前具备一次 30 秒带诊断实测的软件条件；尚未完成本轮硬件验收，**不据此进入 120 秒测试或声明整段 L2-B 映射有效**。先获取新会话，确认 raw 保留与段边界、视频/锚点严格完整性、采样证据及实际时钟质量。

## 8. 修改、证据与回退

实际修改/新增文件：

- `/home/jetson/zed_capture_ws/src/zed_capture/src/capture_node.cpp`
- `/home/jetson/zed_capture_ws/src/zed_capture/CMakeLists.txt`
- `/home/jetson/zed_capture_ws/scripts/check_recording.py`
- `/home/jetson/zed_capture_ws/devel/lib/zed_capture/zed_capture_node`
- `/home/jetson/clock_diag/clock_monitor.cpp`
- `/home/jetson/clock_diag/clock_monitor`
- `/home/jetson/clock_diag/build.sh`
- `/home/jetson/clock_diag/analyze.py`
- `/home/jetson/clock_diag/joint_test.py`
- `/home/jetson/clock_diag/test_diag.py`
- `/home/jetson/clock_diag/README.md`
- `/home/jetson/zed_capture_ws/scripts/test_offline.py`
- `/home/jetson/zed_capture_ws/evidence/software_manifest.json`
- `/home/jetson/zed_capture_ws/src/zed_capture/include/zed_capture/imu_time_segments.hpp`
- `/home/jetson/zed_capture_ws/src/zed_capture/test/imu_time_segments_test.cpp`
- `/home/jetson/clock_diag/bounded_spsc.hpp`
- `/home/jetson/clock_diag/test_async_queue.cpp`

另新增本报告和证据文件；独立工作空间的生成文件仅由增量编译更新。未修改 vendor HID/视频驱动源码、原 catkin_ws、Livox、STM32、FAST-LIVO2、GNSS/UWB、系统依赖、NTP、网络、CUDA/JetPack。没有 Git commit/push。

保护检查：原环境 4495 项文件记录、848 项源码/配置哈希、276 个动态库哈希、软件包版本与原 Git 状态均未变化；本轮涉及的 59 个历史记录文件 size/mtime 与可行的小文件 SHA256 校验全部不变。大 bag 只比较 size/mtime，未为本轮重复计算 7.5 GB 哈希，也未重写或重复全量读取旧 bag。

证据索引：

- `/home/jetson/zed_capture_ws/evidence/hid_clock_fix_20261017_124656/before/`：修改前源码与二进制备份。
- `/home/jetson/zed_capture_ws/evidence/hid_clock_fix_20261017_124656/source_changes.patch`、`modified_files.json`：可审阅修改。
- `/home/jetson/zed_capture_ws/evidence/hid_clock_fix_20261017_124656/historical_audit.json`、`historical_imu_time_validity.csv`：真实历史回归；不是 SYNTHETIC。
- `/home/jetson/zed_capture_ws/evidence/hid_clock_fix_20261017_124656/historical_schedule_evidence.json`：缺口与 bag 写入重叠，包含证据边界。
- `/home/jetson/zed_capture_ws/evidence/hid_clock_fix_20261017_124656/monitor_5s/`、`monitor_60s/`：真实无设备时钟 CSV、adjtimex、I/O 日志和分析。
- `/home/jetson/zed_capture_ws/evidence/hid_clock_fix_20261017_124656/build.log`、`capture_tests.log`、`bag_classification_tests.log`、`clock_tests_final2.log`、`async_queue_tests.log`：构建及测试。
- `/home/jetson/zed_capture_ws/evidence/hid_clock_fix_20261017_124656/protected_state.json`、`preservation_check.json`：系统与历史数据保护。
- `/home/jetson/clock_diag/runs/joint_20261017_125242_cec7b7a5/test_result.json`：硬件预检受限证据，不是新采集结果。

回退只涉及本轮独立目录：先正常停止自己启动的采集/监测，再按 `modified_files.json` 从 `before/` 恢复需要的源码和 manifest，使用原 `scripts/build.sh` 增量构建；监测源码恢复后运行 `clock_diag/build.sh`。新增分段头文件/测试可以保留为未引用文件，不必删除；历史会话、bag 和证据永远不纳入回退。若回退恢复的是旧分析器，必须保留本报告警告：旧分析器可能错误跨越启动跳变拟合。未执行回退、服务变更或任何系统级安装。
