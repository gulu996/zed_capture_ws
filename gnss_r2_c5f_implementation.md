# GNSS-R2 C5-F implementation

2026-10-18。本轮只做软件开发、编译、历史真实输入离线测试，没有打开真实串口、启动ROS Master或进行新实机采集。

状态：**SOFTWARE_VALIDATED / HARDWARE_PENDING**。GNSS→MID测量时间映射、物理同步均为PENDING。旧C5-F的严格主机时钟FAIL、历史100ms回退/重复历元UNRESOLVED不因本轮测试改变。

## 来源与备份

用户复制的 `diagnostics/gnss_r2/preparation_20261018_155919/incoming/gnss_r1_20261018/` 已按delivery_manifest.json核验79个文件，SHA256及大小均匹配；原R1九项回归在Jetson通过。
运行时原样复用 `diagnostics/gnss_r2/vendor/r1/gnss_r1_compat.py` 及其相对路径下的旧parser依赖。R1源码SHA256：`072498d9ba7c9112811ac69d601f763ca4e41748840ca4db7d2e248085678fd6`。不重写AGRICA CRC、RMC恢复、UNIHEADINGA分类或整数UTC算法。

修改前备份：`/home/jetson/zed_capture_ws/diagnostics/gnss_r2/implementation_before_20261018_1615`；其中hashes.json保存源码/二进制哈希，catkin_status.txt保存原工作空间dirty状态。迁移验证在 `preparation_20261018_155919/migration_verification.json`。

## 实际实现

- 新独立配置：`src/zed_capture/config/capture_hd720_c5f_gnss.yaml`。复制原C5-F配置，仅增加显式GNSS开关、by-id路径和921600/DTR=true/RTS=false参数。HD720/30、JPEG Q95/420、三对预热、30秒上限、原队列及完整性门限不变。
- `scripts/session.py`：GNSS开启时验证旧消息MD5和USB身份；已有GNSS发布者或已知GNSS融合/adapter节点存在时拒绝重复启动。仅新增一个独占串口子进程，不启动融合、第二个Master/Livox或第二个bag writer。关闭时传入`_gnss_enable:=false`清除可能残留的ROS私有参数，不加载GNSS类型/解析器或增加GNSS门禁。
- `diagnostics/gnss_r2/gnss_receiver.py`：by-id匹配0483:5740/5CF253593333，fuser、flock和TIOCEXCL检查；只设置已知参数，不发送接收机配置命令。使用TCSANOW，避免tty.setraw默认TCSAFLUSH丢掉待接收字节。串口仅在真实启动命令中打开，本轮没有执行。
- `gnss_r2_core.py`：围绕原R1的有界流式封装；CR/LF和原字节完整保留。恢复后的AGRICA/RMC共享source_sequence但分别有record_sequence；二者都是适配层计数，不冒充接收机内部序号。按原顺序保存，不排序/去重。
- `src/zed_capture/include/zed_capture/gnss_ingress.hpp`：精确topic+datatype+MD5白名单；不可变ShapeShifter共享所有权；五话题独立received/enqueued/written/rejected/serialization_errors/write_errors计数。
- `src/zed_capture/src/capture_node.cpp`：显式启用时增加五个订阅、GNSS原始流准备及3秒停流检查、收尾核对；仍调用原唯一bag writer写sensors.bag。视频/JPEG/MID处理代码及其时间戳不改。
- `recording_queue.hpp`：把原有有界入队和单writer排空循环提取成共用函数，供生产节点和离线测试调用，保留原锁、FIFO、容量和失败策略。没有新增bag writer或JPEG线程。
- `scripts/gnss_recording_check.py`和`check_recording.py`：仅开启GNSS时核对原始SHA/分区、消息类型/MD5、计数、UTC顺序、无映射标志；GNSS持久记录错误追加到严格FAIL。NO_FIX、UTC缺失和已保存的CRC失败本身不禁止原始采集。原严格图像/IMU/锚点判定不放宽。
- `CMakeLists.txt`、`test/gnss_writer_test.cpp`及独立目录测试：编译真实生产队列/ingress writer的bag往返测试；不需要ROS Master。

