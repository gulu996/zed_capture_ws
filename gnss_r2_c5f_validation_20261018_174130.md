# GNSS-R2 + C5-F 真实联合采集复核

采集会话：`/home/jetson/zed_capture_data/20261018_174130_d85a69b1`  
三时钟目录：`/home/jetson/clock_diag/runs/joint_20261018_174114_6a2cb4ed`  
本报告只读分析已有实测，不重新采集、不修改驱动或历史记录。机器可读复核：`/home/jetson/zed_capture_ws/diagnostics/gnss_r2/review_20261018_174130.json`。

## 结论

**本次30秒联合采集正常完成，JPEG、MID-360及GNSS原始记录链路成功；严格DATA_INTEGRITY仍FAIL，不能宣称已完成时间同步或可直接融合GNSS。**

| 项目 | 结论 | 证据/限制 |
|---|---|---|
| CAPTURE_RUNTIME | PASS | manager returncode=0，interrupted=false，failed=false，bag_finalized=true |
| JPEG_FILE_RECORDING / VIDEO_CONTINUITY | PASS | 902/902对、1804张JPEG，29.997892 FPS，长间隔0、sequence缺口0 |
| JPEG_ENCODING_DEADLINE | FAIL | pair97、161超过33.333333ms，未拒收或缺图 |
| MID360_CONTINUITY | PASS（可观察ROS层） | 316点云、6342 IMU，结构/序列/时间连续性检查通过 |
| GNSS_RAW_RECEPTION | PASS | 原始111834字节、750 chunks、1141记录，SHA256和bag交叉一致 |
| GNSS_PROTOCOL_VALIDITY | OBSERVED_WITH_INVALID_RAW_RECORDS | 1140/1141校验通过；一条截断GGA拼接RMC，原字节保留 |
| GNSS_POSITION_QUALITY | NO_FIX | GGA/AGRICA有效校验记录的质量码均0，无有效定位 |
| GNSS_UTC_VALIDITY | UNAVAILABLE_RAW_CAPTURE_ALLOWED | RMC时间日期缺失；AGRICA为UNKNOWN，不能生成有效测量UTC |
| GNSS_RECEIVE_CLOCK_VALIDITY | PASS（记录连续性） | 三种接收时钟均保留、无回退，非PPS或测量历元精度验证 |
| GNSS_MEASUREMENT_MAPPING | PENDING | local_measurement_time_valid=false、valid_for_fusion=false、mapping_version=0，不确定度UNKNOWN |
| CLOCK_DIAGNOSTIC | PASS | 1364样本、漏期限0，RAW夹取最大736ns |
| ZED_IMU_TIME_VALIDITY | FAIL | 首条无效可疑报告，2段；原始记录全部保留 |
| DATA_INTEGRITY | FAIL | ZED IMU异常、401个启动锚点更新漏读仍计入严格判定 |
| SLAM_REQUIRED_DATA_STATUS | PENDING_L2B_AND_PHYSICAL_SYNC | 必需传感器记录子项PASS不等于建图准备完成 |
| L2B_MAPPING / PHYSICAL_SYNC | PENDING | 本新会话未执行L2-B，不继承旧会话887/903结果 |
| READY_FOR_C5F_INTEGRATION | 原始记录集成已实测；GNSS融合PENDING | NO_FIX不阻止原始记录；解析恢复边界仍需后续处理 |

联合脚本script_exit_code=2对应严格验收FAIL，不是采集进程提前失败。监测器SIGNAL/SIGINT是联合脚本收尾停止，manager未报告用户中断。

## 会话与硬件身份

会话创建时间对应2026-10-18 17:41:32（Asia/Shanghai），请求30秒；目录名及joint关联一致。GNSS summary synthetic=false、serial_opened=true、errors=[]。
boot_id=`ff8152e2-8154-4b61-b8b0-b12d923250fb`。实际接收机VID:PID=0483:5740，serial=5CF253593333，/dev/ttyACM0，稳定by-id路径与配置一致，921600 baud、DTR=true、RTS=false。
配置为`/home/jetson/zed_capture_ws/src/zed_capture/config/capture_hd720_c5f_gnss.yaml`，SHA256=`526b1e83ede57e980fe80e71439c19f195bb85b6ae909013200b088750e68600`。
视频HD720/YUYV，JPEG 1280×720、Q95/420，USB视频5000Mb/s；未混用历史离线合成测试。

## GNSS字节、协议和五类ROS消息

独立重跑只读check_gnss：errors=[]。bin大小/SHA、chunk连续偏移、lines原始hex拼接、bag raw消息次序/source_sequence/接收时间一致。
SHA256：`dbdf7922bac9a73e9d9f1ca1a153bc0e2ac2515a4242617f266d58a141483a51`。
这里证明**已被用户态读取的字节**完整保存，不能证明接收机发出的每个串口字节都未在USB/设备侧丢失。
使用独立逐位CRC32（初值0、多项式0xedb88320、无末尾异或）及NMEA XOR复核，与sidecar校验结果全部一致。

