# 原生 720P30 YUYV 联合采集 C2：准备与回归

2026-10-17。**软件准备和回归通过；C2 实机状态为 PENDING_HARDWARE。按要求在准备阶段停止，等待用户通过普通 SSH 终端执行一次测试。** 未重复低负载探针，未启动 C2、JPEG 或 FAST-LIVO2。

## 1. 配置与参数链路

独立配置：`/home/jetson/zed_capture_ws/src/zed_capture/config/capture_hd720_c2.yaml`。

它从当前 `capture.yaml` 逐字节复制，仅把 `resolution: HD1080` 改为 `resolution: HD720`。解析后的字段差异也只有 resolution。原默认文件保持 HD1080，SHA256、大小、mtime 均未变。fps=30、queue_mb=256、minimum_free_gb=10、8UC2/YUYV、原锚点路径、Livox auto、SYNC_PENDING、未知内外参及其他配置保持原值。4 MMAP 缓冲来自未修改的库，未新增虚构的 YAML 参数。

实际调用链：

```text
run_joint_test.sh "$@"                 原来已支持 shell 参数透传，不修改
  → joint_test.py --config PATH         本轮新增选择/验证/记录/透传
  → start_capture.sh --duration 30 --config ABS_PATH
  → session.py --config ABS_PATH        原来已支持，增加来源元数据
  → zed_capture_node _resolution:=HD720 原来已支持，无核心代码变化
```

不传 `--config` 时，joint 仍读取原默认配置，子进程命令仍为原来的 `start_capture.sh --duration 30`。显式配置先解析为绝对路径，作为 argv 单个元素传递，不经过 shell 拼接，因此空格不会被拆开。缺失文件、非法 YAML、缺少字段、不支持的模式/FPS 或非 YUYV/8UC2 被拒绝，不回退默认配置。15 秒预监测期间如果配置内容变化，也会在启动录制前拒绝。

联合测试目录新增：`capture_config_source.json`（原路径、SHA256、explicit 标记及解析内容）、`capture_config.yaml`（读取时原文）、`capture_command.json`（实际 argv）。`test_result.json` 记录 config_path、config_sha256、requested_resolution。

会话元数据要求对应一个最小补充：原 `session.json` 只有配置内容，没有来源路径。本轮在 `session.py` 中增加 **config_path、config_sha256**，并把会话的 `capture.yaml` 保存为该次解析使用的原始字节，避免复制时与已解析内容不一致。这是配置溯源修改，不修改传感器或录制策略。原软件 manifest 作为历史构建记录继续保留，本轮脚本变更另存 diff 和哈希证据。

## 2. 保持不变的行为

- 前监测 15 秒、后监测 15 秒、30 秒采集、原中断/退出策略不变。后监测仍从发现采集 summary 或 manager 退出计时，覆盖真实录制而不把耗时 bag 检查误当录制时长。
- CLOCK_MONOTONIC_RAW/MONOTONIC/REALTIME 的采样、分析和门限不变。
- 正式节点、Open Capture/HID 库、V4L2 4 缓冲、select 超时、HID 队列、IMU 时间分段、时间锚点和 L2-B 均不改。
- 图像、IMU、MID CustomMsg、时间戳和原始 sidecar 的 topic、格式及写盘路径不变；不引入 JPEG。
- 原严格检查器保留，不调整帧率、长间隔、序号缺口、锚点漏读或时间有效性判定。

## 3. 720P 图像验收依据

| 层级 | 720P 预期字段 | 本阶段证据 |
|---|---|---|
| V4L2 双目缓冲 | 2560×720、YUYV、stride=5120、bytesused=3,686,400 | 原生低负载实测已验证；C2 仍需核对实际数据 |
| 左目 ROS Image | 1280×720、8UC2、step=2560、data=1,843,200 bytes | 正式源码及 SYNTHETIC 全尺寸拆分测试通过；C2 实际消息待验 |
| 右目 ROS Image | 同左目 | 同上 |
| 双目关联 | 同次原始缓冲、相同 Header.seq/stamp，关联 VideoStamp.pair_id | 现有源码及全 bag 检查逻辑保留；C2 待验 |
| 原始时间 | V4L2 整数 sec/usec、flags、sequence 和原始 MID/HID 时间 | 原路径保持；不加固定偏移 |

