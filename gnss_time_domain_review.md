# GNSS时间域复核

状态：**语义审计VERIFIED；真实串口时间HARDWARE_PENDING；GNSS↔MID测量时间映射UNRESOLVED；PHYSICAL_SYNC_PENDING**。

## 必须分开保存的时间

|值|当前依据|限制|
|---|---|---|
|GNSS测量UTC|原KSXT/RMC/ZDA文本及parser.utc_ns；GGA借助日期状态|不是主机接收时间；原浮点解析存在亚微秒舍入，完整原文必留|
|串口接收MONOTONIC|新探针os.read返回后独立clock_gettime|包括USB缓冲/内核调度/用户读取延迟，不是PPS|
|串口接收MONOTONIC_RAW|RAW_before→MONOTONIC→REALTIME→RAW_after|顺序采样，夹取宽度记录；禁止称精确同时|
|接收REALTIME|time.time_ns整数，非rospy仿真时间|墙钟可调，不作为GNSS历元覆盖值|
|MID设备时间|保留原CustomMsg/IMU及IMA1锚点|GPS/type=2不保证虚拟GPRMC日期等于真实GNSS日期|
|映射有效性/版本/不确定度|探针valid=false、version=0、uncertainty=null|null表示未知，不能填0假称零误差|

每read chunk保存字节偏移、read前MONOTONIC与返回后的RAW夹取/三钟；完整行绑定含终止符chunk。同chunk内多条记录可能有相同接收时间，这不是测量历元重复。跨协议GGA/KSXT/RMC同历元重复正常，连续性须按source与原历元分别评价。保留boot_id避免跨重启混用。

## 旧节点字段存在模式差异

`host_receive_monotonic_ns` 在livox_imu_anchor模式实际为CLOCK_MONOTONIC；host_local模式实际为CLOCK_MONOTONIC_RAW。同名字段不能假定同域。host_receive_stamp为rospy.Time.now()（受use_sim_time影响）。旧代码在完整行_handle_line时取时，而非USB字节物理到达时。新sidecar明确分开三个时钟，不改旧消息MD5。

`RawSerialFrame.header.stamp`为映射后的接收local时刻，失败时零。pvt.utc_measurement_ns保留解析UTC；pvt.local_measurement_ns在anchor模式却采用映射后的接收时刻，尽管字段名叫measurement。mapping_version在该模式为0，time_state=LOCAL_ONLY，timestamp_source=HOST_RECEIVE_LOCAL。valid_for_fusion=True是旧软件条件，不代表真实测量同步通过。

## 旧IMA1映射的实际公式

sensor_time_bridge/imu_anchor.py：

```
D_receive = anchor.imu_stamp_ns
          + (GNSS_receive_MONOTONIC_ns - anchor.host_monotonic_ns)
          - configured_time_offset_ns
```

这是局部斜率1的 **接收时刻映射**，没有使用GNSS测量UTC。双读seqlock稳定性、ready、clock_source、epoch/单调性/20ms告警/100ms有效年龄均有检查，但不估计串口传输时延、接收机输出延迟、PPS关联或主机非线性速率。输出uncertainty主要继承anchor值，不是GNSS测量到MID的完整误差界。

旧anchor模式无有效映射时会丢弃有效位置PVT（原raw/status继续），不满足“先保留全部原始/PVT再离线处理”的最终目标。host_local在无桥服务时保留有效位置PVT，但local_stamp=0/valid=false；已用合成测试验证，仍不能直接作为正式融合输入。

host_local另有UTC逆映射：local_reference + (UTC−UTC_reference)/slope。其依赖外部TimeMapping，仅基本检查version、状态、正斜率、单调性；不能凭现有服务名称推断已经建立真实GNSS UTC与MID虚拟日期的测量关联。本轮不启动旧时钟桥、更不重写L2-B。

## 本次前置风险

C5-F会话20261018_141750_265b3cbf中MID type2；既有UTC样式MID锚点为1590192...ns（2020日期），主机REALTIME为1792304...ns（2026）。本轮尚无真实GNSS串口UTC可对照，不把主机墙钟等同接收机UTC。日期相差是需要分别建模的域差异，绝不能用UTC−MID直接算校正offset。

同会话有效三时钟观测显示实际视频窗口MONOTONIC−RAW约变化−5.00ms，时钟质量FAIL。GNSS接入必须保留这个证据；RTK Fixed与接收时钟变化无逻辑等价关系。

## 最小接入约定（设计，尚未实施）

新增采集适配层重用旧parser/消息定义，增加三钟raw sidecar；保留原始协议质量码、UTC文本、parser版本、checksum_audit。未建立可信测量映射时，local_measurement_time_valid=false、valid_for_fusion=false、mapping_version=0，原测量UTC仍保留。若暂复用接收anchor结果，只能标成RECEIVE_TIME_MAPPING，并与MEASUREMENT_MAPPING_PENDING分开；不把继承anchor不确定度宣称完整GNSS时间精度。

待本机真实语句确认后再决定AGRICA CRC与协议质量适配的最小实现，必须在独立工作空间，不修改原msg、因子图、Livox、STM32或既有L2-B核心。UTC文本精确整数解析如增加，先以独立诊断字段保存与旧parser差值，不能静默改变旧数据。