| 协议 | 已分类记录 | 校验通过 | 校验失败 |
|---|---:|---:|---:|
| GGA | 327 | 326 | 1 |
| RMC | 162 | 162 | 0 |
| GSA | 163 | 163 | 0 |
| GST | 163 | 163 | 0 |
| UNIHEADINGA | 163 | 163 | 0 |
| AGRICA | 163 | 163 | 0 |

本次未观察到KSXT、ZDA，不能声称已在本次实机验证这些协议。AGRICA 163/163与UNIHEADINGA 163/163 CRC通过。
162条RMC parse_errors均为field_count_or_value，对应`$GNRMC,,V,,,,,,,,,,N,V*37`，校验正确但没有日期、时间或有效位置，不是原始字节丢失。GSA invalid_status等应用语义拒绝也必须与checksum失败分开。
GGA有效326条与AGRICA163条均NO_FIX（quality=0）；本次未实测Fixed/Float识别。不能把AGRICA无定位时的0,0经纬度当作真实位置。

**新增解析边界（VERIFIED）**：record/source_sequence=22，字节区间[2058,2101)，跨chunk3→4，在首个接收chunk后112.738288ms，接收REALTIME=1792316495818800346ns：
```
$GNGGA,,,,,,0,,,$GNRMC,,V,,,,,,,,,,N,V*37
```
整体XOR计算0x47，收到0x37，所以当前GGA记录判CHECKSUM_MISMATCH正确。内部RMC单独计算0x37，校验有效。R1 split_record仅对数值AGRICA→RMC实施受限恢复，故本条RMC未独立分类；原字节仍在bin、lines和/gnss/raw中完整保存。
该RMC也是V/无UTC，因此此次未损失有效定位或测量UTC，但**不能声称所有合法子报文都已恢复**。截断发生于设备输出、USB链路还是此前缓冲层无法由当前日志确定（UNRESOLVED）。本轮未修改解析器；后续可用此真实样例设计严格受限的GGA→RMC恢复测试。

| 话题 | received | enqueued | written | rejected |
|---|---:|---:|---:|---:|
| `/gnss/raw` | 1141 | 1141 | 1141 | 0 |
| `/gnss/status_v2` | 1141 | 1141 | 1141 | 0 |
| `/gnss/pvt_local` | 489 | 489 | 489 | 0 |
| `/ublox_driver/receiver_pvt` | 489 | 489 | 489 | 0 |
| `/sensor_time/utc_observation` | 0 | 0 | 0 | 0 |

所有话题serialization_errors/write_errors=0，published与bag读出计数一致，总3260条GNSS消息；writer complete=true。
四个有数据话题的datatype+MD5逐消息通过旧格式白名单检查。UtcObservation预检类型/MD5通过，但本次0条，不能声称本次五类均写入了实际消息；此前软件测试覆盖了第五类。UTC为空是无有效历元的明确结果，不是writer漏写。
489条PVT为带NO_FIX/无效标志的记录，并非489个有效位置。PVT local Header=0，无效映射标志保持false，未将接收时间填作有效测量时间。

## 时间语义与连续性

GNSS串口接收MONOTONIC跨度32.002628616s；MONOTONIC_RAW跨度32.001619680s；REALTIME跨度32.002625608s。三种记录均无回退，最大相邻read chunk间隔约123.004ms，RAW顺序夹取最大64.992us。chunk间隔不是GNSS输出丢历元数，也不是PPS精度。
接收时间从os.read后采样，行使用末chunk时刻；顺序读取的不同系统时钟不是同时采样。完整整数值和每次夹取宽度见JSON及原chunks/lines。

RMC日期/UTC文本为空；AGRICA头为GPS,UNKNOWN、week=1，日历字段全0；不能把这些字段转换为可信UTC。未生成有效UTC，历史100ms UTC回退/重复问题本次**无法检验**，仍UNRESOLVED。无有效UTC也意味着本次无法评价有效历元浮点舍入问题；代码保存整数/原文本不能替代实测覆盖。
接收REALTIME是主机时间，不是GNSS测量UTC；不计算真实GNSS UTC与MID虚拟GPS日期的直接差值。测量→MID映射仍PENDING、版本0、不确定度null/UNKNOWN；ROS数值0须结合无效标志解释，不代表零误差。

三时钟记录68.150072s，1364/1364样本，前监测15.024s、后监测至少15s。MONO−RAW变化+2.146776ms，仿射速率差+31.501291ppm，拟合残差RMS1.726us、最大3.912us，REAL−MONO变化−32ns，无无效桥接区间。
这支持本次主机时钟关系平稳；未复现历史309ms异常，不代表根因永久修复。ZED名义tick/MID时间仍约1.280257%比例差，诊断残差不能解释为物理同步精度，未修改tick常数或L2-B门限。

