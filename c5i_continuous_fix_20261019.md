# C5-I 持续采集软件修复与验证（2026-10-19）

本轮未启动传感器、未运行真实采集。仅修改 diagnostics/field_capture 独立现场候选程序。正式 C5-G 源码、83项保护清单、默认/C2/C4/C5-F/C5-G配置及正式二进制保持不变。

## 状态查询与提前退出

两条命令在不同终端执行是正确用法。status --follow 的调用路径为 wait_status(..., stop_on_ctrl_c=False)，只读取小型原子状态快照。其 Ctrl+C 不写停止请求。前台 start 的 Ctrl+C 才发出停止请求。SIGHUP/观察进程退出不停止独立会话管理器。

实际会话证据：

|会话|录制时间|JPEG完成|队列拒收|文件同步最大耗时|停止请求|
|---|---:|---:|---:|---:|---|
|20261019_141225_850fc132|13.999s|420/421|1（pair421）|227.880ms|false|
|20261019_141336_6cfd54e4|30.002s|901/901|0|58.457ms|false|
|20261019_142427_5f1be0fe|6.664s|200/202|2（pair201、202）|250.233ms|false|

失败会话均 returncode=2、interrupted=false，是JPEG流水线检测到拒收后主动报错收尾，不是已记录的崩溃信号。第一失败会话：pair416后同步64个文件；sync CSV区间3657867324359～3658093709717ns，226.385358ms。417～420在此期间编码完成并占满4对写入队列；421于3658033073743ns完成编码被拒收。4个已排队任务在同步结束后才写入。

VERIFIED：短时文件同步占住唯一JPEG文件writer，4对队列无法吸收这次停顿，触发原有失败保护。UNRESOLVED：为什么该次fsync变慢，以及真实机器打开另一个终端是否间接改变负载。本轮没有证据证明status发送停止信号；跨进程软件测试也未复现该行为。不能宣称已永久排除底层磁盘/调度因素。

## 修复范围

- 现场JPEG候选头文件：编码队列仍4对；压缩后文件写入队列16对，上限仍32MiB；增量事件槽64个循环复用。不缓存无限帧，不改变Q95/420、预热、像素/整数时间戳、同步周期、33.333ms门限。
- 增大的是压缩数据停顿缓冲，不是将原始YUYV无界积压。16对在30FPS下约0.53秒的名义队列容量，不是最坏实时性保证。4对编码队列仍保留原失败行为。
- 写入拒收原因区分互斥锁忙、队列容量、32MiB字节上限。失败仍明确记录并触发保护，不静默丢弃。
- start不带duration或显式0进入持续模式；正数仍表示实际采集时长，不再限制300秒。初始化和前后时钟监测不计入录制时间。
- 独立 gnss_field.py 仅替换时长策略导入和原R2.1模块搜索路径；原协议解析、测量UTC、串口身份、3秒无字节保护、stop/done/ack及原始证据不变。持续模式取消总运行期限；指定时长保持时长+60秒receiver看门狗。
- 唯一bag writer使用SegmentedBag。每段512MiB或250000条消息后，在下一条消息写入前轮转。文件仍无压缩；8MiB chunk及一条消息可能使物理大小略超过512MiB软轮转阈值。该分段同时限制每段ROS索引增长。
- 命名 sensors.bag、sensors_000000002.bag 等；逐段close/fsync/rename及目录fsync，记录原record time、topic、MD5、计数、消息序号范围、大小。bag_segments.jsonl增量保存，正常退出流式生成bag_segments.json，不在内存保留全部分段。
- 原会话8GB总bag限制由安全分段替代，不取消磁盘保护。启动要求至多30秒原始载荷保守余量+10GB保留；实际录制每秒检查剩余空间。启动通过不保证整段指定时长一定有足够空间。
- 状态观察仍只读。分段后状态以是否存在*.bag.active判断OPEN，不能因第一段已关闭就错误显示整个writer关闭。
- 原C5-H不修改。现场手动检查增加分段身份/计数/原record time范围核对；独立严格检查适配器只扩展GNSS消费至全部分段，并按单段执行bag索引预算。所有原数据质量判断保持。完整检查仍手动执行，可能需要较长时间。

## 软件证据

目录：/home/jetson/zed_capture_ws/diagnostics/field_capture/

