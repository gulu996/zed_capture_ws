# ZED USB / UVC / V4L2 专项审计及低负载对照结果

2026-10-17。对照 A：`/home/jetson/zed_capture_data/20261017_144432_c0112f6c`。
独立工具与证据：`/home/jetson/zed_capture_ws/diagnostics/zed_v4l2_probe`。

**更新：用户已完成唯一一次低负载 B 实测 `probe_20261017_152106_349a1c1e`。原始事件独立复核确认 LOW_LOAD_RUNTIME_PASS、LOW_LOAD_OBSERVED_CONTINUITY_PASS：898 帧，零长间隔、零序号缺口。正式节点、参数、静态库、原工作空间、三时钟算法、IMU 分段和历史输入均未修改。未新增采集或提交 Git。**

完整 B 复核及根因边界见 [低负载 A/B 实测复核](zed_v4l2_low_load_ab_review_20261017_152106.md)。本报告原准备阶段版本完整保存在 `diagnostics/zed_v4l2_probe/evidence/review_20261017_152106/root_cause_analysis_before_B_review.md`；下文原离线审计结论保留，实测状态和第 11 节已更新。

## 1. 结论与当前根因范围

| 判断 | 分类 | 依据与边界 |
|---|---|---|
| 视频实际 SuperSpeed 5000 Mb/s | VERIFIED | sysfs、lsusb -t、历史 session 三者相符；不是根据 HID 速率猜测 |
| 视频经过 USB Hub，当前同一 SuperSpeed Hub 下未见其他已枚举下游设备 | VERIFIED | 2-1 为 0bda:0489 四口 Hub，视频为 2-1.3；物理 Hub 在板载还是外置盒内，sysfs 无法确定 |
| 8 次异常主要耗时在 select 进入之后、DQBUF 之前 | VERIFIED | QBUF→select 3.968～6.752 µs，select 等待 61.502～65.107 ms，DQBUF ioctl 15.455～20.542 µs |
| 用户态图像回调长时间占住一个 buffer 导致本次 8 次异常 | 缺少支持，UNRESOLVED | 前帧回调 1.737～5.464 ms，随后及时 QBUF；不等于已经排除所有调度或内核负载影响 |
| UVC 内部丢弃不完整帧，并伴随旧 FID/EOF 路径重复计数 | SUPPORTED_HYPOTHESIS | 上游 5.10 有可解释 delta=3/约两个周期的路径；本机 nodrop=0；缺少原始 UVC header、内部 buffer/URB 跟踪和精确 BSP 源码匹配，尚不能确认为本机实际分支 |
| USB物理链路、相机内部停顿或内核复制/交付延迟 | UNRESOLVED | 用户态完整帧日志不能看到未交付 payload，也没有 USB 物理包计数 |
| 高负载录包是原因 | UNRESOLVED | 仍是合理的间接负载假设；不是已证实原因。本轮 A 无明显长时间用户态处理阻塞，B 用来检验高吞吐录包是否为必要条件 |
| 需要修改正式采集节点 | 当前没有依据 | 未找到可复现、能解释这 8 次异常的正式节点软件缺陷；保持原路径 |

最可靠的定位是：**异常发生在下一完整视频缓冲可被用户态取到之前。** “select 等待”同时包含等待就绪与唤醒后获得调度的时间，不能等同于 CPU 调度延迟。当前最值得验证的机制是 UVC 帧完成/完整性处理及其上游交付；触发因素仍可能来自相机、USB、内核处理或整体负载，不能指定唯一责任层。

## 2. 实际 USB 拓扑

```text
3610000.xhci  tegra-xusb / xhci-hcd
├─ usb2  10000 Mb/s root hub
│  └─ 2-1  0bda:0489  Generic 4-Port USB 3.0 Hub  10000 Mb/s
│     └─ 2-1.3  2b03:f880 ZED 2i  5000 Mb/s
│        ├─ :1.0 uvcvideo 控制接口，Interrupt IN 0x86
│        └─ :1.1 uvcvideo 视频接口，Bulk IN 0x81，wMaxPacketSize=1024
└─ usb1  480 Mb/s root hub（同一 xHCI 控制器）
   ├─ 1-2  0bda:5489  Generic 4-Port USB 2.0 Hub  480 Mb/s
   │  └─ 1-2.3  0424:2512 二口 Hub  480 Mb/s
   │     └─ 1-2.3.2  2b03:f881 ZED-2i HID  12 Mb/s，serial=38003368
   └─ 1-3  13d3:3549 Bluetooth，12 Mb/s
```