## JPEG、MID、锚点及严格完整性

902对均WRITTEN，最终同步完成、工作线程退出；编码/写盘失败0，输入及队列拒收0。编码队列峰值1、写入队列峰值2（553126字节）；原始YUYV未写入sensors.bag。
视频跨度30.035444s，最大间隔33.409ms，回退/重复/序号缺口/长间隔均0，左右目及原始整数时间对应。两次select超时均在首帧前；DQBUF/EAGAIN/QBUF错误0。
已有完整检查验证902对JPEG、元数据与SHA256；本轮复用该检查，不重新导出图像。

以下从frames.csv重新计算；转换/编码为双目合计，时间单位ms，写入时长不等同于逐帧持久同步时长：

| 时长指标 | P50 | P95 | P99 | 最大 |
|---|---:|---:|---:|---:|
| convert_ms | 7.374 | 8.221 | 8.571 | 11.106 |
| jpeg_encode_ms | 18.174 | 20.613 | 20.910 | 24.880 |
| submitted_to_encode_end_ms | 25.637 | 28.913 | 29.413 | 36.127 |
| file_write_ms | 0.679 | 1.062 | 1.239 | 1.367 |
| encode_end_to_write_begin_ms | 0.021 | 0.048 | 20.809 | 56.610 |

编码端到端超33.333333ms：pair97=36.126576ms、pair161=34.964523ms；排队分别0.061986/0.055586ms。未丢任务，无累积溢出；不把902/902完成解释为所有帧都满足deadline。周期同步最大88.997493ms，写入队列等待最大56.610040ms；当前有界队列吸收了等待，不能据此保证长期或断电完整性。

MID点云316帧，10.000016Hz；IMU6342条，199.988199Hz，无观察到的长间隔/回退/重复/点云结构或序号异常。timestamp_type均2，时钟源切换计数0。这是可观察ROS层连续性，不证明原始以太网包无丢失或物理PPS同步精度。

ZED IMU12191条，首条tick6321985、第二条20395615：名义设备时间跳549.751172s而主机仅1.595282ms；首条标INVALID_SUSPECT，其余12190条另段VALID_CONTIGUOUS。另sample3 tick_delta97对应3.789063ms，严格检查共2个长间隔。全段平均21.009Hz被启动跳变污染，不能据此断言实际HID读取仅21Hz。HID队列丢弃/记录传输错误/读取错误0；段有效性不等于物理同步或数据完整性。

保存6396个锚点状态，漏读401个，全部集中在首帧前、previous_ready=false的启动事件；视频期间和ready状态漏读0。严格锚点历史仍FAIL，不隐去401。902/902图像具备候选锚点包围，包围跨度最大6.080096ms；这是映射输入覆盖，不是L2-B验证通过。

## 容量与资源

全会话实际文件字节合计399018549（399.019MB，十进制）；JPEG 248694783（248.695MB），sensors.bag 135638247（135.638MB），GNSS目录 3108901（3.109MB）。目录块分配开销未计入；报告保存在会话之外。
相对旧C5-F会话20261018_141750_265b3cbf的381.832498MB，增加17.186051MB；其中JPEG场景载荷自身增加12.683518MB，不能把总增量全部归于GNSS。两次sensors.bag差1.192069MB也包含传感器计数变化。
本次受管子进程CPU峰值136.60%（单核100%）、RSS292.36MB、系统CPU峰值36.72%、块写峰值13.566MB/s；bag增长4.097MB/s仅指bag，不含JPEG。旧基线对应CPU128.88%、RSS242.18MB、块写13.457MB/s；峰值非同步采样且负载/场景不同，只能作描述比较，不能宣称GNSS独占CPU增量7.72个百分点或内存增量50.18MB。
本次未独立测出GNSS进程CPU、温度/功耗/降频，不能伪造数值。一次30秒通过不等于5分钟长期采集通过，现有30秒/固定事件槽限制未更改。

## 后续边界与保护

本次已经验证GNSS原始记录可与JPEG和MID并发。优先保留截断GGA+RMC样例，后续获得确认后再作最小解析恢复修复；等待有有效UTC/定位的数据验证测量时间，但不要求RTK Fixed才能采原始数据。不启动GNSS融合，不将本次NO_FIX无UTC数据误判成有效GNSS约束。
未重新采集，未修改C5-F、FAST-LIVO2、Livox、STM32、L2-B、三时钟或系统配置。仅新增本报告和独立JSON复核证据。会话/joint全部已有文件大小及mtime核对不变，session顶层sidecar及GNSS文件SHA256复核不变；bag仅以只读方式反序列化GNSS话题，不重写；未commit/push。完成本次分析后停止。
