# C5-H 实现说明

仅修改现有`scripts/check_recording.py`的CLI入口，新增8个离线checker模块。没有改采集线程、JPEG编码器/队列、GNSS-R2.1、MID、IMA1、L2-B、STM32、NTP、FAST-LIVO2或三时钟计算。

修改前备份：`/home/jetson/zed_capture_ws/diagnostics/zed_c5h/work_20261018_192501/before/scripts/`；前后SHA及完整diff：`hashes_before.json`、`hashes_after.json`、`changes.diff`。原legacy check()及原jpeg_file_check/gnss_recording_check实现保留作为兼容和回归参照；正式CLI现在走新的FULL_STRICT路径。

## 模块与验证等价性

- `checker_run.py`：完整验收、分阶段计时、RSS/I/O记录，流式输出完整JSON；终端只打印结果摘要及路径。明确标记FULL_STRICT_CHECK，没有实现或冒用QUICK_CHECK。
- `checker_strict.py`：保留原严格断言、错误名称、统计字段和阈值，改用逐消息/逐行输入和磁盘关联。GNSS在同一次bag循环消费，不再二次扫描。
- `checker_bag.py`：只读CustomMsg固定布局解码；先验证datatype/MD5及字段布局，再以19字节结构化NumPy视图表示**全部声明的点**。所有点载荷长度、Header、timebase、point_num、序号/空云等原检查保留；不抽样、不滤点。避免创建六千多万个Python点对象。其他ROS消息仍genpy完整反序列化。原genpy允许尾随字节的行为保持一致。
- `checker_gnss.py`：原始SHA分块计算；逐chunk检查字节偏移和时钟夹取；逐line重建原始字节；bag原始消息按序关联；UTC整数序列、无效映射标志、五类type/MD5和写入计数不变。独立R2.1解析代码未复制或改动。
- `checker_io.py`：V4L2及HID与原始sidecar顺序关联；全部报告长度/tick、syscall次序、队列计数、时间倒退和错误仍检查。异常事件写入私有磁盘表，不丢弃历史异常。
- `checker_streams.py`：JPEG每对仅有两个固定解码工作线程、最多两项在途任务，每张仍执行原OpenCV完整解码、SOF、长度、EOI、SHA256和Header校验；结果按原左右目顺序提交。记录两侧路径集合、重复pair及跨文件关系的SQLite索引。资源/时序按行读取。
- `checker_application.py`：用磁盘排序和精确数值数组计算原应用级策略；3次/100ms及所有严格时间门限不变。
- `checker_store.py`：SQLite小缓存及逐行JSON输出。每个SHA和frames记录仍在完整JSON里；压缩的是空白，不是证据。

所有时间戳保持整数；绝对纳秒时间不先转float。分位数/中位数仍精确计算，不使用近似抽样算法。

## 明确预算与仍增长的结构

| 结构 | 限制/边界 |
|---|---|
| JPEG解码 | 固定2工作线程，最多2任务；逐图释放像素 |
| SQLite | 4MiB page cache，temp_store=FILE，mmap=0；本机4KiB页下最大2GiB私有数据库 |
| 数值统计 | 每序列最多2,000,000个64位数；超过预算报错，不近似或省略 |
| ROS bag索引 | skip_index打开后先看chunk计数，最多2,500,000条消息、1024连接、8192 chunks；再加载索引 |
| JSONL/磁盘证据行 | 单行1MiB上限，异常则拒绝完整验收 |
| 连续无帧事件burst | 超过512条时显式预算错误；原文件不变，不能声称该段完整验收通过 |
| 资源PID历史 | 最多4096个PID，超预算报错 |

rosbag索引和精确数值数组仍在预算内随N增长，不能称整个检查器恒定RSS。预算是可处理数据规模上限，不是OS级RSS隔离或恶意文件解析的绝对内存保证。SQLite使用磁盘换内存；空间不足会检查失败，不能输出成功验收。

20分钟按本次速率投影约2,114,304条bag消息，低于250万条预算；这不是已经读过完整20分钟真实bag的证明。输入话题、GNSS输出频率改变后必须重新核对。

## 输出与使用

本轮全部新输出位于`/home/jetson/zed_capture_ws/diagnostics/zed_c5h/work_20261018_192501`，原会话只读。未来原采集入口仍调用同一个check_recording.py，原配置无需修改；新会话可保持原check_result.json路径。显式分析历史会话必须指定外部输出目录，例如：

```bash
source /home/jetson/zed_capture_ws/scripts/env.sh
python3 -B /home/jetson/zed_capture_ws/scripts/check_recording.py \
  /home/jetson/zed_capture_data/20261018_185527_61ca19f8 \
  --output-dir /home/jetson/zed_capture_ws/diagnostics/zed_c5h/manual_review_NEW
```

该命令只是离线复核示例，本轮已经完成，不需要再次运行。已有输出不会覆盖。完整JSON保留原schema；旁边新增profile JSON；退出码2仍表示严格FAIL，不代表程序崩溃。需读取profile区分完成验收后的数据FAIL与资源/读取中止。

私有scratch目录在结束时清理，仅清理检查器本次创建的临时索引，不清理原始会话。异常磁盘写入可能留下不完整结果，不能以文件存在作为PASS。

## 回退

无需修改采集配置。停止离线检查后，保留后续修改，按前后SHA/diff将check_recording.py从本次before备份恢复即可恢复旧CLI；不要删除原始数据，也不要git reset/clean。新辅助模块不改变旧入口算法。本轮没有执行回退、commit或push。