**VERIFIED**：视频与 HID 处于不同速率分支，共享控制器；蓝牙在 USB2 根分支另一端口。不能把 HID 的 12 Mb/s 当作视频 USB2 降速，也不能把“共享控制器”直接说成“视频被其他设备抢满带宽”。目前视频 SuperSpeed Hub 仅见 ZED，下游占用、物理线缆布局及 Hub 供电质量仍有观察边界。

本次空闲审计中视频和 SuperSpeed Hub 的 `power/runtime_status=suspended`、`power/control=auto`；这是空闲快照，不证明录制期间发生自动挂起。本轮未改变 autosuspend。

sysfs 原始描述符已保存：`zed_video_descriptors.bin` / `frame_descriptors.json`。3840×1080 uncompressed frame 描述符给出 8,294,400 B，间隔列表 333333 / 666666（100 ns 单位，即约 30 / 15 FPS）。30 FPS 格式在设备描述符中存在。名义图像负载为 248,832,000 B/s；5 Gb/s 是链路协商速率，不是可直接与图像字节数等同的有效吞吐保证。端点为 **Bulk**，没有把它套用成 isochronous 预留带宽问题。

## 3. 内核与权限审计

运行内核：`5.10.216-tegra`，构建日期 2025-03-04；L4T R35.6.1。模块 `/lib/modules/5.10.216-tegra/kernel/drivers/media/usb/uvc/uvcvideo.ko`，version 1.1.1，srcversion `52FC29DD6DE2D33C6F7544E`；哈希与参数保存在 `source_audit.json` / `usb_sysfs.json`。

当前参数只读结果：`clock=CLOCK_MONOTONIC`，`hwtimestamps=0`，`nodrop=0`，`trace=0`，`quirks=4294967295`，控制请求 timeout=5000 ms。这里的 5000 ms 不是用户态 select 的 100 ms。

`journalctl -k -b` 可读取，已保存完整当前 boot 日志。**VERIFIED（日志范围内）**：未找到 ZED 重复 USB reset、disconnect、新 USB 地址重新枚举、UVC 带宽协商失败或 USB/UVC 传输错误日志。只有启动时一次 ZED 视频/USB HID 枚举；后续 `hid-generic` 在关闭采集附近重新绑定，已有 HIDAPI 关闭路径会重新 attach kernel driver，因此不能仅凭该行断言设备重新枚举。没有打开 trace，缺少正常未打印的 URB/payload 错误证据；“无日志”不等于“无底层丢失”。

内核另有 **14:25:36 的 Python OOM**，与上一轮离线辅助核验一致，早于本次 14:44 联合采集约 19 分钟。不能把它冒充本次视频异常时的 OOM；本轮没有再读取大 bag 内容，所有摘要分析只读 sidecar，哈希使用有界分块。

工具限制：`v4l2-ctl` 未安装，未安装任何软件包；普通 `lsusb` 报 libusb 初始化 -99，`lsusb -t` 和 sysfs 成功。`dmesg` 被拒绝 EPERM，未提升权限或改权限；已有 journal 足以做上述有限日志审计。当前沙箱隐藏/禁止访问 `/dev/video*`，因此未执行设备 ioctl 实机查询。独立探针将在普通终端只读保存 QUERYCAP/G_FMT/G_PARM/G_CTRL 结果，不以缺少 v4l2-ctl 为由安装依赖。

## 4. V4L2 / UVC sequence 和时间戳语义

