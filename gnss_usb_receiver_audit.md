# GNSS USB接收机审计

结论：**SOFTWARE_TESTED；HARDWARE_PENDING**。只读审计旧工程、运行无设备回归和合成离线bag测试；未启动完整C5-F、ROS Master、Livox或GNSS融合节点。未安装依赖。正式采集及catkin_ws未修改。

## 来源与保护

本机 `/home/jetson/catkin_ws` 的origin为 https://github.com/gulu996/FAST-LIVO-UG.git，HEAD为 `d62f4ca38b9dea19041919de090e5d4d7d36d1ea`。本轮直接审计本机部署代码，未拉取远端或把远端HEAD当作部署版本。仓库已有大量FAST-LIVO2等未提交修改，原样保留。证据与哈希在 `diagnostics/gnss_usb/audit_baseline.json`、`protection_check.json`。

rospack确认以下五包均在原workspace/src存在且可解析：gnss_serial_driver、gnss_comm、sensor_time_msgs、sensor_time_bridge、sensor_recording_bringup。Python生成消息可导入，不需重编原workspace。

## 实际USB与访问范围

sysfs确认 `0483:5740`，序列号 `5CF253593333`，产品STM32 Virtual ComPort，路径 `usb1/1-2/1-2.1`、12Mb/s；ttyACM0关联身份一致。沙箱 `/dev/ttyACM0` 与 `/dev/serial/by-id/` 均不可见；没有尝试绕过、改权限、扫描波特率。实际串口输出、设备端协议/实际RTK状态均PENDING，不能把节点不可见报告为接收机损坏。

独立工具仅使用指定by-id路径，校验USB三元身份，不回退到任意ttyACM。固定921600、DTR=true、RTS=false，打开后读取termios/调制解调器状态确认。读回波特率是主机端设置证据，尚须以真实连续输出确认接收机链路。

## 旧实现的行为与限制

- `exclusive_serial.py`：非阻塞open、flock排他、raw termios、921600/DTR/RTS。原flock只是协作锁，没有TIOCEXCL；不能阻止不遵守flock的其他读取程序。
- `_run_serial`：1024 bytes/read，空/EAGAIN后等待5ms，8192字节行缓存。ASCII replacement/strip后发布，原raw.data不含原CRLF，不保证逐字节等价串口流。raw_log/parsed_log采用追加行缓冲文本。
- 原错误路径重连约1秒；line_buffer在外层定义，断连后没有清空，存在拼接跨连接残行风险；os.read返回空串按暂时无数据处理，物理拔插恢复未实测。本轮不修改旧驱动。
- 支持KSXT、GGA、RMC、ZDA、GST、GSA、AGRICA、legacy JSON；不支持的原始消息仍需保留。
- NMEA/KSXT按`$...*XX`异或校验。AGRICA函数直接设checksum_valid=True，未验证CRC；legacy JSON也无传输校验。不得宣布这些记录校验通过。
- GGA质量5得到quality=5/carr_soln=1，但GnssStatus.RTK_FLOAT常量为3；source raw quality直接写入status，并非统一归一化枚举。KSXT也沿用同一质量映射，不能在无真实协议依据时确认其RTK分类正确。必须保留source、原质量码及原句，再核对各协议含义。
- UTC先经datetime.timestamp()浮点转换。合成微秒测试发现整数纳秒相对十进制参考差+24、−16、−208ns等；这不是传感器时钟异常。本轮不改旧解析器，保留完整UTC文本。GGA依赖最近RMC/ZDA/KSXT日期，无独立跨午夜保障；秒60被min(...,59)处理，闰秒也未可靠表达。

## ROS兼容性：VERIFIED（本机源码与生成消息）

|原话题|原类型|MD5|
|---|---|---|
|/gnss/raw|sensor_time_msgs/RawSerialFrame|`b3f0843fc91b42663f3ec3c977e3095b`|
|/ublox_driver/receiver_pvt|gnss_comm/GnssPVTSolnMsg|`d18171357d7a159f76d4d7c0b12fb631`|
|/gnss/pvt_local|gnss_serial_driver/GnssPvtStamped|`bdfb1e39cf636dda7ac090d7feb65573`|
|/sensor_time/utc_observation|sensor_time_msgs/UtcObservation|`55266fcd72cb453b63ebcad49e53171a`|
|/gnss/status_v2|gnss_serial_driver/GnssStatus|`89bd2929a7a8274c1f46b1f399c930ec`|

源`.msg`计算MD5和导入类MD5全部一致；未修改消息定义。不能据此声称与任意未检查远端/旧bag版本一致。兼容PVT只有GNSS week/tow，无Header；pair/source_sequence关联必须依赖其他消息及sidecar。

额外适配器：gnss_serial_driver/gnss_adapter订阅pvt_local，发布 `/gnss/enu_odom` nav_msgs/Odometry，仅处理local_time/valid_for_fusion有效数据；当前不启动。FAST-LIVO2还有单独融合适配器 `/gnss_fusion/enu_odom`、`/gnss_fusion/status`，不是采集必需项，不动其算法。

旧session_recorder实际启动rosbag record，含GNSS/UWB/时钟桥和建图相机旧话题；旧列表未完整含utc_observation。不能整套record_all.launch复用到C5-F，也不能让它与现有唯一写入器共同打开sensors.bag。

## 软件验证

- 旧parser 7项、GNSS anchor 3项、通用anchor 17项，共27项通过。
- 新独立测试7项：分块/原字节关联、校验失败与未知CRC、断连清残行、缓存上限、占用拒绝、TIOCEXCL先于设备设置、三时钟整数读取，通过。
- 重用旧节点_handle_line发布逻辑，以内存publisher代替ROS网络，生成独立 **SYNTHETIC** 小bag：raw4/status4/UTC4/localPVT2/compatPVT2，共16条，五类型MD5一致、全记录反序列化通过。无Fix输入原始记录仍保存；无映射时host_local模式PVT仍保存并明确无效。不代表实际串口/ROS socket/联合采集通过。
- 不需要编译C++或catkin；新增Python已做语法检查，shell已bash -n。

结果在 `diagnostics/gnss_usb/software_results/`。新工具独立于生产：independent_probe.py、run_independent.sh、software_test.py。只复用旧解析器和BAUD定义，独立串口打开保护先fuser检查、flock+TIOCEXCL，再设置指定参数；不发送接收机命令。fuser与open间无法完全消除第三方既有句柄竞态，运行时仍须保证没有另一个读串口程序；工具不杀进程。

## 下一步仅需独立实机测试

普通jetson SSH终端执行（不使用sudo）：

```bash
/home/jetson/zed_capture_ws/diagnostics/gnss_usb/run_independent.sh --duration 15
```

不需要ZED或MID供电，不启动ROS Master或完整C5-F。输出唯一GNSS_DIR，保存serial_raw.bin、chunks.jsonl、lines.jsonl、summary.json；完整原始字节含CRLF/无效消息，所有原始字节偏移和完成行的三时钟夹取可追溯。最多8192字节行缓存，超长行不解析但字节仍留bin；断连清残行与日期状态、有界重连，异常日志保留。不人工拔插也可先测试；真实断线恢复仍需另行验证。

工具最终RAW_RECEPTION_OBSERVED只表示收到字节，不能冒充所有协议解析/校验/RTK/时间通过。需回读输出后再确认协议分布、校验失败、每协议UTC连续性和质量状态；室内非Fixed不是启动门禁。串口忙/身份不匹配/不可访问则退出，禁止改权限绕过。
