# C5-H 检查器只读性能审计

输入：`/home/jetson/zed_capture_data/20261018_185527_61ca19f8`。本轮无新实机采集，无原始bag/JPEG/sidecar修改。证据目录：`/home/jetson/zed_capture_ws/diagnostics/zed_c5h/work_20261018_192501`。

## 原475.085秒记录的边界

历史`offline_read_seconds=475.0852157520021`并非精确端到端时间：源码在GNSS检查及报告JSON输出之前设置此字段。历史没有记录检查器峰值RSS；C5-G采集进程组282MB不能作为检查器RSS。本轮另启独立进程复测保存的旧版源码，获得新测量，不能冒充历史测量。

旧版本轮完整check耗时497.583秒，包含JSON输出的总耗时498.636秒；峰值RSS 1275.539MiB。

| 旧版阶段 | 实测秒 | 审计说明 |
|---|---:|---|
| 全量JPEG审核 | 233.418 | 17,976张逐文件读入、SOF检查、OpenCV全解码、SHA256；不是重复解码 |
| 主bag迭代/反序列化 | 212.023 | 528,576条消息；60,339,168个点逐个构造Python CustomPoint |
| GNSS独立检查 | 17.276 | 再次打开sensors.bag遍历30,262条GNSS；所在bag chunks再次读取 |
| V4L2/HID审计 | 5.709 | 两套CSV字典整表、positive子列表、关联列表同时驻留 |
| 时序统计 | 0.305 | 多个CSV整表及重复分位数计算 |
| 锚点候选覆盖 | 0.114 | 锚点列表、good子列表及host数组；bisect关联 |

阶段并非所有互斥操作的完整分解。bag迭代计时不含调用方字段检查、部分索引构造和中间数据整理；剩余时间不能直接归因于磁盘。

## 原内存增长结构

- 所有带Header话题都积累时间列表，即使最终只统计五个流。
- anchor_bag、anchors整表、sidekeys、good/host重复存储同一历史。
- IMU原始CSV、时间分段CSV、bag分段JSON、sample_id集合及列表同时驻留。
- analyze_io_diagnostics整表保留121,567个HID事件和原始HID字典，多份临时列表进一步放大内存。
- JPEG frames/video列表、元数据dict、seen/set、两目keys、verified SHA列表都线性增长。
- GNSS原始文件、chunks、lines、bytes.join及bag关联重复副本。
- rosbag库读取时的全消息索引本身仍是O(N)；不是bag逐消息yield即可消除。
- 最终报告保留全部索引和哈希，因此输出磁盘空间必然随数据增长；joint外层仍会读入并嵌入报告，本轮没有重构该外层。

未在当前完整验收主要路径发现必要的O(N²)循环。主要问题是高常数逐点对象构造、重复bag扫描和同时存活的O(N)字典。锚点原bisect为O(V log A)，应用排序为O(V log V)。独立旧analyze_real_session.analyze中按异常搜索最近事件不是本次check调用路径，未据此声称475秒来自该搜索。

JPEG本身每张只解码和哈希一次，不是通过跳过重复图像解码获得收益；新版仍逐张完整解码。GNSS raw SHA原来算两次，新版只算一次并复用结果。

## 测量方法与偏差

旧版和新版为不同Python进程、相同Jetson和真实输入；使用monotonic计时、ru_maxrss及/proc/self/io。没有清除系统缓存、安装工具或改变CPU/NTP设置。先旧后新，页面缓存与后台调度不同；read_bytes降低不能全部归因于算法优化。

rchar是系统调用逻辑读取量（包含库及临时索引读），read_bytes是内核归属的实际存储读取量，二者不能混为原始输入唯一字节数。性能结果是本次观测，不承诺固定加速倍数。