源码中 `left->step=right->step=f.width`；双目 width=2560，所以单目 step 为 **2560**，不是 V4L2 stride **5120**。实际复制由原 `capture::splitYuyv` 按双目行 stride 定位，再分别复制左右半行；没有把 YUYV 重标记为 bgr8。

原 `check_recording.py` 已按 session 配置选择单目 1280×720，逐条反序列化 bag，并检查 encoding/step/data 长度以及左右目/VideoStamp 的 sequence+stamp 对应。节点还记录 `device_settings.txt` 中的实际尺寸、实际 buffer 数量，VideoStamp 含 stereo_width/height/pixel_format/row_stride/bytesused，足以复核实际输出而不只相信 YAML。

**实际像素内容仍为 PENDING_HARDWARE。** C2 后应在前、中、后各抽取极少量完整双目对，有界解码 YUYV 查看亮度分布、行边界、左右图像是否错误重复及明显错位；不批量导出图像，不把暗场或相似场景自动认定为代码错误。结构检查和 SYNTHETIC 拆分测试不能代替真实像素复核。720P 内参、物理曝光同步继续未验证。

## 4. 编译与软件回归

证据目录：`/home/jetson/zed_capture_ws/diagnostics/c2_hd720_preparation/`。

- Python 修改文件编译通过，生成 pyc 仅位于该证据目录；两个 shell 入口语法检查通过。
- 新 `clock_diag/test_joint_config.py`：**6 项测试全部通过**（内含多个子案例）。真实 Popen 调用边界被 mock，覆盖默认 HD1080、显式 HD720、空格路径、配置错误不启动、预监测期间配置改变拒绝；mock `session.py` 还确认节点收到 `_resolution:=HD720` 且 session 来源路径/哈希/配置原文正确。没有启动 ROS master 或传感器。
- 原 `test_diag.py`：**15 项回归全部通过**，含时钟异常检测、原 15 秒后监测语义、运行/完整性分离及 IMU 时间分段验证。短暂启动的只有独立本地时钟测试进程，不涉及传感器。
- 新 `split_hd720_test.cpp` 使用未修改的生产头文件，在 2560×720、stride=5120 的明确 SYNTHETIC 输入上逐字节验证所有左右目行和像素位置，结果通过；单目各 1,843,200 bytes，不是复制同一半幅。只编译独立测试目标，没有重建正式节点或库。
- 原 `capture_core_test` 通过。正式节点 `ldd -r` 通过，无缺失库/符号；实际隔离环境加载系统 `/usr/lib/aarch64-linux-gnu/libusb-1.0.so.0.2.0`，没有回到 MVS libusb。

日志：`config_tests.log`、`clock_regression.log`、`split_test.log`、`shell_syntax.log`、`software_results.json`；修改 diff 和原文件备份同目录保存。

## 5. 唯一一次 C2 非采集预检

诊断目录：`/home/jetson/clock_diag/runs/joint_20261017_162139_94d50b7d`。

实际读取的是 `capture_hd720_c2.yaml`，requested_resolution=HD720；估算 30 秒双目原始像素 **3,317,760,000 bytes**。当时可用空间 **150,643,335,168 bytes**。原检查规则为预计图像×1.15 + 10 GB 余量，当前约需 13.815424 GB，磁盘检查通过；实际执行时会重新检查。估算不是最终 bag 大小，仍需容纳雷达/IMU、元数据和收尾。

预检状态 **HARDWARE_PENDING**，原因：

- 沙箱内视频 `/dev/video*` 不可访问。
- ZED HID USB 节点不可访问。
- ROS AF_INET socket 返回 EPERM。

未创建采集会话、未启动 monitor/ROS/Livox/相机、未重试或修改权限。MID 可达性标为 NOT_PROBED（非采集预检且已有权限阻塞），不能据此判断雷达断电或硬件故障。时间同步状态只读保存，没有改变 NTP。

## 6. 普通 SSH 终端唯一 C2 命令

先确保 ZED 正常连接、MID-360 和 STM32 已供电、同步链路保持原样，原采集进程已经自然退出。在普通 jetson 用户 SSH 终端执行一次：