V4L2 sequence 是驱动计数，不是已认证的相机物理曝光编号；规范允许包含驱动观察到但未保存的帧，也不保证包含设备内部尚未传输的丢帧。timestamp 的来源由驱动及 flags 决定。[Linux 5.10 V4L2 buffer 文档](https://www.kernel.org/doc/html/v5.10/userspace-api/media/v4l/buffer.html)

上游 5.10 `uvc_video_decode_start()` 在 FID 改变时先增加 sequence。如果旧帧未以 EOF 正常结束，仍有 payload，则可标记旧帧完成并返回内部 `-EAGAIN`；此时 last_fid 尚未更新，Bulk 解码循环会为同一 payload 换 buffer 重试，可能再次计数。**这里的内部 EAGAIN 不是用户 ioctl(DQBUF) 的 EAGAIN，后者为 0 不会排除此路径。** [上游 v5.10 uvc_video.c](https://raw.githubusercontent.com/torvalds/linux/v5.10/drivers/media/usb/uvc/uvc_video.c)

不完整的未压缩帧可被标为 error；在丢弃损坏帧策略下，buffer 可在内核重新排队而不交付用户态。因此已返回帧的 bytesused 正常、V4L2_BUF_FLAG_ERROR=0，并不能证明中间没有内部损坏帧。[上游 v5.10 uvc_queue.c](https://raw.githubusercontent.com/torvalds/linux/v5.10/drivers/media/usb/uvc/uvc_queue.c)

一个 **SYNTHETIC 解释模型**：完整 A 的 sequence=0；部分 B 使计数到 1；C 的帧边界在旧 B buffer 上使计数到 2，随后换 buffer 重试使计数到 3；若 B 被内部丢弃，用户可能看到 A→C 间隔约两个周期、sequence_delta=3。单元测试仅验证这个抽象分支顺序可以产生这种现象，不是 USB 包回放、不是本机驱动分支命中证明，也不能据此把缺失曝光数定为 1。

**UNRESOLVED（版本匹配边界）**：本机只安装 headers，未包含完整 uvc_video.c。精确 5.10.216 / NVIDIA r35.6.1 源码链接未能取得，模块中也没有可直接定位的 `uvc_video_decode_start` 本地符号；已保存符号/反汇编尝试，但未据此伪称确认该二进制与上游完全一致。上游机制是有源码依据的假设，仍需精确 BSP 源码和内部事件才能确认。本轮不打补丁、不换模块。

本机成功帧 flags 全为 73729（MONOTONIC、SOE 标志），hwtimestamps 当前为 0。结合上游实现，V4L2 时间应按**驱动提供的原始主机时钟域观测**使用，不能直接称为相机固件原始 tick 或曝光中心。本轮完整保留 timestamp 和 flags，不改 L2-B 入口或换算。

NVIDIA R35.6.1 发布说明也列有相机高 CPU / 掉帧性能线索（issue 200765445）。这不是本次原因的证明，适用性仍 UNRESOLVED；本轮没有照其建议回退内核补丁。[NVIDIA 官方发布说明，第 10 个 PDF 页面](https://docs.nvidia.com/jetson/archives/r35.6.1/ReleaseNotes/Jetson_Linux_Release_Notes_r35.6.1.pdf)

## 5. 正式采集源码生命周期

**VERIFIED（源码）**：O_NONBLOCK 打开 → S_FMT / S_PARM → REQBUFS=4 → QUERYBUF / MMAP → 初始全部 QBUF → STREAMON → 现有视频线程 select / DQBUF / 同步回调 / QBUF；退出先停止并 join 视频线程，再 STREAMOFF / munmap / close。每次 select 重建 fd_set 和 100 ms timeval。EAGAIN/EINTR 重试，其余 I/O 错误终止；没有隐式主动跳过正常帧的应用策略。

正式回调持有的图像像素在 QBUF 前复制完毕，writer 处理复制后的消息，未引用已经归还的 MMAP 像素。writer 执行任务时不持有 producer 队列锁。4 个 buffer 的实际返回值由历史 `device_settings.txt` 确认。

初始化中存在可进一步加固的边界：calloc/mmap 的失败检查不全面，S_PARM 失败仅记录日志。这不是本次复现的错误；891 个完整缓冲、实际 4 buffer 与持续采集不支持把它归因为这 8 次周期缺口。本轮不改正式程序。探针额外只读核验实际格式、帧率、buffer 数量，拒绝不匹配，不自动降级。

## 6. 八次异常逐事件时间轴

完整原始边界存于 `evidence/baseline_A.json` 的 `events[].previous_event/current_event` 和 `previous_video/current_video`：包含前帧 DQBUF→回调→QBUF、下一次 select→DQBUF 的所有 MONOTONIC 纳秒值。下表是便于比较的派生量；接收墙钟仅用于定位日志，不作曝光时间。

| pair | 接收时间 | sequence | 原始间隔 ms | QBUF→select µs | 迭代空白 µs | select 等待 ms | select→DQ前 µs | DQ锁等待 µs | DQ ioctl µs | 本帧回调 wall / CPU ms |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 23 | 14:44:40.605248 | 21→24 | 66.871 | 5.664 | 5.600 | 64.944 | 0.096 | 0.576 | 17.151 | 1.819 / 1.809 |
| 32 | 14:44:40.939710 | 32→35 | 66.866 | 6.559 | 6.207 | 64.266 | 0.128 | 0.480 | 16.894 | 2.479 / 2.109 |
| 96 | 14:44:43.113801 | 98→101 | 66.876 | 4.544 | 4.288 | 65.107 | 0.128 | 0.544 | 17.983 | 2.148 / 2.131 |
| 98 | 14:44:43.214171 | 102→105 | 66.870 | 6.752 | 6.656 | 64.809 | 0.096 | 0.672 | 20.542 | 2.154 / 2.140 |
| 206 | 14:44:46.859878 | 212→215 | 66.880 | 5.824 | 5.664 | 64.565 | 0.096 | 0.512 | 15.455 | 1.792 / 1.784 |
| 361 | 14:44:52.077620 | 369→372 | 66.864 | 5.280 | 5.152 | 64.673 | 0.128 | 0.576 | 19.070 | 2.247 / 2.212 |
| 561 | 14:44:58.800467 | 571→574 | 66.870 | 5.823 | 5.727 | 64.606 | 0.160 | 0.352 | 18.303 | 2.268 / 2.221 |
| 872 | 14:45:09.236082 | 884→887 | 66.874 | 3.968 | 3.840 | 61.502 | 0.128 | 0.512 | 16.095 | 6.082 / 6.050 |

前帧回调 wall/CPU、本帧 QBUF ioctl 和 writer 时间另存 `eight_event_timing.csv`，没有隐藏前帧处理。8 个区间都没有中间失败循环：select timeout=0、DQBUF EAGAIN=0、DQBUF fatal=0、QBUF error=0。全段 893 循环、891 帧，唯一 2 次 select timeout 均在首帧之前；返回帧 bytesused 全为 8,294,400、invalid_video_buffers=0。

全段 890 个帧间隔：882 正常 sequence 递增、8 次 delta=3、无 duplicate/reset。总缺失驱动编号 16；时间上每次约多一个 30 Hz 周期，但无法从这里计算真实曝光丢失数量。891 对左右目一致仍沿用已有完整 bag 检查结果，本轮不重读 7.53 GB bag。

## 7. 负载证据与因果边界

A 的 bag 为 7,525,436,291 B。视频跨度 30.035481 s，平均 29.631621 Hz；中位间隔 33.493 ms，P95 33.508 ms，P99 33.581110 ms，最大 66.880 ms。

writer 队列峰值 17,049,927 B / 256 MiB，溢出 0；最长图像 writer 任务 57.560774 ms，最大排队等待 24.813316 ms。事件 872 附近有 40.287130 ms 的 writer 任务，但其他异常也出现在附近 writer 仅 12～17 ms 的窗口内。时间相关不能证明磁盘因果。

1 Hz 级资源摘要：子进程峰值 CPU 86.82%（一个核=100%）、系统峰值 37.99%、子进程 RSS 峰值 259.62 MB、Dirty 峰值 586.38 MiB、块写入峰值约 253.95 MB/s。整段 bag 增长均值 226.68 MB/s 包含启动/收尾窗口，不能与有效视频载荷约 248.83 MB/s 混为同一口径。8 个事件资源窗口约 1.03～1.05 s；这些均值无法排除 10～100 ms 级抢占、内存回收或 I/O 突发。视频循环累计 CPU / 壁钟估计为 6.104% 单核，未覆盖统计回调本身和循环间隙，不能据此声称无调度延迟。

三时钟 A：1369 样本，无漏期限、最大 RAW bracket 7.392 µs，CLOCK_DIAGNOSTIC_PASS。时钟写线程最长 fsync 121.153216 ms；按已有三时钟样本插值得到的 MONOTONIC 区间与这 8 个视频缺口均未重合，见 `clock_writer_overlap.json`。该结论只针对记录的时钟 writer fsync；NVMe 后台写回、内核复制与 writer 任务不是同一个事件。正式 bag 的显式 fsync 位于关闭后，也不能用它解释录制中每次 gap。

ZED HID 的低层日志继续保留：队列丢弃 0、峰值 1、已记录传输/读取错误 0；但首两条设备时间相差约 16.463 s，分段判定首条 INVALID_SUSPECT，余 12191 条属于段 2。**ZED_IMU_TIME_VALIDITY_FAIL 仍保留**。419 个锚点漏读和约 1.275% 时钟比例问题均未在本轮修改或重新映射。

## 8. 独立低负载探针

路径：`/home/jetson/zed_capture_ws/diagnostics/zed_v4l2_probe`。文件：`probe.cpp`、`build.sh`、`run.py`、`run_probe.sh`、`analyze.py`、`test_probe.py`、`README.md`，输出只在其 `build/`、`runs/`、`evidence/` 下。本报告是唯一新增到工作空间根目录的交付文件。

探针**直接链接现有未修改的 libcapture_oc.a**，复用其初始化、同一 grabThreadFunc、select/DQBUF/QBUF 和关闭路径；不是另写一套视频循环。所有 producer 逻辑和库的 SHA 可追溯。实际不使用 HID/SensorCapture，链接器剔除未使用 HID/libusb 依赖，动态依赖仅为 C/C++ 基础库，无 ROS/CUDA/ZED SDK。

| 项目 | A 正式联合采集 | B 低负载探针 |
|---|---|---|
| USB 数据流 / 内核 UVC | 3840×1080 YUYV 30 FPS | 相同；仍保留完整 USB 带宽与内核搬运负载 |
| MMAP / select | 4 buffer / 100 ms | 相同；实际值必须核验 |
| 用户态图像操作 | 拆分/复制左右目、ROS消息、bag | 仅复制元数据结构，不读取/复制像素 |
| HID / ROS / 雷达 | 联合采集 | 不启动；已有 Livox 如仍运行则保留并记录背景负载 |
| 存储 | 大型无压缩 bag | 录制循环内不写文件，停止后仅写轻量 CSV/JSON |
| 线程 | 正式多数据流/写线程 | 库原有视频线程 + 主线程，不增加 writer/实时线程 |
| 控制 | 保留自动曝光等 | 使用同一初始化；无曝光/旋转/裁剪控制修改，LED启闭沿用库行为 |

元数据缓冲固定 4096 条、983040 B，预先分配；包含 event_id、原始 timestamp/sequence/flags、buffer index/bytesused/长度、select 和 ioctl 边界/结果/errno、成功帧间隔、线程 CPU 等。不会存大型 YUYV、不 fsync 每帧、不打印逐帧日志。容量耗尽明确失败，不覆盖旧事件、不默默丢弃记录。常规完成/SIGINT/SIGTERM 先 join 采集再落盘；SIGKILL 或断电会丢失内存中未落盘的元数据，不能宣称此时完整。

持续时间从首帧到达开始约 30 s，首帧最多等待 10 s，停流 3 s 保护；不更改正式超时。新唯一目录先保存 preflight/session，输出均拒绝覆盖。启动检查按 VID/PID/index 匹配当前 video node，拒绝可见的现有采集/录包进程及任何视频 FD 占用，不杀进程。两个探针用 advisory lock 互斥；其他用户不可读 FD 表及检查后的竞争窗口仍以驱动 EBUSY 所有权检查为最终边界，不以 root 绕过。请勿在测试期间另外启动正式录制。

B 会同步记录可用的标准 V4L2 控制查询值；不支持的控制保留 errno，不伪造曝光值。自动曝光未冻结，因此两次测试照明/场景也应尽量保持，不能把 B 视为只移除磁盘写入这一个变量。

## 9. 编译、无设备测试及保护

**VERIFIED / SOFTWARE_TESTED**：独立 g++ 编译成功，不调用 catkin_make，不改正式二进制。两个 C++ 测试入口通过：探针 collector 的无像素解引用、有界溢出、原始字段保留，以及现有正式循环的模拟 select/ioctl 超时/EINTR/EAGAIN/QBUF 错误测试。11 项 Python 测试通过，含真实 A sidecar 回归、占用拒绝、序号 wrap/reset/gap 区分、运行失败不能判 PASS、诊断程序不要求未链接 HID 库，以及明确标为 SYNTHETIC 的旧 FID 顺序解释模型。

`ldd -r` 无缺失库/符号。初次预检错误复用了正式节点必须存在 libusb 的检查，误报视频探针未链接 libusb；已仅在独立 wrapper 内修正并回归，旧日志保留。不把这个辅助检查错误写成 USB 硬件故障。

保护检查：89 条路径的 size/mtime、其中 88 个 SHA 均不变，包括正式源代码、静态库、可执行文件、三时钟代码、历史 sidecar；旧 bag 只核对 size/mtime，不宣称前后完整 hash。catkin Git status、已装软件包版本仍与原保护基线一致。没有 commit/push、清理、系统安装或权限修改。证据：`protection_after.json`。

## 10. 普通 SSH 终端的一条命令

**VERIFIED：实测已完成，不要求再次运行。** 原准备阶段只有一次非流式预检 `runs/probe_20261017_151133_f8928316`，因沙箱限制没有 STREAMON；随后用户在普通 SSH 终端执行了下面的命令，产生 `runs/probe_20261017_152106_349a1c1e`。该次真实 B 已复核通过。以下命令保留作复现说明，不是本轮再次采集的要求。

保持 ZED 原连接、场景和照明，确认正式采集已自然结束，在普通 jetson 用户终端执行一次：

```bash
/home/jetson/zed_capture_ws/diagnostics/zed_v4l2_probe/run_probe.sh
```

不需要启动 MID-360/STM32，不需要 sudo，不需要手动协调后台进程。若检测到占用，脚本拒绝启动；不要为通过测试强杀当前业务。若设备权限不足，保留 preflight 输出另行处理，不运行 chmod/udev 修改。

脚本输出唯一 `PROBE_DIR`。结果查看该目录 `result.json` 和 `comparison.json`；它自动与 A 的已固化统计对比。返回码 0 仅代表运行完整，若仍有 gap，`observed_continuity` 继续 FAIL。同次测试原始 `video_io_events.csv`、`probe.log`、`probe_end.json`、V4L2前后查询、USB/系统前后状态均保留。Ctrl-C 可正常终止并保存已经收集的记录；中断不能计作完成 30 秒。

## 11. A/B 验收与后续决策

| 指标 | A 已有实测 | B |
|---|---:|---|
| 帧数 | 891 | 898 |
| 视频时间跨度 | 30.035481 s | 30.002547 s |
| 平均 FPS | 29.631621 | 29.897462 |
| 中位/P95/P99 ms | 33.493 / 33.508 / 33.581110 | 33.497 / 33.500 / 33.505 |
| 最大间隔 / 长间隔数 | 66.880 ms / 8 | 33.570 ms / 0 |
| 缺失驱动编号 | 16 | 0 |
| select timeout | 2，均首帧之前 | 2，均首帧之前 |
| DQBUF EAGAIN / 其他错误 / QBUF错误 | 0 / 0 / 0 | 0 / 0 / 0 |
| 视频循环 CPU 估计 | 6.104% 单核（有限口径） | 0.224% 单核（相同口径） |

**VERIFIED**：B 为相同 3840×1080 YUYV、1/30 s 请求、4 个实际缓冲、5000 Mb/s USB3，复用未修改的采集循环；900 条事件完整、898 帧返回元数据正常。B 的 30.667 s 系统快照窗口内 NVMe 总写入仅增加 757,760 B，USB 拓扑与内核日志事件正文前后不变。曝光控制查询部分不支持，场景与自动曝光未严格控制。没有保存像素，不能据此验收像素内容或联合数据集。

**SUPPORTED_HYPOTHESIS**：整体负载或并发路径相关因素值得优先排查；**UNRESOLVED**：不能隔离出磁盘唯一因果，也不能排除负载敏感的 USB/UVC 或设备行为。正式 A 的 DATA_INTEGRITY_FAIL、IMU 启动异常和锚点漏读继续保留。当前没有修改正式节点的已证实依据。

- 若 B 仍出现约 66.9 ms / delta=3：在没有其他并发录包的前提下，说明高吞吐 rosbag **不是出现该现象的必要条件**；仍不能仅凭一次测试锁定固件或 UVC。
- 若 B 改善：仅说明总负载或回调路径变化后改善，不证明磁盘唯一因果，也不能宣称永久修复。
- 如需进一步控制变量，下一轮可分别保留相同图像复制、恢复 HID/雷达并发、最后恢复写盘来区分因素；本轮没有实现或自动运行这些实验。
- 若异常在 B 持续，应优先取得精确 BSP 源码、可用 UVC 元数据或经单独批准的有限内核跟踪，核实 EOF/FID、buffer error/requeue 与 URB 完成；原始用户态元数据不足时继续 UNRESOLVED。不得通过改 nodrop、重置 USB、换内核或降低 FPS 来伪造 PASS。

回退：停止使用本独立诊断目录即可。正式程序没有替换，无需恢复系统、删文件或清理工作空间。
