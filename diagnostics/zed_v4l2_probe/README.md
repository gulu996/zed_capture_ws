# ZED V4L2 低负载对照探针

只复用正式 Open Capture 静态库的视频采集路径，独立可执行程序。
3840×1080 YUYV、30 FPS、4 MMAP 缓冲、100 ms select；无 ROS/HID、无像素复制、无 rosbag。
不修改正式程序、曝光控制、USB 权限或系统配置。

新增可选原生 `HD720`：2560×720 双目拼接 YUYV（单目 1280×720），30 FPS、4 MMAP。
默认仍为 HD1080。没有 OpenCV 缩放、JPEG、裁剪或像素格式转换；复用未修改的正式静态库。
720P 只进行一次 30 秒低负载实测：

```bash
/home/jetson/zed_capture_ws/diagnostics/zed_v4l2_probe/run_probe.sh --resolution HD720
```

先记录所有 capture 格式、所有 YUYV 尺寸及所选 YUYV 尺寸的帧间隔枚举。
720P 必须出现在实际设备离散枚举中；权限失败、不支持枚举或仅有尚未验证的连续范围都会拒绝，不回退到 1080P。
使用 `RESOLUTION::HD720` 直接请求相机；随后 G_FMT/G_PARM 回读核对 YUYV、2560×720、stride=5120、sizeimage=3686400、30 FPS 和实际 4 缓冲。
ENUM 的 333333×100 ns 表示约 30 FPS，枚举匹配保留 100 ns 量化；实际 G_PARM 仍要求分母=30×分子，不改变帧间隔验收门限。
退出后再次保存设置。初始 `v4l2_before.json` 可能还是之前的 1080P，这不代表此次 720P 协商失败；以 `v4l2_negotiated.json` 为设置后的证据。
运行期间设备输出变为原生 720P；不改正式配置，之后正式节点初始化仍按它自身配置设置模式。

720P 结果新增 `NATIVE_720P_SUPPORTED`、`LOW_LOAD_720P_RUNTIME`、`LOW_LOAD_720P_CONTINUITY`、`FORMAL_CAPTURE_UNCHANGED`、`JPEG_REALTIME_PENDING`。
`zed_native_720p_validation.md` 自动保存在新测试目录；不能用历史 1080P A 把跨分辨率差异归因为单一负载变化。
本工具未采集双 IMU/雷达、未检查像素内容，也不验证物理同步。720P 内参需重新核对，不能复用未验证的 1080P 标定。

普通 jetson SSH 终端执行**一次**：

```bash
/home/jetson/zed_capture_ws/diagnostics/zed_v4l2_probe/run_probe.sh
```

ZED 保持原 USB 连接、场景和照明。不要同时启动正式录制。
探针不需要启动 MID-360 或 STM32；若已有 Livox 进程，工具保留它并记录背景负载。
发现已运行的采集/录包进程或可见的视频 FD 占用会拒绝启动，不杀进程。
权限受限的其他用户 FD 表不能全部检查；驱动的 EBUSY 是最终保护，失败不重试。

输出 `PROBE_DIR=.../runs/probe_时间_UUID`。从首帧开始约 30 秒，初始最多等待 10 秒；Ctrl-C 正常停止并保存已经收集的元数据。
固定容量 4096 条、983040 B。循环期间仅写内存；正常退出/SIGINT/SIGTERM 后保存 CSV，容量耗尽明确 FAIL。
SIGKILL/断电可能丢失尚在内存的元数据，不能宣称完整。

主要结果：

- `video_io_events.csv`：全部循环的原始 sequence/timestamp/flags/bytesused 和系统调用时间。
- `probe_end.json`、`probe.log`：运行是否完整及错误。
- `v4l2_before.json`、`v4l2_after.json`：只读格式/帧率/可用标准控制查询；不支持的控制保留 errno。
- `v4l2_enumeration.json`：VIDIOC_ENUM_FMT / ENUM_FRAMESIZES / ENUM_FRAMEINTERVALS 原始整数结果、errno 和正常 EINVAL 结束记录；遍历有界。
- `v4l2_negotiated.json`：初始化后在实际流 fd 上进行 G_FMT/G_PARM 回读；未达到此阶段则文件缺失，不伪造。
- `comparison.json`、`result.json`：与历史 A 的帧数、间隔、序号、错误、CPU 对比；运行成功与连续性分别判定。
- `preflight.json`、`session.json`、`build_manifest.json`、`before_*`/`after_*`：拓扑、占用、软件哈希和系统状态。

程序结束码 0 只代表探针完整运行；**不表示无丢帧**。检查 `observed_continuity` 和所有计数。
没有保存图像，因此也不能声明图像像素完整性、双目 ROS 配对或物理同步已验证。
即使 B 改善，也不能把磁盘认定为唯一原因；同时减少了图像复制、ROS、HID、可能的雷达并发等负载。

软件重新编译和无设备检查（仅在本目录生成文件）：

```bash
./build.sh
./build/zed_v4l2_probe --self-test
./build/production_loop_test
./build/native_mode_test
python3 -B test_probe.py
```

原始 A 仅读 sidecar，不读取大 bag：`evidence/baseline_A.json`、`eight_event_timing.csv`。
完整审计：`../../zed_usb_uvc_v4l2_root_cause_analysis.md`。
回退只需不再运行本目录探针；正式采集二进制未替换，不需要恢复系统或清理工作空间。