## 边界、生命周期与错误

GNSS读取块最多4096 bytes、待分帧缓存8192 bytes；超长/残留数据作为显式片段保存。统计分类最多64个加OTHER，避免异常文本造成分类表无限增长。ROS发布/订阅队列各128条/话题；单条入bag消息限制64KiB；原唯一writer仍为配置的256MiB上限，不扩大原队列。不使用JPEG的4096事件槽；30秒限制保留。

原始serial_raw.bin和chunks.jsonl先于解析/发布写入；CRC失败、NO_FIX、无UTC、解析失败不筛掉原始数据。读取断开或3秒无字节明确报错；本版停止该实验，**不自动重连并把两段伪装成连续流**。关闭前记录未完成片段，再重置R1日期上下文。短写循环处理，无进展/磁盘错误显式失败。

正常退出：相机/HID生产者停止→请求GNSS停止→保存残留、flush/fsync原始和sidecar→GNSS写出发布数量done文件→C++等待每话题接收数匹配后ack→停spinner→唯一writer排空→bag原有close/fsync/finalize。ROS有界传输可能拒收/丢弃，但数量与raw逐记录核对会使验收失败；不声称ROS队列绝不会丢消息。写入计数表示bag.write成功，持久化还必须同时满足bag_finalized和可读校验。

等待订阅者15秒、GNSS原始流准备10秒、正常停流保护3秒、收尾核对10秒；GNSS子进程55秒仅为故障退出上限，不是延长视频采集。任何收尾/发布/序列化/存储失败均记录。突然断电可能丢失未最终同步的数据，本轮不验证断电持久性。

每个新会话新增：

```
gnss/serial_raw.bin
gnss/chunks.jsonl
gnss/lines.jsonl
gnss/time_observations.jsonl
gnss/publication_events.jsonl
gnss/summary.json
gnss/stop, done, ack
gnss_receiver.log
gnss_software.json
gnss_writer_summary.json
```

主session.json和GNSS summary关联session/boot/writer_epoch/身份及配置。lines保存原始字节、偏移、首末chunk、原质量码、时间原文、CRC结果；time sidecar不替换原始字节。未知导航速度/精度/PDOP与椭球高度保守写NaN，原始高度/HDOP仍在报文和R1解析sidecar中。尤其避免旧GGA把缺失geoid默认0后冒充椭球高。

## 保护核查

`protection_check.json`：六份原配置、JPEG库、jpeg_files.hpp、storage_mode.py、clock_diag/joint_test.py哈希不变，原catkin_ws dirty状态不变。没有修改原GNSS .msg/MD5、FAST-LIVO2、Livox、STM32、L2-B、NTP、系统依赖；没有commit/push/reset/clean或覆盖历史数据。三时钟计算代码完全不动。

## 下一次单次30秒命令（未执行）

待用户批准并在普通Jetson SSH终端、传感器供电及串口无竞争的条件下执行：

```bash
/home/jetson/clock_diag/run_joint_test.sh --config /home/jetson/zed_capture_ws/src/zed_capture/config/capture_hd720_c5f_gnss.yaml
```

沿用现有15秒前后监测和唯一会话目录。不要同时运行旧GNSS串口驱动/record_all.launch。没有RTK Fixed也允许记录。若报权限、断线或占用错误，保留会话且停止，不自动重试或修改权限。

回退运行方式：仍选择原capture_hd720_c5f.yaml即关闭GNSS，旧模式回归已通过。源码/二进制完整回退必须在采集进程结束后，依据备份hashes.json逐文件核对恢复上述授权修改；本轮未自动执行回退，不能对原工作空间reset/clean。
