# Jetson 主机时钟与联合采集验证

记录日期：2026-10-16。软件和无设备基线已完成；本轮新的 30 秒联合采集为 **HARDWARE_PENDING**。当前沙箱拒绝 AF_INET socket 和相机设备访问，MID-360 按用户说明处于断电状态。本轮只运行一次离线硬件预检，没有启动或反复尝试真实采集。

结论：本轮直接测到了 **MONOTONIC 相对 RAW 的非线性调速**，60 秒基线变化 +30.364507 ms；只读内核状态和分段速率支持正常的 Linux PLL 相位修正机制。历史 −308.903540 ms 事件的主机调速假设因此明显增强，但由于历史没有 RAW/adjtimex 同期记录，仍不能宣称已确认该次事件由某次 NTP 测量引起。没有证据支持修改 NTP、内核、STM32 或传感器时间戳，故未做底层“修复”。

**已验证的历史事实**

原数据：[20261016_143401_7174fbf5](/home/jetson/zed_capture_data/20261016_143401_7174fbf5)。bag 为 7,421,882,678 字节。复核原 sidecar、汇总、日志，并使用已有约 7 MB 的 `imu_diag_only.bag` 核对 IMU 和 GPS 诊断；沿用原完整 bag 反序列化报告，未重复扫描 7.4 GB 图像数据。原文件未改写。

| 项目 | 结果 |
|---|---|
| 采集执行 | returncode=0，failed=false，bag_finalized=true，CAPTURE_RUNTIME_PASS |
| 左右目 | 各 879 帧，原始时间跨度 30.047639 s，29.220266 Hz，左右目严格对应 |
| 视频缺失 | 11 次长间隔，最长 69.589 ms；22 个缺失 V4L2 驱动序号，无回退/重复；不补帧、不改变门限 |
| MID-360 | 点云 313 帧，IMU 6261 条；原检查未见结构错误、序号断裂或时间回退/重复 |
| ZED IMU | 12072 条；1 次 5 ms 长间隔，无回退/重复，此失败项也保留 |
| 锚点 | 6285 个状态，漏读 429 次：启动未 ready 跨越 400 次，ready 状态后 29 次；按视频开始分界另为开始前 405、开始后 24，二者是不同统计口径 |
| 锚点轮询 | 32725 次，重复读取 26417，非稳定双读计数 23，最大轮询间隔 45.000620 ms；该计数不能单独区分系统调用失败与写入中状态 |
| 候选覆盖 | 879/879 图像有候选锚点包围；不能等同于 L2-B 或完整锚点历史通过 |
| GPS 诊断 | 导出 bag 的 64 条诊断均报告 type=2；只代表保存的诊断，不代表原始 GPRMC/PPS 已独立测量 |
| 原验收 | DATA_INTEGRITY_FAIL；所有原错误保留，未改写原 check_result.json |

本轮重新计算：31.866044950 s 内 MID 设备时间减主机 MONOTONIC 变化 **−308.903540 ms**。在相同接收时间覆盖窗口内，MID/主机仿射残差 RMS **32.724646 ms**，ZED/主机 **33.144160 ms**；两者残差相关系数 **0.999967**。通过共同主机接收时间作关联后，MID/ZED 标称 tick 时间拟合 RMS **0.265321 ms**，最大绝对残差约 5.093 ms。后者含接收时延与插值影响，**不是物理同步精度**。全段 MID 拟合 RMS 32.242851 ms 与共同窗口结果不同，报告明确区分拟合窗口。

用户提供的 L2-B 结果为 542 对通过、337 对拒绝，其中 315 对斜率越界。本机未发现对应完整 L2-B 实现与该次输出，未重新开发或伪称重跑该模块；这组数量标记为用户已提供结果。此轮工作是原始时钟证据的独立回归。

**时钟服务、接口及语义审计**

内核为 5.10.216-tegra，当前及可选 clocksource 均为 `arch_sys_counter`。历史采集与当前基线 boot_id 都为 `0066fe30-e68b-4324-8292-d4025209a7bf`。三种 clock_gettime 接口及 `adjtimex(modes=0)` 在当前沙箱可正常只读调用。

`timedatectl`、`timedatectl timesync-status/show-timesync`、`systemctl show` 被 D-Bus 权限拒绝，`/proc/timer_list` 不可读；已经保存原始错误，标记 UNAVAILABLE。可读取的 journal 仍只显示 12:30:52 向 `162.159.200.1:123 (0.pool.ntp.org)` 首次同步，没有能直接证明 14:34 调整幅度的日志。当前服务 ActiveState、当前服务器和最新 NTPMessage 需由一键脚本在普通 SSH 环境补录，不能用旧日志冒充当前状态。

