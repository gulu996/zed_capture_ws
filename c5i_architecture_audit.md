# C5-I-A 架构审计

本轮只完成软件实现与离线验证，未启动相机、雷达、GNSS串口或联合实机采集。C5-I-B暂未实施。正式C5-G冻结。

## 原调用链与问题

`clock_diag/run_joint_test.sh → joint_test.py → scripts/start_capture.sh → scripts/session.py → zed_capture_node`。
原session.py在节点结束、子进程收尾后自动执行check_recording.py；joint_test.py随后读取完整检查、分析设备时钟并再次读取bag诊断。现场入口不能直接包装旧命令后强行中止检查，否则会混淆收尾和检查。

原节点：唯一bag writer、有界256MiB任务队列；JPEG独立编码/文件线程，两个4对队列、写队列32MiB、C5-G增量事件槽32；GNSS流式原始证据与现有5类消息；IMA1/失败poll完整保留。沿用节点1Hz磁盘余量检查（10GB储备加队列和64MiB）、5秒checkpoint、8,000,000,000字节bag保护和最长300秒限制。

原正常退出顺序：视频/HID生产者join → GNSS stop/done/ack与消息数量握手 → spinner停止 → IMA1 reader join → 唯一writer排空 → JPEG线程排空/最终同步 → bag及sidecar关闭/fsync → bag.active更名 → 会话目录fsync → capture_summary。

审计发现默认ROS SIGINT处理会触发ROS shutdown，而GNSS收尾仍依赖订阅回调。**这属于源码确认的停止路径风险，未声称已在真实硬件复现丢失。** 独立候选采用NoSigintHandler和sig_atomic_t停止请求，使ROS可继续完成GNSS握手。原正式节点不变。

## 新的独立路径

`diagnostics/field_capture/start_capture.sh → field_capture.py后台manager → session_field.py → diagnostics/field_capture/build/lib/zed_capture/zed_capture_node`。

独立配置：`diagnostics/field_capture/capture_hd720_c5i.yaml`。内容与原C5-G YAML逐字节一致，仅选择入口不同。

候选节点复用原静态capture_oc/hidapi库和**字节相同**的JPEG插件复制件，只新增停止标志检查和少量阶段元数据。未修改JPEG算法、质量、线程数量、队列、GNSS解析器、Livox、IMA1、时间映射或clock算法。

时钟使用原clock_monitor二进制，15秒前监测、采集及完整收尾、15秒后监测，保留clock_samples.csv、three_clock.csv硬链接、clock_adjustments.csv、monitor summary及timesync前后只读快照。时钟计算延后至手动检查，结束时CLOCK_DIAGNOSTIC=PENDING_OFFLINE_ANALYSIS，绝不假设PASS。

## 观测开销与边界

现场manager每秒原子替换小型capture_status.json；只读原metrics尾部64KiB、JPEG进度尾部64KiB、GNSS checkpoint尾部64KiB，增量读frames.csv每轮最多256KiB。单行上限64KiB；只保存计数及有限状态。无bag遍历、无JPEG文件目录扫描、无新增图像缓存。
JPEG已编码计数是已落入终态索引的可观测计数，**不含尚在途任务**；GNSS ROS写入计数来自5秒checkpoint。显示观测时间，未知值为null；终态采用原summary核对。1Hz显示不意味着所有源计数精确到同一时刻。

阶段元数据约6次/会话，由候选节点主控制线程写入原子小文件，无逐帧新增写入。软件未测量实机额外CPU或抖动；不能称零开销。

## 限制

C5-I-A只接受显式0<duration<=300；不指定时长直接拒绝并提示CONTINUOUS_MODE=PENDING。未实现bag分段；仍受8GB保护。20分钟、持续模式、分段边界测试属于C5-I-B，未开放。
设备占用检查只观察当前proc命名空间；GNSS仍依赖原独占串口，ROS检查拒绝重复发布者，原驱动错误不忽略。禁止同时人工启动旧命令与新命令；独立lease可阻止多个现场入口，但不能强制旧启动器遵循新lease。
