# ZED 2i 原生 720P30 预检与测试准备

日期：2026-10-17。当前仅完成源码审计、独立探针修改、编译、无设备测试、只读 USB 描述符检查和一次非流式预检；**没有执行 720P 实机采集**。

## 当前验收状态

| 项目 | 状态 | 依据 |
|---|---|---|
| NATIVE_720P_SUPPORTED | PENDING_HARDWARE | 本机 USB 描述符列出 2560×720 及约 30 FPS，但尚不能访问设备进行 ENUM/G_FMT/G_PARM 实证 |
| LOW_LOAD_720P_RUNTIME | PENDING_HARDWARE | 未 STREAMON，不能沿用之前 1080P 的通过结果 |
| LOW_LOAD_720P_CONTINUITY | PENDING_HARDWARE | 没有本次 720P 帧序号或时间间隔实测 |
| FORMAL_CAPTURE_UNCHANGED | VERIFIED | 41 个受保护文件的 SHA256、大小和 mtime 前后对比见 protection_after.json |
| JPEG_REALTIME_PENDING | PENDING | 没有编码、安装编码库或生成 JPEG |

独立目录：`/home/jetson/zed_capture_ws/diagnostics/zed_v4l2_probe`。
本轮证据：`diagnostics/zed_v4l2_probe/evidence/native_720p_preparation/`。

## 实际设备线索及权限边界

当前 sysfs 视频设备：`/sys/bus/usb/devices/2-1.3`，VID:PID `2b03:f880`，协商 5000 Mb/s。当前读取的原始 USB 描述符保存为 `current_usb_descriptors.bin` 和 `current_usb_descriptors.json`，SHA256 为 `64fcc7592260e2d4d03679f66a55856f43221d6de7ea078ab29b722d4eacd04c`。

描述符 frame_index=1：2560×720、最大缓冲 3,686,400 bytes，间隔列表 166666 / 333333 / 666666（100 ns 单位，即约 60/30/15 FPS）。这来自本机实际设备，**不是根据官网型号支持作出的推断**；但 USB 描述符不能代替驱动枚举、请求后的格式回读和持续采集。

本沙箱能看到 `/sys/class/video4linux/video0` 与 video1，不能访问对应 `/dev/video*`。唯一非流式预检：

`diagnostics/zed_v4l2_probe/runs/probe_20261017_155118_9bf293a3/`

`hardware_run_started=false`，报 `Identity-matched /dev/video node inaccessible: sandbox or Unix permissions; no device open attempted`。无其他预检错误，动态依赖和构建清单检查通过。没有把权限边界判成相机故障，没有重试打开设备、修改权限或申请绕过沙箱。

## 原生输出实现

原库 `videocapture.cpp::checkResFps()` 已支持 `RESOLUTION::HD720` 的 30 FPS。它从单目分辨率表取得尺寸，将视频宽度乘以 2，通过 VIDIOC_S_FMT 请求 YUYV，通过 VIDIOC_S_PARM 设置帧率；没有先采集 1080P 再缩小的流程。

原探针写死 `HD1080` 和 8,294,400 字节验收值。本轮只给独立探针增加 `--resolution HD720`：

- 默认仍为 `HD1080`，对应 3840×1080 YUYV / 30 FPS / 4 MMAP。
- `HD720` 对应原生 2560×720 YUYV / 30 FPS / 4 MMAP；stride=5120、双目缓冲 3,686,400 bytes，单目理论 1280×720、1,843,200 bytes。探针没有实际拆分或保存图像。
- 继续链接同一个未修改的 `libcapture_oc.a`，使用原初始化、select、DQBUF、QBUF 和关闭循环。没有重写生产采集路径，没有改变曝光控制或原 100 ms select 超时。
- 新枚举在流启动之前执行；设置后在实际视频 fd 读取 G_FMT/G_PARM，退出后再次读取。模式、格式、stride、sizeimage、帧率或实际 buffer 数量不符即失败，不回退、不缩放。
- 枚举遍历有界：格式最多 64、YUYV 尺寸最多 256、目标尺寸帧间隔最多 128 项；保存每项 result/errno 和结束项。只把明确的离散模式视为已枚举支持，未能确认的范围不冒充通过。
- 枚举的 30 FPS 比较接受 UVC 整数 100 ns 描述符量化（333333/10000000 s）；实际 G_PARM 仍要求分母=30×分子。这不是放宽视频连续性或 L2-B 门限。
- 继续使用有界内存元数据记录，逐帧回调不写盘、不 fsync、不复制像素；停止并 join 后保存 CSV。原始整数 V4L2 sec/usec、flags、sequence 及所有 select/DQBUF/QBUF 事件保留。

`v4l2_before.json` 仅代表设置前状态，可能仍为 1080P；设置成功必须检查 `v4l2_negotiated.json`。本次 720P 流会改变相机当前视频模式，但不会修改正式配置文件；下一次正式初始化仍按正式配置请求模式。没有修改 ZED IMU 分段、MID 原始时间、L2-B 核心或历史结果，也没有加固定偏移。

## 修改文件与软件验证

