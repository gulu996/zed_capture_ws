# C5-I-A 采集与检查分离

## 阶段

CAPTURE：原采集节点读取和保存全部JPEG、MID、GNSS、IMA1及原始时间证据。

FINALIZATION：先停止生产者，保留ROS回调直到GNSS stop/done/ack结束，再关闭spinner、排空writer/JPEG、关闭及同步数据。候选session manager等待所有自己启动的子进程自然退出，不限时强杀；既有Livox/ROS Master被复用时不归它所有，也不停止。

FULL_STRICT_CHECK：只有用户手动调用check_capture.sh时启动。原scripts/check_recording.py和所有C5-H实现未修改；完整解码、SHA256、全bag反序列化、GNSS关联、IMA1和原严格判定全部保留。

## 结束摘要

新会话保存capture_finalization.json、capture_status.json、field_identity.json、field_runner_status.json、field_node_status.json、field.log、capture_terminal.log、field_software.json及原始C5-G结构。

BAG_FINALIZED依据节点关闭/fsync结果、最终bag存在且无.active；JPEG_FINAL_SYNCED依据原JPEG最终同步/线程join报告；GNSS_FINAL_SYNCED依据原接收机无持久化错误、done/ack、writer完整计数和原始文件长度。这些是**关闭确认**，不是全文件正确性证明。

正常结束输出CAPTURE_RUNTIME=PASS、FINALIZATION_STATUS=FINALIZED和各同步字段；失败、未启动、无法确认分别明确记录。始终FULL_STRICT_CHECK=PENDING、DATA_INTEGRITY=PENDING、L2B_MAPPING=PENDING、PHYSICAL_SYNC=PENDING。JPEG/锚点等已知异常不被删除。

实际收尾完成后仍保留15秒时钟后监测和只读timesync快照，随后manager退出；这段不是FULL_STRICT_CHECK，也不计入用户指定录制时长。系统命令有单项12秒超时，状态可能短时STALE，不能承诺按停止键瞬间退出。

## 手动完整检查

```
/home/jetson/zed_capture_ws/diagnostics/field_capture/check_capture.sh --session <SESSION_ID>
```

也支持`--session-dir <绝对路径>`。拒绝活动manager、身份不一致、缺少完成报告、bag.active或未完成JPEG/GNSS同步。读取历史C5-G时也核查control.json中的进程启动标识和原最终同步证据。异常但已安全关闭的数据仍可接受严格检查，并诚实输出FAIL。

输出为`diagnostics/field_capture/checks/<SESSION_ID>_<时间>_<随机ID>/`，原会话只读，不覆盖旧结果。field时钟证据存在时额外调用原clock_analysis/adjustment_analysis，结果与数据完整性分开。无硬件重采、无全量输出JPEG、无数据传输。

## 原五分钟会话回归

源：20261018_185527_61ca19f8。
新输出：diagnostics/field_capture/checks/20261018_185527_61ca19f8_20261019_134357_7971e184/。
FULL_STRICT完成，返回码2为真实严格FAIL，不是运行器故障。比较424,070个叶子字段，仅offline_read_seconds不同。JPEG8988对、原12次长间隔、最大133.397ms、402个漏更新、GNSS计数和全部原异常保持一致。
本次总检查229.306秒、峰值277.941MiB（284612KiB）。这不是性能优化宣称；本轮只是把这段耗时从现场收尾中移走。
