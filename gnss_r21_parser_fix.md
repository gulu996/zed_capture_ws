# GNSS-R2.1 截断GGA恢复修复

状态：SOFTWARE_VALIDATED。仅离线开发与测试，未打开串口、未启动ROS Master/传感器或新联合采集。软件结果不覆盖历史实测结论。

## 真实依据与修复范围

原会话：`/home/jetson/zed_capture_data/20261018_174130_d85a69b1`。
父记录source_sequence=22，字节[2058,2101)，原始内容为：
```
$GNGGA,,,,,,0,,,$GNRMC,,V,,,,,,,,,,N,V*37

```
损坏GGA：字节[2058,2074)，全部在chunk3；RMC：[2074,2101)，全部在chunk4。父记录整体XOR计算0x47、收到0x37，校验失败；内部RMC单独XOR=0x37正确。旧R1只恢复受限AGRICA→RMC，故本条RMC未独立分类。无法由这些字节确定截断发生的硬件/传输层。

本次只修改一个已有生产适配文件：`diagnostics/gnss_r2/gnss_r2_core.py`。新增独立兼容层`gnss_r21_compat.py`和回归/重放工具`test_gnss_r21.py`。vendored GNSS-R1原件及SHA清单完全不变，未修改原catkin_ws中的旧驱动。

## 拆分规则

1. 先验证完整父报文；校验合法时原样返回，即使包含起始标记也不拆分。
2. 原R1 AGRICA恢复优先沿用，不更改CRC、UTC、质量码或恢复逻辑。
3. 新规则仅匹配**已观察到的空时间/空位置、质量0的GNGGA/GPGGA前缀**：`\$G[NP]GGA,,,,,,0,{1,8}`。
4. 后续必须紧接一条完整GNRMC/GPRMC，具有行终止符、两位十六进制XOR、12/13/14个字段及A/V状态；XOR必须正确。尾部不允许额外`$`、`#`、`*`、其他报文或垃圾。
5. 其他GGA损坏、未知前缀、任意负载、缺校验、错误XOR、不完整尾部均保持原始未恢复记录。没有补字节、排序、去重或无条件按`$`切分。

这是保守的已验证语法扩展，不宣称通用NMEA损坏恢复。新的定位有效GGA前缀等变体需另有证据和反例测试。

## 字节、时间和关联信息

分区完整拼接必须严格等于原字节。损坏前缀标记`TRUNCATED_GGA_BEFORE_VALID_RMC`，checksum无效、无PVT；RMC标记`RESYNC_AFTER_TRUNCATED_GGA`，checksum有效，但仍V/NO_FIX/无UTC。
两片段共享父source_sequence=22，拥有各自record_sequence及byte_begin/end。精确chunk_first/last分别3/3与4/4，新增parent_byte_begin/end、parent_chunk_first/last、parent_receive_clocks便于重建父记录。

为了不追改原记录的接收时间，`receive_clocks`仍保存父记录原末chunk4的时钟（MONOTONIC=14995774439123ns）。`fragment_receive_clocks`额外保留每个片段自身末chunk时钟：损坏GGA的chunk3为14995692797395ns，恢复RMC的chunk4为14995774439123ns。receive_semantics明确区分父时钟与片段时钟。两者都不是GNSS测量历元或PPS；原始chunks继续保存全部三时钟与夹取宽度。

新增chunk跨度跟踪上限受原8192字节分帧限制，最坏每字节一个span（最多8192项），每条结束即释放；不使用无界缓存。普通记录与原AGRICA恢复的既有解析/时间字段保持不变；新父子字段仅附加于新增GGA恢复。生产回调、bag writer、队列、JPEG、MID不变。

## 消息及时间边界

五类.msg和MD5均不变。损坏前缀和恢复RMC分别走既有RawSerialFrame/状态消息链路，副作用是本重放每类增加1条，而不是丢弃或重写原字节。恢复RMC无有效定位/UTC，所以PVT和UTC消息数不增加。
`local_measurement_time_valid=false`、`valid_for_fusion=false`、`mapping_version=0`，不确定度UNKNOWN；GNSS_MEASUREMENT_MAPPING=PENDING、PHYSICAL_SYNC=PENDING。不将主机接收时间当测量UTC，不与MID虚拟GPS日期直接相减。

## 修改前证据与回退

证据目录：`/home/jetson/zed_capture_ws/diagnostics/gnss_r2/r21_20261018_180214`。
`before/gnss_r2_core.py`为完整原文件，SHA见before_manifest.json。当前工作空间不是Git仓库，因此修改前git diff不可用的原始输出保存在before_git_diff.txt，并保存完整源码基线；实际前后差异见parser_change.diff。新兼容层/测试的最终SHA见protection_final.json。
如需回退，仅在无采集进程时，经核对文件未被后续修改后恢复此core备份即可重新使用原R1；新增兼容层和测试可留存不加载。无需删除任何历史数据，不涉及二进制替换或系统调整。本轮未执行回退。

71项受保护文件SHA未变，包含原配置、核心采集源码、可执行文件、JPEG库、脚本、三时钟代码、vendor R1及本次原GNSS记录。1851个历史会话文件大小/mtime未变。catkin原dirty状态检查保持一致。未安装依赖、未commit/push、未清理工作空间。