```bash
/home/jetson/clock_diag/run_joint_test.sh --config /home/jetson/zed_capture_ws/src/zed_capture/config/capture_hd720_c2.yaml
```

不要加 sudo，不需要手动协调后台监测进程。脚本保留 15 秒前监测、30 秒录制、15 秒后监测和 bag 完整性检查；整个命令可能明显超过 60 秒。结束前应等待所有检查完成。测试失败不自动重录；保存其 `TEST_DIR`、`SESSION` 和日志供复核。运行正常但严格完整性 FAIL 时，外层脚本仍可能返回非零，这是预期的分层判定，不应当作用户中断。

`TEST_DIR` 位于 `/home/jetson/clock_diag/runs/joint_...`；新 bag 与 sidecar 位于 `/home/jetson/zed_capture_data/时间_UUID`。输出均为新目录，不覆盖旧数据。原有无参数命令仍选择 HD1080，C2 必须使用上面的显式配置命令。

## 7. C2 后的实际验收及对比

| 结果维度 | 目前状态 | 实测后必须核对 |
|---|---|---|
| CAPTURE_RUNTIME | PENDING_HARDWARE | manager returncode、failed、bag_finalized、实际持续时间及提前退出 |
| DATA_INTEGRITY | PENDING_HARDWARE | 左右数目/字段/配对、实际 V4L2 模式、长间隔、序号、完整 bag、MID 结构/连续性、锚点漏读、队列溢出 |
| ZED_IMU_TIME_VALIDITY | PENDING_HARDWARE | 原始 HID 报告、启动分段、tick 缺口、队列丢弃及读取错误 |
| CLOCK_DIAGNOSTIC | PENDING_HARDWARE | 本次三时钟、采样间隔/夹取/缺口与有效区间，不能沿用旧 PASS |
| L2B_MAPPING | PENDING | 不修改算法；本轮未运行 C2 的离线映射 |
| PHYSICAL_SYNC | PENDING_HARDWARE | 不以软件映射或程序完成代替曝光物理同步 |

实测后还需分别列出：MID GPS/type=2、点云与 IMU 连续性；IMA1 已保存状态、漏更新和图像候选包围覆盖；writer 队列峰值、等待、溢出；实际 bag 大小、CPU/RSS、NVMe 吞吐。候选覆盖不等于锚点历史完整，更不等于 L2-B 有效。

对比基线保持 `/home/jetson/zed_capture_data/20261017_144432_c0112f6c`：891 对，8 长间隔，16 驱动编号缺口，最大 66.880 ms，bag 7,525,436,291 bytes。C2 尚没有真实数值，不填写虚构改善率。理论双目像素吞吐 248.832→110.592 MB/s，减少 55.56%；实际整 bag 收益、CPU/内存/队列收益必须从 C2 数据计算。两次测试环境和时间不同，不据此断言分辨率唯一因果。

## 8. 修改清单、保护和下一步

- 新增独立配置 `src/zed_capture/config/capture_hd720_c2.yaml`。
- 修改 `clock_diag/joint_test.py`：配置选择、验证、溯源、argv 透传；保留时钟计算及生命周期。
- 修改 `scripts/session.py`：配置来源路径/哈希和一致原文快照，未改节点参数逻辑、话题、队列或检查门限。
- 新增 `clock_diag/test_joint_config.py`、独立拆分测试及本报告/证据。

38 个受保护文件的 SHA256、大小和 mtime 均不变，含正式核心/可执行文件、Open Capture/HID 静态库、默认配置、时钟采样/分析代码、原检查器等；两个获准修改的启动管理脚本单独留存前后 diff，不冒称这些脚本完全未变。未改 catkin_ws、FAST-LIVO2、Livox、STM32、NTP、系统依赖或历史 bag/sidecar；未 commit/push。

回退配置选择只需不传新 `--config`；恢复本轮脚本时可参照证据目录 `before/` 中的备份，在确认没有后续编辑后人工恢复。无需恢复系统、删除数据或重编正式节点。

本轮在此停止。实测数据到达后再生成 `zed_native_720p_c2_validation.md`。是否值得进入 JPEG Q90/420、Q95/420 的 Jetson 本地性能测试由 C2 的真实运行、图像质量和完整性结果决定；当前没有修改或运行 JPEG 链路，也没有批准进入长时间录包。
