# C5-I-A 会话生命周期

## 操作命令

先做一次受控短时硬件验证（本轮没有执行）：

```
/home/jetson/zed_capture_ws/diagnostics/field_capture/start_capture.sh --duration 30
```

前台只是观察器；Ctrl+C请求优雅停止。SSH SIGHUP/输出连接断开退出观察，不触发停止。再次Ctrl+C退出停止等待，后台manager仍继续安全收尾。

显式后台模式：

```
/home/jetson/zed_capture_ws/diagnostics/field_capture/start_capture.sh --duration 30 --detach
```

新SSH终端查询与停止：

```
/home/jetson/zed_capture_ws/diagnostics/field_capture/status_capture.sh --follow
/home/jetson/zed_capture_ws/diagnostics/field_capture/stop_capture.sh
```

status的Ctrl+C只退出观察。也支持status --json、status/stop --session ID、stop --timeout 120。

只有短时硬件采集、停止握手和完整检查确认后，再手动采用：

```
/home/jetson/zed_capture_ws/diagnostics/field_capture/start_capture.sh --duration 300 --detach
```

不指定duration会明确拒绝，CONTINUOUS_MODE=PENDING。原C5-G命令及默认配置未变，明天正式采集可继续使用已实测旧版本；新候选不自动部署。

## 后台管理

start持有runtime/hardware.lock排他flock，创建唯一会话和随机token，再用start_new_session=True启动manager，stdin=/dev/null，stdout/stderr=field.log。manager与传感器子进程不继承SSH终端；后台进程忽略SIGHUP。锁fd传给manager、runner及其子进程，启动客户端关闭自己的fd后锁仍有效。正常关闭最后所有者才释放。

会话身份持久保存：SESSION_ID、绝对路径、token、boot_id、manager_pid、/proc启动ticks、pgid、日志路径。runtime/current.json指向最近会话；每次身份核查。新启动拒绝现有lease或活跃manager；设备/ROS重复检查继续执行。状态从不作为原始传感器数据替代。

阶段：PREFLIGHT → CLOCK_PRE_ROLL → INITIALIZING → RECORDING → FINALIZING → CLOCK_POST_ROLL → FINALIZED/FAILED。初始化被取消且未启动采集为CANCELLED_BEFORE_CAPTURE。节点另报STOPPING_PRODUCERS、GNSS_HANDSHAKE、DRAIN_BAG_WRITER、DRAIN_JPEG_AND_SYNC、CLOSE_AND_SYNC_BAG_SIDECARS、NODE_FINALIZED。

录制时间使用原input_watchdog的capture_start_monotonic_ns；与启动等待分离。最终elapsed采用候选节点停止生产者前的单调时间，不把15秒时钟后监测算作采集时间。原节点duration计时规则不变。

## 异常边界

心跳超过5秒显示STALE/UNKNOWN；manager不存在或身份变化显示MANAGER_LOST/UNKNOWN，不能认定成功。意外manager消失时不自动收养、杀死子进程或解锁；剩余子进程可能仍持lease。确认残留进程和数据之前拒绝再次启动。

磁盘/设备/写入故障仍走原节点安全停止；新增状态文件失败不能打断runner的清理。manager无法写停止请求时，仅向它直接持有且尚未wait回收的runner发送SIGINT，由候选正常收尾，不信任外部PID。

C5-I-A只有300秒上限与原8GB预算，没有bag_segments.json，也不支持跨段采集。B须单独实现和验证后才开放。