全部代码修改都位于独立探针目录：

| 文件 | 修改目的 |
|---|---|
| `native_mode.hpp`（新增） | 模式尺寸、实际回读核对、有界枚举和原始结果输出 |
| `native_mode_test.cpp`（新增） | 无设备 SYNTHETIC 模式/枚举/错误/边界测试 |
| `probe.cpp` | 可选 HD720、三类枚举、初始化后实际格式回读及结束状态 |
| `run.py` | 命令行选择、唯一新会话、按模式记录配置、保护检查、720P 结果与报告 |
| `analyze.py` | 按原生模式核验 payload、实际枚举/格式证据；继续保留原门限 |
| `test_probe.py` | 720P 正反例与历史 1080P 回归 |
| `build.sh` | 仅编译独立探针/测试；更新可追溯构建输入清单 |
| `README.md` | 使用方式、证据与验收边界 |

另新增本预检报告。修改前的探针源码、旧构建产物和清单完整保存在 `evidence/native_720p_preparation/before/`，未覆盖原始实测目录。

验证结果（SOFTWARE_TESTED）：

- g++ 独立编译通过，`-Wall -Wextra` 构建无输出警告；未调用 catkin_make 或重建正式库。
- 新 native mode C++ 测试：尺寸、原生格式、30 FPS、拒绝不符回读、无权限枚举、有界遍历、量化匹配、生成枚举 JSON 可解析。
- 原 collector 自测通过；原正式循环的模拟 select/ioctl 测试通过。
- 17 项 Python 测试全部通过，包括缺少枚举拒绝、15/60 FPS 不匹配、错误尺寸/格式拒绝、720P 中仍识别 66.666 ms 和序号缺口。上述构造输入明确为 SYNTHETIC。
- 历史真实 1080P A 回归仍为 891 帧、8 长间隔、16 缺失驱动编号；历史 B 回归仍为 898 帧、0 长间隔、0 序号缺口。
- `ldd -r` 无缺失库/符号，CLI 帮助可用。未安装任何系统依赖。

日志见 `build.log`、`native_mode_test.log`、`collector_selftest.log`、`production_loop_test.log`、`python_tests.log`、`dynamic_dependencies.log`、`software_tests.json`。

## 普通 Jetson SSH 终端执行一次

确保正式采集已经自然结束、ZED 正常连接，以普通 jetson 用户运行：

```bash
/home/jetson/zed_capture_ws/diagnostics/zed_v4l2_probe/run_probe.sh --resolution HD720
```

不需要启动 MID-360 或 STM32，不需要 sudo。启动前按实际 VID/PID 查找视频节点，检查占用并拒绝干扰已有业务，不硬编码某个 USB 总线路径、不杀进程。测试从首帧计约 30 秒，未到首帧最多等待 10 秒；停流保护保持 3 秒。失败不自动重试，不启动 JPEG、ROS bag 或 C2。Ctrl-C 会保留已收到元数据，但中断不能计为完成 30 秒。

每次创建新的 `runs/probe_时间_UUID`，打印 `PROBE_DIR`。实际输出包括：

- `v4l2_enumeration.json`：VIDIOC_ENUM_FMT、ENUM_FRAMESIZES（全部 YUYV 尺寸）、ENUM_FRAMEINTERVALS（所选尺寸）。
- `v4l2_before.json`、`v4l2_negotiated.json`、`v4l2_after.json`：G_FMT/G_PARM 及控制查询；未达到阶段则没有相应文件。
- `video_io_events.csv`：原始时间、sequence、flags、buffer/字节数和全套调用诊断。
- `probe_end.json`、`result.json`、`comparison.json`、`probe.log`：完成状态、实际 FPS、间隔分布、缺口、select 超时、DQBUF/QBUF 错误、视频循环 CPU。
- `before_*` / `after_*`、`session.json`、`formal_before/after.json`：系统/USB 快照、请求配置与保护证据。
- 新会话内 `zed_native_720p_validation.md`：该次运行自动报告，失败也如实记录。

目前没有生成根目录的 `zed_native_720p_validation.md`，因为本轮尚无真实 720P 结果。用户执行后再按原始证据复核并生成最终验证报告；不能将本次无设备测试写成实机通过。

## 后续门槛与未完成事项

只有实际 ENUM、G_FMT/G_PARM 和 30 秒连续性均通过后，才制定 720P 完整联合采集 C2；本轮不实现或运行 C2。之后才使用 Jetson 上真实 720P 图像测试 JPEG Q90/420、Q95/420 的实际编码时间、CPU、内存、温度、吞吐及积压，本轮没有 JPEG 性能结论。

720P 双目像素内容、左右拆分、相机内参及物理同步尚未验证；不能直接复用 1080P 标定。低负载通过也不等于完整联合录包通过，更不解决历史锚点漏读、IMU 时间异常或设备时钟比例差。

回退无需系统操作：不使用新 HD720 选项即可。默认 HD1080 仍可运行；旧诊断构建已备份，正式节点、静态库、配置和原工作空间均未替换。没有 commit/push、系统安装、历史数据删除或覆盖。
