# C5-I-A 软件验收

本轮没有实机采集、没有修改正式C5-G二进制。实施范围仅diagnostics/field_capture及本轮五份报告。

| 指标 | 结论 |
|---|---|
| C5I_A_SOFTWARE_READY | PASS，独立候选，等待硬件验收 |
| C5I_A_HARDWARE_PENDING | PENDING，未启动新传感器会话 |
| C5I_B_CONTINUOUS_READY | PENDING，未指定duration明确拒绝 |
| C5I_B_SEGMENTATION_READY | PENDING，原8GB保护保留 |
| SAFE_STOP_VALIDATED | SOFTWARE_ONLY；真实硬件关闭待验证 |
| FULL_STRICT_CHECK_SEPARATED | VERIFIED；独立入口不启动检查器 |
| LEGACY_C5G_PRESERVED | VERIFIED，83项哈希和catkin已有diff一致 |
| PHYSICAL_SYNC / GNSS_MEASUREMENT_MAPPING / L2B_MAPPING | PENDING，无重新验证 |

## 实施文件

独立Python：field_capture.py（后台管理/状态/停止）、field_common.py（身份/有界读取/结束证据）、session_field.py（原manager独立副本，检查分离及有序收尾）、check_field.py（手动完整检查）。
入口：start_capture.sh、status_capture.sh、stop_capture.sh、check_capture.sh。
配置：capture_hd720_c5i.yaml，与原capture_hd720_c5g.yaml字节相同。
候选C++：capture_node_field.cpp、field_stop.hpp。独立build_candidate.py使用现有编译/链接参数，输出build/lib/zed_capture/zed_capture_node，插件复制件仍与原SHA相同。原source和devel未覆盖。session_field.diff及capture_node_field.diff列出所有候选差异。

新增采集状态文件不会成为L2-B输入，也不影响C5-H原始数据判定。

## 编译与测试

- 独立C++候选编译成功；ldd -r节点及JPEG插件无missing/undefined symbol，使用系统libusb。
- Python语法及4个shell入口语法通过；无duration返回2并打印CONTINUOUS_MODE=PENDING。
- C5-I软件测试26项通过（test_current.log）：身份/PID/boot、幂等stop、STALE、损坏元数据拒绝、重复lease、停止超时、状态磁盘写入失败不跳过cleanup、初始化停止、SIGHUP、SIGINT、无GNSS/启用GNSS候选参数路径及不启动checker。
- GNSS既有回归24项通过（gnss_regression.log），包含R2.1真实GGA→RMC恢复、校验/质量/UTC及原模式。
- C5-G既有回归6项通过（c5g_regression.log），包含300秒参数、原短模式限制、GNSS两种模式和重复真实字节流。
- 原时钟配置6项和诊断15项回归通过，原时钟算法文件哈希不变。
- C++停止+真实bag软件测试：100条SYNTHETIC IMU排空，原整数Header不变，bag可全部读回，8GB/磁盘储备函数边界通过。
- 原JPEG writer故障注入测试通过，结果在SYNTHETIC_jpeg_writer。
- GNSS历史真实消息经过原C++ writer：raw578/status578/pvt_local253/receiver_pvt253/utc_observation21，合计1683条，均写入并读回，无拒收/序列化/写盘错误。结果REPLAY_gnss_writer_verified。不是新硬件采集。

## C5-H真实五分钟只读回归

使用20261018_185527_61ca19f8；只调用一次新手动完整检查入口。
比较424,070个叶子字段，唯一差异offline_read_seconds；所有数据计数、哈希和异常相同。8988对JPEG，MID3017/60338，原12次图像长间隔、28个驱动序号缺口、402漏锚点更新继续保留。DATA_INTEGRITY=FAIL，未放宽任何门限。
总耗时229.306秒、峰值284612KiB（277.941MiB），全bag遍历528576条。结果见checks/20261018_185527_61ca19f8_20261019_134357_7971e184与strict_comparison.json。这只是检查入口兼容性证明，未宣称进一步加速。

## 保护核查

修改前备份：baseline_20261019_133405，含原session.py、原C5-G YAML、原二进制、83项SHA和原catkin diff。保护结果：protection_check.json，全部相同。
正式node SHA256：4bc5bae4c14d917bffac8b72ac4d03122fca3153536c668ce7bb2ea2d657d4ef。
无系统依赖安装、无sudo/权限/网络/NTP调整、无commit/push/reset/clean。只读回归输出在新checks目录，原bag/JPEG/sidecar未改写。

## 用户15项问题答复

1. 现场结束不自动FULL_STRICT_CHECK：是。
2. Finalization：原队列/关闭/同步完整保留，软件验证通过，实机关闭待确认。
3. 无duration持续采集：否，明确PENDING并拒绝。
4. 8GB限制：仍保留。
5. bag分段：未实施。
6. SSH断线：结构上独立session且日志重定向；SIGHUP软件验证通过，真实SSH拔线待测。
7. 新SSH查询：基于持久身份/状态实现，子进程软件验证通过。
8. 新SSH停止：实现身份安全的请求文件，软件通过，实机待测。
9. Ctrl+C：请求正常收尾，软件通过。
10. 停止bag读取：模拟实际bag与历史真实bag验证通过；新硬件未采集。
11. JPEG索引：增量保留，原writer回归通过；新硬件未验证。
12. GNSS原始：解析及持久化未改，旧数据回归通过；新硬件未验证。
13. 无新增无界内存/图像队列；原队列限制和300秒限制保留，状态缓存有界。
14. C5-H兼容：逐项等价已验证。
15. C5-G：正式二进制、原配置、启动脚本、算法未改。

建议先人工执行一次30秒候选测试，并检查stop/GNSS ack/JPEG同步与手动完整报告；成功后再考虑300秒现场使用。C5-I-B必须另外设计bag分段、容量与长时间故障测试，不能把本轮软件结果作为持续采集已通过。
