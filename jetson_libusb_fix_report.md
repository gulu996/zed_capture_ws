# ZED 2i libusb 动态库冲突修复报告

日期：2026-10-15。结论：**动态依赖修复 SOFTWARE_TESTED；修复后的真实 30 秒采集 HARDWARE_PENDING / BLOCKED。** 当前工具环境的 USB 节点及 TCP 限制仍存在，不能用动态符号检查通过代替相机采集通过。

## 原因及修复前后证据

已读取原始失败会话 `/home/jetson/zed_capture_data/20261015_190646_08999cd5/`：`capture.log` 报 `undefined symbol: libusb_wrap_sys_device`，`manager_result.json` 返回 127，没有 bag。该会话及所有原始日志保持原样。

本轮先运行 `ldd`、`ldd -r`、`readelf -d`、`readelf --dyn-syms --wide`、`nm -D --defined-only`，得到：

| 检查 | 修复前 | 修复后（采集子进程环境） |
|---|---|---|
| libusb 解析路径 | `/opt/MVS/lib/aarch64/libusb-1.0.so.0` | `/usr/lib/aarch64-linux-gnu/libusb-1.0.so.0` |
| 系统库最终实路径 | 未选中系统库 | `/usr/lib/aarch64-linux-gnu/libusb-1.0.so.0.2.0` |
| `libusb_wrap_sys_device` | MVS 库未导出；采集 ELF 的 UND 符号不能解析 | 系统库导出，`nm` 标记 `T` |
| `ldd -r` | 输出 `undefined symbol: libusb_wrap_sys_device` | 无缺失符号、无缺库，返回 0 |
| 相同子进程环境的 ctypes 加载探针 | — | 加载 libusb 成功，函数可解析，`/proc/self/maps` 显示系统库 |

根因：继承环境的 `LD_LIBRARY_PATH` 含多个 `/opt/MVS/lib/aarch64`，排序先于系统库；MVS 和 Ubuntu libusb 使用相同 `libusb-1.0.so.0` 名称，但提供的符号不同。采集二进制依赖此 SONAME，RUNPATH 只有 `/opt/ros/noetic/lib`，原环境选中了不满足其符号需求的 MVS 库。

此前仅检查 `ldd` 中有没有 `not found`，不能发现“同名库已找到，但函数不存在”的情况。本机 `ldd -r` 即便输出该 undefined symbol，也返回 **0**，因此不能只检查命令退出码。

证据目录：[`evidence/libusb_fix_20261015_192007/`](evidence/libusb_fix_20261015_192007/)。其中包括修复前后完整 ldd 输出、动态符号表、库导出表、加载探针、原文件备份、补丁及保护检查。

## 修改文件与隔离范围

1. 新增 `scripts/capture_environment.py`：复制继承环境，只在副本中设置 `LD_LIBRARY_PATH`，不写 `os.environ`。采集节点的搜索路径为：

   ```text
   /usr/lib/aarch64-linux-gnu:/lib/aarch64-linux-gnu:/home/jetson/zed_capture_ws/devel/lib:/home/jetson/catkin_ws/devel/lib:/opt/ros/noetic/lib
   ```

   保留 ROS 等原环境变量；不使用 LD_PRELOAD 补符号，不替换库文件。若运行环境已有非空 LD_PRELOAD/LD_AUDIT，预检明确拒绝未经验证的注入环境，不静默抹去其作用。

2. 修改 `scripts/session.py`：预检使用上述环境执行 `ldd -r`，检查 stdout/stderr 中的缺失符号、缺库、重定位错误，检查退出码并确认 libusb realpath 是系统库。检查失败时，在创建会话、ROS Master 或 Livox 驱动之前退出。仅 `zed_capture_node` 的 `Popen` 传入该环境；`roscore`、Livox 的 `roslaunch` 仍使用 `env=None`，继承管理器原环境。正常进入采集会话后新增 `capture_loader.json`，保存原环境路径、节点路径和完整动态依赖预检结果。
3. 新增 `scripts/test_capture_environment.py`：针对真实 ELF 的冲突复现/修复测试，父环境不变测试、退出码 0 但 stderr 缺符号测试、缺二进制测试，以及符号失败时禁止启动子进程的测试。
4. 更新 `README.md` 的使用说明与 `evidence/software_manifest.json` 的交付哈希。旧 manifest 保存在本次证据目录，不修改已录会话的软件清单。新增本报告。

`env.sh`、`start_capture.sh` 保持字节不变；无须手动 export 新变量。采集 C++ 二进制未改变，无须重新编译，也没有重新构建原 FAST-LIVO2 工作空间。

## 验证结果与实机尝试

- **SOFTWARE_TESTED**：5 项回归测试通过，日志为 `regression_tests.log`。其中 MVS 冲突与修复均对现有 ARM64 采集 ELF 执行真实 `ldd -r`。
- **SOFTWARE_TESTED**：系统库动态加载探针成功，导出符号可解析；父进程环境没有变化。
- **VERIFIED**：42 个受保护文件的哈希无变化，包括系统/MVS libusb、MVS 库文件、`.bashrc`、ld.so 配置/缓存、采集二进制和原失败会话文件。系统包清单、原 catkin_ws Git status、BLAS/LAPACK 默认选择均未改变。
- **BLOCKED / HARDWARE_PENDING**：符号检查通过后，确实重新执行了：

  ```bash
  /home/jetson/zed_capture_ws/scripts/start_capture.sh --duration 30
  ```

  本次约 0.81 秒后在预检退出 **2**，动态依赖状态为 `SOFTWARE_TESTED`。当前工具沙箱没有 `/dev/video0`、`/dev/video1` 和 USB bus 节点；创建 AF_INET TCP socket 返回 `Operation not permitted`。这与用户普通 SSH 的主机权限不同，不能据此判断相机损坏。

  没有启动 ROS/Livox/相机，没有新建数据会话或 rosbag，**没有完成实际 30 秒采集**，FPS、图像、雷达和 IMU 结果均为 PENDING。未忽略这些错误，也未尝试绕过沙箱。保存了 `capture_30s_attempt.stdout.log`、`capture_30s_attempt.stderr.log` 和 `capture_30s_attempt_result.json`。

## 主机继续测试与回退

在 Jetson 普通 SSH 终端使用原命令即可，不需修改 shell 或全局库路径：

```bash
/home/jetson/zed_capture_ws/scripts/start_capture.sh --preflight
/home/jetson/zed_capture_ws/scripts/start_capture.sh --duration 30
```

预检的 `dynamic_dependencies.libusb_realpath` 应为系统 `libusb-1.0.so.0.2.0`，`errors` 应为空。若出现新的真实硬件/采集错误，保留新会话的 `capture.log`、`capture_loader.json` 和检查报告，不把动态依赖通过视为采集通过。

回退仅需恢复本次证据目录里的 `session.py.before` 和 `software_manifest.before.json`；保留新增文件、失败日志及数据，不删除历史会话。恢复旧管理器会重新暴露 MVS 搜索路径冲突，不能视为已修复的运行方案。

本轮新增/升级/卸载系统包均为 **0**；没有修改全局 LD_LIBRARY_PATH、`.bashrc`、MVS SDK、系统 BLAS、原 FAST-LIVO2 源码/工作空间、网络或驱动；没有安装 CUDA/ZED SDK；没有 Git commit。