用户此前观察到 timesyncd active、chrony/ntp inactive、Frequency=1518548（约 +23.17 ppm），并有被忽略的 −292.896 ms NTP 测量。该测量没有被当作已执行修正。本轮真实基线读取的内核值已不同：freq=11380714，即 **+173.655914 ppm**；tick=10000 µs；status=8193，即 STA_PLL|STA_NANO；time_state=TIME_OK；constant=4。所有查询 modes 都为 0。

Linux 的 MONOTONIC 与 RAW 并非同速保证：RAW 不带 NTP 漂移调整，而 MONOTONIC 会体现时钟调速；顺序读取也非精确同时。见 [Linux 官方 timekeeping 文档](https://docs.kernel.org/core-api/timekeeping.html)。因此仅看 `freq` 不足以推断瞬时速率，PLL 的相位偏差消化同样贡献速率。

原采集程序保留 V4L2 timeval、sequence、flags 和 DQBUF 前后 MONOTONIC；本历史会话标志包含 MONOTONIC 和 SOE。标志语义由驱动提供，不能直接当作物理曝光中心或经验证的曝光同步，见 [V4L2 官方缓冲时间戳说明](https://docs.kernel.org/userspace-api/media/v4l/buffer.html)。未替换为 RAW。

Livox `PubHandler::OnLivoxLidarPointCloudCallback` 对同一个 IMU 包保存设备时间与 `MonotonicNowNs()`；后续队列携带该 host 值，`UpdateImuAnchor` 另存 update 时间。GPS/type=2 分支直接保留包中的 64 位设备时间，未走主机 wall-clock 回退分支。源码支持其接收关联语义，但不证明网络/USB 接收时延恒定。

**5 秒及 60 秒无设备基线**

| 项目 | 5 秒基础测试 | 60 秒基线 |
|---|---:|---:|
| 样本 | 100 | 1200 |
| 首末 RAW 跨度 | 4.950080 s | 59.950072 s |
| 采样期限漏过 | 0 | 0 |
| 最大 RAW 夹取宽度 | 608 ns | 832 ns |
| 最大采样间隔 | 50.208592 ms | 50.274352 ms |
| MONOTONIC−RAW 变化 | +3.511665 ms | **+30.364507 ms** |
| 全局速率差 | +709.359196 ppm | +501.658477 ppm |
| 最大仿射非线性残差 | 0.017523 ms | **1.691781 ms** |
| REALTIME−MONOTONIC 首末变化 | 96 ns | 193 ns |
| 诊断判定 | CLOCK_DIAGNOSTIC_PASS（仅短窗口） | **CLOCK_DIAGNOSTIC_FAIL**（非线性/速率变化） |

60 秒基线中，5 秒分段速率从 +668.483 ppm 降至 +381.666 ppm；内核 offset 从 +32.441132 ms 降至 +12.610448 ms，freq 保持不变。安装的内核头文件 `include/linux/timex.h` 给出 SHIFT_PLL=2；利用 constant=4 和每秒状态作 PLL 相位项加频率项的近似计算，与实测分段速率相差约 1.5～8.1 ppm，明显支持正常 PLL 消化相位偏差的解释。这不是内核故障结论，也不能追溯为某个未经记录的 NTP 包。

![60 秒主机时钟基线](/home/jetson/clock_diag/runs/audit_20261016_200849/clock_baseline.png)

复算用户 19:36 的旧独立测试得到 +1.404970 ms、约 +23.597928 ppm，和此前观察一致；与本轮约 20:09 的测试不矛盾，说明时钟状态在不同时间段发生变化。本次没有复现历史 **309 ms 幅度**；实际直接复现的是较小的 **30.365 ms 非线性主机相对 RAW 变化**，不能声明历史问题永久修复。

CLOCK_DIAGNOSTIC_FAIL 表示当前记录不能被当作稳定单一仿射时钟关系验收；并非宣称正常系统时间校准是故障。检测门限已保存在每份 analysis.json 的 policy 中，不影响原视频或 L2-B 门限。未关闭、重启或重配时间同步服务。

**固定速率比例差的单独核查**

| 历史会话 | ZED 标称秒 / MID 秒 | MID/主机 RMS | ZED/主机 RMS |
|---|---:|---:|---:|
| 20261015_192716 | 1.012549881 | 0.082601 ms | 0.304851 ms |
| 20261015_201642 | 1.012737311 | 0.098637 ms | 0.302358 ms |
| 20261016_143401 | 1.012638883 | 共同窗口 32.724646 ms | 共同窗口 33.144160 ms |

前两次不存在同等幅度的共同非线性曲率，但约 1.25%～1.27% 的比例差已经存在，说明不能把它与历史 309 ms 曲率混为一谈。最新会话反向比例 MID/ZED 为 0.987518865，相差约 −1.248114%；方向不同，百分比也不完全相同。

逐条核对 12072 个 HID 报告的 `<Q` 字段（字节偏移 2），全部与保存的 device_ticks 一致。导出 bag 的 12072 条 ZED IMU header 全部等于 `floor(ticks * 78125 / 2)`，无错误。该 39062.5 ns/tick 是现有 Open Capture 的标称 TS_SCALE，原工程采用精确整数换算；原始回调在上游浮点重基准及自适应 scaling 前执行，没有继承其主机漂移修正。参见 [官方 Open Capture sensorcapture 源码](https://raw.githubusercontent.com/stereolabs/zed-open-capture/master/src/sensorcapture.cpp)。

按 MID 为参照拟合得到约 38574.956 ns/tick，仅是数据关系估计，不是新的合法换算常数，未应用到数据或代码。现有证据降低了字节解析、整数换算和 ROS header 实现错误的可能性；仍不能区分 ZED 标称 tick 与实际硬件时间基准、STM32 PPS 实际周期或设备同步调整的贡献，不能直接称为晶振漂移。

**根因假设分级**

| 假设 | 本轮分级与证据边界 |
|---|---|
| H1 主机时钟调速 | 当前 MONOTONIC/RAW 非线性差异 **VERIFIED**；正常内核 PLL 解释 **SUPPORTED_HYPOTHESIS**；它解释历史 309 ms 的归因仍为 **SUPPORTED_HYPOTHESIS**，不是已证实历史 NTP 事件 |
| H2 Linux 时钟源或转换异常 | clocksource 与接口语义 **VERIFIED**；硬件计数器/内核故障 **UNRESOLVED**，目前无肯定证据，当前表现可由正常 PLL 解释 |
| H3 Livox 时间动态调整 | 已保存诊断 type=2；设备相对主机弯曲 **VERIFIED**，独立设备时间异常 **UNRESOLVED / PENDING_HARDWARE** |
| H4 SDK 回调关联 | 源码携带同包 host 时间 **VERIFIED**；接收延迟对拟合的贡献 **UNRESOLVED**，0.265 ms 不能排除全部关联误差 |
| H5 ZED tick 比例/语义 | 解析与标称换算 **VERIFIED**，跨会话固定比例差 **VERIFIED**；其硬件来源 **UNRESOLVED / PENDING_HARDWARE** |
| H6 STM32 虚拟 GPS | 缺少原始 GPRMC/PPS 波形证据，**UNRESOLVED / PENDING_HARDWARE**，固件与同步链路未改 |

没有复现或定位新的采集程序软件缺陷，因此本轮没有修改采集核心。新增诊断会在时钟证据不足或非线性超限时拒绝给出稳定时钟结论；L2-B 继续 PENDING，没有放宽 max_device_ppm 或 device_residual_limit_ns。

**新增程序、测试及保护**

新增文件位于 `/home/jetson/clock_diag`：`clock_monitor.cpp`、编译输出 `clock_monitor`、`build.sh`、`analyze.py`、`joint_test.py`、`run_joint_test.sh`、`test_diag.py`、`README.md`，以及独立 runs 证据目录。本工作空间只新增本报告；已有采集源码、配置、二进制和软件清单均与原哈希一致。未修改 `/home/jetson/catkin_ws`。

监测器以 `g++ -std=c++14 -O2 -Wall -Wextra -Werror` 编译通过；`ldd -r` 无缺库/缺符号。12 项软件测试通过：正常 23 ppm、MONOTONIC 偏差步变、REALTIME 步变、持续非线性、数据缺失、夹取过宽、读取异常、跨 boot/覆盖不足拒绝桥接、慢 bag 检查下的监测生命周期、无 summary 失败后监测、运行与完整性分级、SIGTERM 正常落盘和拒绝覆盖。合成数据明确为 SYNTHETIC，实际主机读取冒烟测试不代表传感器验证。

所有原受保护环境比对通过：4495 项文件状态、848 个文件 SHA256、276 个动态库 SHA256；软件包清单、原 Git HEAD/status、BLAS/LAPACK 均不变。历史采集 sidecar SHA256/mtime/size 不变，原 bag size/mtime 不变且未以写模式打开。没有清理、删除历史数据、安装依赖、修改网络/时区/RTC/NTP，未 commit/push。

**一键流程和本轮硬件阻塞**

只需开启 **MID-360 和 STM32 同步板**，保持 **ZED 2i 正常连接**，然后在普通 jetson 用户 SSH 终端执行一条命令：

```bash
/home/jetson/clock_diag/run_joint_test.sh
```

它内部保持原命令 `/home/jetson/zed_capture_ws/scripts/start_capture.sh --duration 30`，不改变 1080P30、原始图像、CustomMsg、双 IMU 或时间戳。动态匹配 VID=2b03、视频 PID=f880、HID PID=f881 和现有序列号，不硬编码某次 USB devnum，不需要 root。

先监测 15 秒，再进行一次采集；识别实际采集 summary，之后继续至少 15 秒，等待原管理器及完整性检查结束。失败不自动重录。Ctrl+C 会请求自身启动的管理器正常退出，保留日志和监测前缀。SIGKILL/断电无法保证最后约 1 秒用户态缓冲落盘；缺少监测 summary 视为未完整结束。

当前预检在 `/home/jetson/clock_diag/runs/joint_20261016_201626_71faeb6f`：sysfs 能看到 ZED 视频 USB3 5000 Mbit/s 和 HID 12 Mbit/s，但设备节点不可访问，AF_INET 返回 EPERM。准确标记为沙箱限制，没有作为硬件故障，没有尝试绕过限制；当前授权接口不允许 shell 沙箱提权。MID 连接测试未执行，避免在已知断电时重复尝试。

**本轮尚无新的采集 session、bag 路径或 bag 大小**。上面 7.42 GB 是历史 bag，不能冒称本轮交付。新测试目录将输出 `TEST_DIR=...`，新传感器会话仍保存在 `/home/jetson/zed_capture_data/`，关联写入 test_result.json。

真实测试将自动保存三时钟 CSV、内核调整 CSV、服务前后快照、采集终端日志、监测日志、关联会话和软件哈希，并分别报告：

| 验收项 | 本轮当前状态 |
|---|---|
| 新联合 CAPTURE_RUNTIME | HARDWARE_PENDING |
| 新联合 DATA_INTEGRITY | HARDWARE_PENDING；原历史仍 FAIL |
| 新联合 CLOCK_DIAGNOSTIC | INCONCLUSIVE，尚无同步采集数据；无设备 60 秒基线为 FAIL |
| L2B_MAPPING | PENDING |
| PHYSICAL_SYNC | PENDING |

联合诊断对同一次会话比较设备/MONOTONIC 与 MONOTONIC/RAW；受减法方向影响，共同设备曲率应与负的主机去趋势曲率比较。只有同 boot、覆盖完整、20 Hz 样本顺序和夹取/间隔合格时才提供诊断 RAW 插值；它不是逐帧直接 RAW 测量，插值误差和物理同步未验证，不改写数据。

**120 秒与后续 L2-B 条件**

当前不具备按原严格门槛进入 120 秒测试的条件：历史图像序号缺失、锚点历史不完整尚未通过，新 30 秒 RAW 联合证据未取得。没有修改原长期采集门槛。可以继续离线研究 L2-B、输入质量拒绝及桥接误差，但不能把现有 542 对软件通过或候选锚点覆盖等同于映射/物理同步整体通过。

主要错误与警告：历史 11 次视频长间隔、22 个缺失驱动序号、1 次 ZED IMU 长间隔、429 个锚点更新漏读；当前基线显著但可由正常 PLL 解释的时钟调速；历史未记录 RAW；服务查询和硬件访问被沙箱阻止；固定设备速率比例来源未解。

**诊断产物与回退**

总证据目录：[audit_20261016_200849](/home/jetson/clock_diag/runs/audit_20261016_200849)。包含 `environment_audit.json`、`clock_system_files.json`、`basic_5s/`、`baseline_60s/`、`historical_device_analysis_final.json`、`historical_ratio_crosscheck.json`、`historical_tick_header_check.json`、`historical_livox_diagnostics.json`、`kernel_pll_comparison.json`、`prior_1936_clock_analysis.json`、软件测试日志、动态依赖和保护检查。图为同目录 `clock_baseline.png`。

新一键实测会在其独立目录生成 `diagnostic_report.md` 和 `test_result.json`，保留五类分开验收的结论及新 session/bag 字节数。本文记录当前阶段，不用尚未发生的实测结果填充报告。

回退只需停止使用 `/home/jetson/clock_diag/run_joint_test.sh`，继续使用原采集命令；新增诊断程序和证据可保留，不需要恢复或删除系统文件。原采集程序和依赖未改，无需回滚其二进制。后续仍需保存 RAW 联合证据才能缩小历史根因，不能声称已经永久消除异常。