- continuous_python_final.log：33项原现场/新增观察回归通过。
- continuous_duration_integration.log：2项补充通过，0和1200秒均覆盖GNSS开/关，真实启动参数透传mock验证，不启动硬件。
- continuous_gnss_regression.log：16项GNSS-R2/R2.1回归通过。
- continuous_cpp_final.log：250ms同步延迟注入，40/40对保存、拒收0；800ms注入仍明确失败。同步I/O错误、5000条循环事件（超过原4096）、1000对分目录边界、398秒虚拟测量跨度、最后一条写入前SIGINT后完成该写入及分段close、关闭失败不产生完成索引、禁止覆盖及幂等close测试通过。
- continuous_jpeg_legacy.log：短写、零写、ENOSPC/半对失败、编码失败、队列满、像素生命周期、退出排空及分目录回归通过。
- REPLAY_gnss_segments_v3/test_result.json：1683条历史真实GNSS消息通过同一writer写入11段bag，五类MD5、序列化字节和原record time逐条相同。错误MD5、队列满、未打开writer错误仍显式失败。
- REPLAY_jpeg_v3：C2真实720P的3对图像重放，新插件JPEG均能解码为720×1280×3，配对及整数原时间保留。无新采集、无整bag复制。
- continuous_integration_validation.json：200段合成bag及11段GNSS历史重放读回；候选节点和插件ldd -r无缺失符号，libusb仍为系统库。
- continuous_protection.json：83项原文件哈希不变，原正式二进制和旧现场候选二进制均未替换。

软件注入不代表真实设备竞争、持续温度或磁盘延迟已通过。800ms过载测试的FAIL是预期结果，证明没有掩盖拒收。

## 使用

第一次验证仍建议短时受控测试，不直接用于未验证的长时间户外任务：

```bash
/home/jetson/zed_capture_ws/diagnostics/field_capture/start_capture.sh --duration 30
```

软件已支持不指定期限的持续模式（硬件稳定性待验证）：

```bash
/home/jetson/zed_capture_ws/diagnostics/field_capture/start_capture.sh
```

另一个SSH终端仅观察：

```bash
/home/jetson/zed_capture_ws/diagnostics/field_capture/status_capture.sh --follow
```

停止：在start的前台终端Ctrl+C，或任意新SSH终端执行：

```bash
/home/jetson/zed_capture_ws/diagnostics/field_capture/stop_capture.sh
```

status终端Ctrl+C仅结束观察。--detach启动后请用stop脚本停止。SSH异常断开不会发出停止请求。收尾包含所有生产者关闭、GNSS握手、JPEG/bag队列排空、最终同步及15秒时钟后采样，不能要求立即返回。重复stop幂等，无SIGKILL。

完成后手动严格检查：

```bash
/home/jetson/zed_capture_ws/diagnostics/field_capture/check_capture.sh --session <SESSION_ID>
```

原始数据及历史检查结果不被覆盖。

## 边界、风险、回退

- C5I_CONTINUOUS_SOFTWARE_READY=PASS；SEGMENTATION_SOFTWARE_TEST=PASS。
- STATUS_OBSERVER_SOFTWARE_TEST=PASS；SAFE_STOP_SOFTWARE_TEST=PASS。
- CONTINUOUS_HARDWARE_VALIDATION=PENDING；FULL_STRICT_CHECK保持逐会话PENDING直到实际执行。
- DATA_INTEGRITY不因跳过检查而变PASS；L2B_MAPPING、GNSS_MEASUREMENT_MAPPING、PHYSICAL_SYNC保持PENDING。
- 并未删除有界队列/磁盘/错误保护。持续模式含义为没有人为定时截止，遇真实断流、持续写盘阻塞、队列满或空间保留线仍安全停止并报告。
- 16对队列可以吸收本轮软件注入的250ms停顿，不能保证任意系统负载均无拒收。定期同步策略未更改，突然断电仍可能损失尚未同步的尾部；不得把文件存在当成已持久化。
- 手动C5-H仍有数值序列等明确内存预算；特别长的会话可能出现检查预算不足并报告FAIL/未完成，不能将这解释为采集损坏或擅自输出PASS。20分钟及更长实机稳定性尚未验证。
- 当前只切换独立field入口到build_continuous_v3。原C5-G入口仍可用于已验证模式。
- 修改前备份：diagnostics/field_capture/continuous_fix_backup_20261019_143213/。回退仅在全部采集停止后，用备份恢复field Python/C++/检查脚本及release_manifest；field_common旧版会重新指向原build目录。不要在活动会话期间回退。无需修改/devel中的正式二进制。
- 保留全部编译/故障注入中间日志与独立测试目录，无自动commit/push。
