# GNSS-R2 time semantics

本轮只正确记录，不建立GNSS测量UTC→MID映射。RTK Fixed、CRC通过、有效UTC分别是不同事实，均不等于硬件PPS或相机曝光同步。

## 时钟域

| 数据 | 存储位置和语义 |
|---|---|
| GNSS测量UTC | R1整数utc_measurement_ns、utc_candidate_ns、原始时间文本/字段；GnssPvtStamped.utc_measurement_ns、UtcObservation.utc_stamp_ns |
| 接收MONOTONIC | 每次os.read返回后的monotonic_ns；RawSerialFrame.host_receive_monotonic_ns |
| 接收MONOTONIC_RAW | RAW_before → MONOTONIC → REALTIME → RAW_after夹取，保存两端和宽度；不假定精确同时读取 |
| 接收REALTIME | 同一夹取中的realtime_ns；RawSerialFrame.host_receive_stamp及raw/status Header |
| bag record time | C++订阅回调接收的CLOCK_REALTIME，不作为GNSS测量时间 |
| MID设备时间/IMA1 | 原有Livox消息和锚点保持原状；本轮不与UTC直接相减 |

一条报文跨多个read时，记录首末chunk编号并使用末尾chunk的接收时钟作为到达证据；chunks.jsonl保存全部read边界/偏移，可重建其他关联。该时间不是首字节时间、GNSS测量历元或USB PPS硬件时间。raw字节SHA匹配证明保存了已读取字节，不证明USB/UART在到达用户态之前绝无丢失。

## 无映射时的旧ROS字段

- GnssStatus与GnssPvtStamped：local_measurement_time_valid=false、valid_for_fusion=false、mapping_version=0、time_state=0（未建立映射）。
- GnssPvtStamped：local_measurement_ns=0，Header.stamp=0，timestamp_source=INVALID；真实UTC另存。零Header是明确无效值，不是实际采样时刻。
- RawSerialFrame：Header和host_receive_stamp明确为主机REALTIME接收时间；timestamp_source=INVALID，不能将其当成已验证的本地/MID测量时间。接收MONOTONIC另有独立字段。
- UtcObservation：有有效UTC才发布；valid=false、local_stamp_ns=0、association_type=HOST_SERIAL_ASSOCIATED，detail解释UNMAPPED。不会冒充HARDWARE_PPS_ASSOCIATED。
- JSON不确定度=null/UNKNOWN；旧uint64不确定度字段只能填0，并配合上述INVALID/false。不能解读为零误差。
- GnssPVTSolnMsg无完整映射有效标志，其valid_fix仅表示接收机定位质量；不得单独依据它启用融合。仅R1已核验AGRICA GPS周/TOW/闰秒时填兼容week/tow，其他来源week=0、tow=NaN表未知。原整数UTC始终独立保留，legacy float64 TOW不替代它。

当前通用PVT中的椭球高度、导航速度、精度和PDOP保守NaN，原数值留在raw/R1 sidecar。旧GGA在geoid缺失时默认0的行为不能用来宣称椭球高已知；HDOP不填PDOP。KSXT/AGRICA高度基准不猜测。未知字段不能用于融合。消息定义和MD5不变。

## 保留的问题

- 历史100ms回退、重复测量历元：原序列保留，UNRESOLVED；没有排序、去重或用接收时间覆盖。
- R1只能判定其支持布局下的UTC/CRC/质量语义，接收时延、USB缓存、串口批量到达等不确定度仍UNKNOWN。
- MID当前GPS/type=2并不证明其虚拟GPRMC日期等于真实GNSS UTC。禁止将虚拟2020日期与真实2026 UTC直接相减；后续需要独立、经过验证的测量历元映射。
- L2-B图像→MID现有结果不等于GNSS→MID映射，887/903的既有图像映射结果不被本轮重算或推广。
- 原C5-F主机严格时钟诊断FAIL不变；本轮未重新采样系统时钟或调整NTP。MONOTONIC_RAW不会未经验证替换现有V4L2或Livox时间戳。
- PHYSICAL_SYNC_PENDING，禁止启动GNSS融合/正式FAST-LIVO2建图。本轮软件成功只允许准备一次受控30秒采集。
