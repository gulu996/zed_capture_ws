# C5-I-A 启动竞态修复与本次真实失败分析

本次读取实际会话：20261019_140259_652368e4。未新采集、未删锁、未发送停止/强杀信号、未修改历史会话。

## 前台启动器错误：已修复 / SOFTWARE_TESTED

这是新增现场启动器的检查遗漏。launch()先持久化预留身份（manager_pid=null），Popen后台manager后立即调用manager_alive()；子进程尚未注册PID时，int(None)抛TypeError。前台退出不会停止已经setsid启动的后台manager。因此再次启动被仍有效的hardware.lock拒绝，符合防重复采集保护。

field_common.py：空PID、非正整数PID、缺失/无效start_ticks直接视为尚未注册或无效，不访问/proc；仍保留boot/start_ticks/命令行核查，不把无效PID作为可停止对象。
field_capture.py：在后台启动前打印SESSION路径，即使观察器失败也能找回会话。
test_field.py：新增预留身份边界，以及实际launch等待循环的确定性回归（前三次轮询保持null，然后注册；只允许一次Popen）。未调用真实设备。

28项测试通过。此前测试直接进入已注册的manager，遗漏了父启动器这一竞态；本次补上该路径。源码改前备份、SHA256、修改diff及测试日志见：
/home/jetson/zed_capture_ws/diagnostics/field_capture/startup_race_fix_20261019_140522

正式C5-G的83项受保护SHA256均保持不变；本轮没有重新编译或替换任何采集二进制。当前发布清单更新，原清单已备份。

## 后台真实采集：FAIL，与空PID异常分开

后台实际运行约11.837368421秒，非用户中断（interrupted=false），returncode=2。
- 视频接收356对，无视频长间隔、无sequence缺口。
- JPEG编码356对；写入355对；第356对WRITE_QUEUE_REJECTED；编码拒收0、编码失败0、文件写入失败0。
- 写队列峰值4，达到原容量；内存字节峰值约1.07MB，远小于32MiB字节上限。
- MID点云134、MID IMU2672；未执行全量连续性检查，不能仅凭计数声明完整。
- GNSS原始51342字节，接收机报告无持久化错误，done/ack存在；发布1522条，bag写入1518条，四个有消息话题各拒收1条。
- bag已正常关闭；JPEG线程join、最终同步成功；整体FINALIZATION_STATUS=FAILED，因为GNSS writer计数不完整。
- GNSS_FINAL_SYNCED=false是现有综合验收结果，不能解读为原始serial_raw.bin必定未同步；原接收机单独报告RAW_RECEPTION_RECORDED。
- FULL_STRICT_CHECK、DATA_INTEGRITY、L2-B、物理同步保持PENDING，未自动进行耗时完整检查。

## JPEG写入拒收的直接时间轴

全部为原CLOCK_MONOTONIC整数ns：

| 事件 | 时间 |
|---|---:|
| 第351对写完 | 3089353360711 |
| 周期同步开始，64个文件 | 3089353397105 |
| 第352对编码完成 | 3089385421959 |
| 第353对编码完成 | 3089418874291 |
| 第354对编码完成 | 3089454077778 |
| 第355对编码完成 | 3089485468884 |
| 第356对编码完成并被写队列拒收 | 3089519034816 |
| 周期同步结束 | 3089595755329 |
| 第352对开始写入 | 3089600623594 |

该同步区间242.358224ms；summary的max_sync_ns=247172745还包括syncBatch后续进度同步等操作，二者计时边界不同。

源码的同一JPEG writer在线程内执行syncBatch。它同步期间，第352–355对依次编码完毕且尚未消费，队列已占4对，第356对触发原BUSY/FULL/BYTES拒收保护并引起采集失败。这是可从原记录重建的直接机制。同步为何出现约242ms停顿（存储flush、调度或其他系统负载）仍UNRESOLVED；未据此猜测具体磁盘或系统故障，也未宣称新增现场管理器是唯一原因。

采集全局failed后，原RecordingQueue会拒绝新任务；GNSS收尾期间四条消息被收到但未入队，计数与这一源码路径吻合。没有静默抹除该缺失。

## 当前状态与下一步

检查时field_runner_status=CHILDREN_EXITED、owned_children为空，最终状态FAILED；非阻塞flock检查确认lease已经释放，未删除或重建锁文件。

启动器空PID竞态已修复，但本次30秒实机验证未通过。不要将修复启动器等同于已解决JPEG写入积压；暂不推荐新入口直接进行300秒户外录制。原已验证C5-G保持冻结。

可读取本次状态：

```
/home/jetson/zed_capture_ws/diagnostics/field_capture/status_capture.sh --session 20261019_140259_652368e4
```

下一项实际阻塞为JPEG周期同步期间有界写队列耗尽。需要单独审计/设计最小修复和测试；本轮未扩大队列、未放宽门限、未修改JPEG算法或同步策略，未启动新的测试采集。
