# Jetson ZED 2i + MID-360 + GNSS 数据采集

在 Jetson 上采集 ZED 2i 双目 JPEG、MID-360 点云/IMU、GNSS 原始记录及时间诊断。当前现场入口为 `diagnostics/field_capture`，默认配置为 **HD720、30 Hz、JPEG quality 95、GNSS 开启**。

## 启动采集

以下命令适用于已经配置、编译完成的 Jetson，工作空间位于 `/home/jetson/zed_capture_ws`。相机、雷达与 GNSS 应已连接，设备路径与配置一致。

```bash
# 从电脑连接 Jetson
ssh jetson

# 在 Jetson 上采集 60 秒，结束后自动关闭文件
cd /home/jetson/zed_capture_ws
bash diagnostics/field_capture/start_capture.sh --duration 60
```

持续采集（无固定结束时长）并脱离当前终端：

```bash
bash /home/jetson/zed_capture_ws/diagnostics/field_capture/start_capture.sh --detach
```

启动时会输出 `SESSION=...`。数据保存在 `/home/jetson/zed_capture_data/<session_id>/`。

## 状态、停止与检查

```bash
# 查看当前会话；追加 --follow 可持续查看
bash /home/jetson/zed_capture_ws/diagnostics/field_capture/status_capture.sh

# 安全停止当前会话，等待队列排空和文件关闭
bash /home/jetson/zed_capture_ws/diagnostics/field_capture/stop_capture.sh

# 采集结束后检查指定会话，将下面路径替换为实际 SESSION 路径
bash /home/jetson/zed_capture_ws/diagnostics/field_capture/check_capture.sh \
  --session-dir "/home/jetson/zed_capture_data/替换为实际会话ID"
```

上面的 `<session_id>` 是占位符，请替换后执行。状态与停止命令也支持 `--session 实际会话ID`。前台采集时 Ctrl+C 会请求安全停止；`--detach` 模式请使用停止脚本。等待 `FINALIZED`，再执行完整检查；完整检查结果目录由 `CHECK_DIR` 输出。`FINALIZED` 仅说明采集完成收尾，不等于数据检查通过。

## 数据与时间

- `camera/left`、`camera/right`：左右目 JPEG；`frames.csv` 保存图像索引。
- `sensors.bag` / 分段 bag：雷达、IMU、GNSS 和诊断消息。
- `video_timestamps.csv`、`anchors.jsonl`、`anchor_poll_events.csv`：原始时间戳和 IMA1 证据。
- `gnss/`、`clock/`：GNSS 原始记录及主机时钟诊断。

采集保存原始时间域，不自动运行 SLAM 或 GNSS 融合。L2-B 图像时间映射需要独立离线执行；采集检查通过不代表物理曝光同步或 GNSS→MID 测量时间同步通过。

## 环境与源码说明

依赖现有 ROS1 Noetic、Livox 工作空间、libusb、OpenCV/TurboJPEG，以及 `/home/jetson/clock_diag`。采集使用仓库内的 Open Capture/HIDAPI，不依赖 ZED SDK/CUDA。配置见 [capture_hd720_c5i.yaml](diagnostics/field_capture/capture_hd720_c5i.yaml)，其中设备序列号、GNSS 串口及本机路径需要与实际环境匹配。

这是现有 Jetson 的源码备份，**不是克隆后即可启动的完整运行环境**。构建二进制未入库；现场入口依赖 `build_continuous_v3` 和冻结基线检查。在新机器恢复时，需要单独核对依赖、构建和基线，不能跳过保护检查。实验报告和备份记录不纳入仓库。

仓库保留源码、配置、测试、许可证及本 README；实验报告、采集数据、日志、缓存及构建二进制未纳入。`.gitignore` 使用明确文件白名单，新增源码时需要同步更新。
