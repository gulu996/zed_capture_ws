# C5-G 实现与运行边界

状态：SOFTWARE_TESTED / HARDWARE_PENDING。没有执行新的实机采集。没有安装依赖、修改系统服务、提交或推送Git。

## 独立模式

配置：`/home/jetson/zed_capture_ws/src/zed_capture/config/capture_hd720_c5g.yaml`。
它完整继承原C5-F+GNSS配置，仅新增`long_recording: true`；原7份配置SHA256全部保持不变。保持HD720、30FPS、Q95/420、4对编码/写入队列、原消息/话题、原GNSS质量码和所有完整性门限。

默认入口不传duration仍是30秒，默认不启用C5-G。5分钟必须显式选择新配置和300秒。不允许静默延长旧C5-F，也不允许1200秒。本次跳过的仅是旧“长于30秒必须先有同配置严格PASS会话”的启动资格门禁，未跳过采后严格数据检查。

## 修改文件

- `src/zed_capture/include/zed_capture/jpeg_files.hpp`：可选增量记录；32事件槽循环复用、按事件提交索引、同步后释放目录历史、进度记录。原工厂默认路径保留。
- `src/zed_capture/src/jpeg_shadow.cpp`：只添加incremental factory，复用原Codec及3对预热；没有修改编码算法。
- `src/zed_capture/src/capture_node.cpp`：明确long模式门禁、新工厂选择、1Hz空间保护、5秒writer检查点、8GB单bag预算保护、最终检查点同步。
- 新增`src/zed_capture/include/zed_capture/long_recording.hpp`及`scripts/long_recording.py`：有限时长/磁盘预算策略、资源只读采样。
- `scripts/storage_mode.py`、`gnss_config.py`、`session.py`：显式模式透传、300秒预检、打印计划/路径/剩余空间、软件版本快照；关闭模式不新增GNSS依赖。
- `scripts/check_recording.py`、`jpeg_file_check.py`：新模式记录请求时长并按原90%比例检验有效跨度，避免30秒数据冒充300秒。原图像、锚点和时间门限不变。
- `/home/jetson/clock_diag/joint_test.py`：仅编排duration透传、运行保护及结果跨度检查。15秒前后监测保留，三时钟计算算法不改。
- `diagnostics/gnss_r2/gnss_receiver.py`：仅长模式保护时长及周期持久化；R2.1核心、CRC、质量码和时间语义不变。
- `diagnostics/gnss_r2/test_gnss_r2.py`：识别新增独立GNSS配置。
- 新增`diagnostics/zed_c5g/`测试与只读异常目录检查工具；构建更新node、JPEG库及两个依赖该头文件的测试可执行文件。

完整修改前后diff和SHA：`/home/jetson/zed_capture_ws/diagnostics/zed_c5g/preparation_20261018_181957/source_changes.diff`、`hashes_before.json`、`hashes_after.json`。修改前源码和二进制保存在`/home/jetson/zed_capture_ws/diagnostics/zed_c5g/preparation_20261018_181957/before/home/jetson/`，没有覆盖既有备份。

## 有界线程/文件生命周期

采集线程复制有效像素后投递，绝不把已QBUF的MMAP指针传给JPEG线程。编码队列4、写入队列4、JPEG字节预算32MiB；32槽保存待处理元数据，writer索引提交后回收。拒收记录失败，不阻塞采集等待JPEG。文件名、整数时间戳及左右目成对提交保持原格式，不生成图像bag。

唯一sensors.bag writer仍保存MID、GNSS及诊断。周期checkpoint也使用该writer，避免多线程同时操作bag。GNSS进程独立保存原始字节，未启动第二串口读取器或第二bag writer。

C5-G新增`jpeg_progress.jsonl`、`c5g_checkpoints.jsonl`、GNSS的`sync_checkpoints.jsonl`。JPEG队列、writer队列和GNSS各话题累计写入数可追溯；resources记录温度、CPU频率、RSS、磁盘和GNSS文件增长。原IMA1、失败poll及视频/HID记录全部保留。

## 退出及恢复限制

正常结束先停止生产，编码/写入线程排空，bag关闭并最终同步；失败停止同样尽力排空但保留失败状态。周期同步可能短时增加writer等待，真实5分钟需监测，不能预先声明无影响。异常目录检查不执行reindex，也不删除不完整JPEG；需要恢复bag时应另行授权并使用副本。

## 一次5分钟普通SSH测试命令

先确认ZED、MID-360、STM32和GNSS正常连接，且没有其他采集进程占用；无需RTK Fixed。执行一次：

```bash
/home/jetson/clock_diag/run_joint_test.sh --config /home/jetson/zed_capture_ws/src/zed_capture/config/capture_hd720_c5g.yaml --duration 300
```

脚本会产生唯一TEST_DIR和SESSION，实际采集前后各监测15秒；随后大bag检查还需要时间，请等待完整退出。需要提前停止时在同一终端Ctrl+C，请让正常退出处理完成，不要kill -9。已有GNSS无UTC、ZED启动报告和锚点历史漏读可能使DATA_INTEGRITY继续FAIL，应分别看运行状态及具体原因，不能把脚本非零退出简单等同设备采集未完成。

本轮到此停止，未执行上述命令。20分钟保持拒绝；需先确认5分钟现场资源和证据完整性，再处理离线检查内存等余项。

## 回退

仅使用原配置即可恢复旧30秒模式；但共享源码仍包含本次可选分支。若需二进制/源码完整回退，先停止全部采集并保存后续改动，按hash清单从本次before备份恢复对应文件，再编译及ldd检查。不要整目录覆盖、git reset/clean或删除新旧会话。当前未执行回退。
