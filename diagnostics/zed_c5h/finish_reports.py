from pathlib import Path
import json
W=Path('/home/jetson/zed_capture_ws');O=Path(Path('/tmp/c5h_out').read_text().strip());S=Path('/home/jetson/zed_capture_data/20261018_185527_61ca19f8')
a=json.loads((O/'bench_before/result.json').read_text());b=json.loads((O/'bench_final/check_result.json').read_text());historical=json.loads((S/'check_result.json').read_text());d=[];leaves=[0]
def compare(x,y,path=''):
 if path=='/offline_read_seconds':return
 if type(x)!=type(y):d.append([path,'type']);return
 if isinstance(x,dict):
  for k in x.keys()|y.keys():
   if k not in x or k not in y:d.append([path+'/'+k,'missing'])
   else:compare(x[k],y[k],path+'/'+k)
 elif isinstance(x,list):
  if len(x)!=len(y):d.append([path,'length',len(x),len(y)])
  for i,(l,r) in enumerate(zip(x,y)):compare(l,r,path+'/'+str(i))
 else:
  leaves[0]+=1
  if x!=y:d.append([path,x,y])
compare(a,b);old_new=list(d);compared=leaves[0];d=[];compare(historical,b)
comparison={'excluded_fields':['offline_read_seconds'],'old_new_differences':old_new,'historical_new_differences':d,'old_new_leaf_values_compared':compared,'all_jpeg_hashes_included':True,'strict_status_before':a['capture_integrity'],'strict_status_after':b['capture_integrity'],'jpeg_pairs':len(b['jpeg_files']['verified']),'gnss_bag_records':sum(b['gnss']['counts'].values()),'video_long_intervals':b['streams']['/zed2i/left/image_raw']['long_intervals'],'anchor_skipped_updates':b['anchor_poll_skipped_states']}
(O/'comparison_final.json').open('x').write(json.dumps(comparison,indent=2));assert not old_new and not d
p=json.loads((O/'bench_before/profile.json').read_text());q=json.loads((O/'bench_final/check_result.profile.json').read_text());s1=json.loads((O/'scale_1/profile.json').read_text());s4=json.loads((O/'scale_4/profile.json').read_text());idx=json.loads((O/'index_scale.json').read_text())
def delta(r,key):
 def parse(t):return {a:int(b) for a,b in (line.split(':') for line in t.strip().splitlines())}
 return parse(r['proc_io_after'])[key]-parse(r['proc_io_before'])[key]
metrics={'old_check_s':p['check_seconds'],'new_check_s':q['check_seconds'],'old_total_s':p['total_seconds'],'new_total_s':q['total_seconds'],'speedup':p['total_seconds']/q['total_seconds'],'elapsed_reduction_percent':100*(1-q['total_seconds']/p['total_seconds']),'old_peak_rss_MiB':p['peak_rss_kib']/1024,'new_peak_rss_MiB':q['peak_rss_kib']/1024,'rss_reduction_percent':100*(1-q['peak_rss_kib']/p['peak_rss_kib']),'old_result_bytes':p['result_bytes'],'new_result_bytes':q['result_bytes'],'output_reduction_percent':100*(1-q['result_bytes']/p['result_bytes']),'old_io':{k:delta(p,k) for k in ['rchar','read_bytes','write_bytes']},'new_io':{k:delta(q,k) for k in ['rchar','read_bytes','write_bytes']}}
(O/'performance_comparison.json').open('x').write(json.dumps(metrics,indent=2));print(json.dumps(metrics,indent=2));print('values compared',compared)
reports={}
reports['c5h_checker_performance_audit.md']=f'''# C5-H 检查器只读性能审计

输入：`{S}`。本轮无新实机采集，无原始bag/JPEG/sidecar修改。证据目录：`{O}`。

## 原475.085秒记录的边界

历史`offline_read_seconds=475.0852157520021`并非精确端到端时间：源码在GNSS检查及报告JSON输出之前设置此字段。历史没有记录检查器峰值RSS；C5-G采集进程组282MB不能作为检查器RSS。本轮另启独立进程复测保存的旧版源码，获得新测量，不能冒充历史测量。

旧版本轮完整check耗时{p['check_seconds']:.3f}秒，包含JSON输出的总耗时{p['total_seconds']:.3f}秒；峰值RSS {p['peak_rss_kib']/1024:.3f}MiB。

| 旧版阶段 | 实测秒 | 审计说明 |
|---|---:|---|
| 全量JPEG审核 | {p['stages_seconds']['file_audit']:.3f} | 17,976张逐文件读入、SOF检查、OpenCV全解码、SHA256；不是重复解码 |
| 主bag迭代/反序列化 | {p['bag_iterators'][0]['iterator_seconds']:.3f} | 528,576条消息；60,339,168个点逐个构造Python CustomPoint |
| GNSS独立检查 | {p['stages_seconds']['check_gnss']:.3f} | 再次打开sensors.bag遍历30,262条GNSS；所在bag chunks再次读取 |
| V4L2/HID审计 | {p['stages_seconds']['audit_io']:.3f} | 两套CSV字典整表、positive子列表、关联列表同时驻留 |
| 时序统计 | {p['stages_seconds']['timing_evidence']:.3f} | 多个CSV整表及重复分位数计算 |
| 锚点候选覆盖 | {p['stages_seconds']['assess_anchor_coverage']:.3f} | 锚点列表、good子列表及host数组；bisect关联 |

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
'''
reports['c5h_checker_implementation.md']=f'''# C5-H 实现说明

仅修改现有`scripts/check_recording.py`的CLI入口，新增8个离线checker模块。没有改采集线程、JPEG编码器/队列、GNSS-R2.1、MID、IMA1、L2-B、STM32、NTP、FAST-LIVO2或三时钟计算。

修改前备份：`{O}/before/scripts/`；前后SHA及完整diff：`hashes_before.json`、`hashes_after.json`、`changes.diff`。原legacy check()及原jpeg_file_check/gnss_recording_check实现保留作为兼容和回归参照；正式CLI现在走新的FULL_STRICT路径。

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

本轮全部新输出位于`{O}`，原会话只读。未来原采集入口仍调用同一个check_recording.py，原配置无需修改；新会话可保持原check_result.json路径。显式分析历史会话必须指定外部输出目录，例如：

```bash
source /home/jetson/zed_capture_ws/scripts/env.sh
python3 -B /home/jetson/zed_capture_ws/scripts/check_recording.py \\
  /home/jetson/zed_capture_data/20261018_185527_61ca19f8 \\
  --output-dir /home/jetson/zed_capture_ws/diagnostics/zed_c5h/manual_review_NEW
```

该命令只是离线复核示例，本轮已经完成，不需要再次运行。已有输出不会覆盖。完整JSON保留原schema；旁边新增profile JSON；退出码2仍表示严格FAIL，不代表程序崩溃。需读取profile区分完成验收后的数据FAIL与资源/读取中止。

私有scratch目录在结束时清理，仅清理检查器本次创建的临时索引，不清理原始会话。异常磁盘写入可能留下不完整结果，不能以文件存在作为PASS。

## 回退

无需修改采集配置。停止离线检查后，保留后续修改，按前后SHA/diff将check_recording.py从本次before备份恢复即可恢复旧CLI；不要删除原始数据，也不要git reset/clean。新辅助模块不改变旧入口算法。本轮没有执行回退、commit或push。
'''
reports['c5h_checker_validation.md']=f'''# C5-H 软件和真实历史数据验证

结论：FULL_STRICT_CHECK优化完成。真实300秒会话仍严格FAIL，未进行20分钟实机采集或开放其配置。

输入：`{S}`。全部新输出：`{O}`。

## 新旧结果一致性

旧源码独立进程复测、新版最终CLI结果和历史原check_result.json分别比较。只排除`offline_read_seconds`运行耗时字段；其余**{compared:,}个叶值完全一致**，没有隐藏其他字段差异。

- 8988对JPEG，17,976个文件SHA256全部一致，全部全量解码；不是抽样。
- MID点云3017、IMU60338；所有点云结构、序号及时间判定一致。
- GNSS 30,262条ROS记录、1,029,239原始字节及原始SHA、消息类型/MD5、无UTC状态一致。
- 视频12次长间隔、最大133.397ms、28个驱动编号缺口全部保持；402个锚点更新漏读保持。
- ZED启动异常及后续缺口、所有低层事件、候选锚点覆盖、应用级FAIL原因完全一致。
- DATA_INTEGRITY=FAIL；SLAM_REQUIRED_DATA_STATUS=FAIL；L2-B/GNSS映射及物理同步PENDING。

证据：`comparison_final.json`。当前C5-G三时钟历史PASS未改动；本轮没有重新执行采样或改变算法。

## 性能对比（本机实测）

| 指标 | 旧版本轮复测 | 新版最终复测 |
|---|---:|---:|
| check总耗时，含GNSS | {p['check_seconds']:.3f}s | {q['check_seconds']:.3f}s |
| 含JSON输出总耗时 | {p['total_seconds']:.3f}s | {q['total_seconds']:.3f}s |
| 峰值RSS | {p['peak_rss_kib']/1024:.3f}MiB | {q['peak_rss_kib']/1024:.3f}MiB |
| JPEG全量检查 | {p['stages_seconds']['file_audit']:.3f}s | {q['stages_seconds']['file_audit']:.3f}s |
| bag迭代/解码计时 | {p['bag_iterators'][0]['iterator_seconds']:.3f}s | {q['bag_read_decode_seconds']:.3f}s |
| V4L2/HID | {p['stages_seconds']['audit_io']:.3f}s | {q['stages_seconds']['audit_io']:.3f}s |
| 锚点候选覆盖 | {p['stages_seconds']['assess_anchor_coverage']:.3f}s | {q['stages_seconds']['assess_anchor_coverage']:.3f}s |
| 完整结果JSON | {p['result_bytes']:,} bytes | {q['result_bytes']:,} bytes |

总耗时降低{metrics['elapsed_reduction_percent']:.2f}%（约{metrics['speedup']:.2f}倍），峰值RSS降低{metrics['rss_reduction_percent']:.2f}%。完整JSON减少{metrics['output_reduction_percent']:.2f}%，仅去除格式空白，所有行和SHA仍在。

并非所有阶段更快：磁盘索引使HID审核和锚点关联略慢，以有界内存换取成本。新版lazy索引加载发生在bag迭代内，旧版部分索引在打开时加载，迭代阶段数字不是完全相同计时边界；应优先比较端到端时间。

最初新版回归总耗时224.694s、峰值276.898MiB；随后补充rosbag索引预算门禁，才做最终{q['total_seconds']:.3f}s复测。不是反复录制，也没有只挑最好的一次。

| I/O计数 | 旧版增量bytes | 新版增量bytes |
|---|---:|---:|
| rchar，逻辑读取 | {metrics['old_io']['rchar']:,} | {metrics['new_io']['rchar']:,} |
| read_bytes，物理存储归属读取 | {metrics['old_io']['read_bytes']:,} | {metrics['new_io']['read_bytes']:,} |
| write_bytes，含临时索引和结果 | {metrics['old_io']['write_bytes']:,} | {metrics['new_io']['write_bytes']:,} |

新版scratch数据库实际约{q['scratch_database_bytes_before_cleanup']/1e6:.3f}MB，结束后只清理该临时目录。临时写入增加，不能宣称读写负担都降低。物理读取受缓存影响，未执行drop_caches，不把缓存效应全部归因优化。

## 软件测试

13项专用测试通过，包括：

- 精确整数大于2^53/2^63、顺序、重复检测及流式JSON等价。
- CustomMsg 0/1/19/20,000点逐字段对比原ROS解码，包括Header/timebase/rsvd；截断与错误MD5拒绝。
- 三对真实JPEG及截断、Header篡改、孤立文件、重复pair、原始metadata错配、错误SOF；新旧判定和完整结果一致。
- 全部锚点覆盖分支，包括无锚点、非递增时间、边界、时钟域变化；原门限不变。
- 真实资源/时序统计完全一致；完整真实低层IO结果一致。
- GNSS历史五类消息（含21条有效UTC）及R2.1 NO_FIX回放与旧检查器一致，错误MD5明确拒绝。
- GNSS关闭、旧原始Image模式合成bag与原check结果一致。
- `/dev/full`输出失败、单行预算、数值容量预算和索引加载预算拒绝。

日志：`unit_final.log`；Python语法编译通过。只修改Python离线程序，不需要重新编译采集C++。

初次测试比较中发现JSON数组与legacy Python tuple的类型差异，修正测试归一化到实际JSON输出后通过；未放宽任何数据检查。旧参考函数部分read-open写法触发ResourceWarning，保留日志；新流式输入使用context manager。

## 扩展性：明确为SYNTHETIC/REPLAY

| sidecar重复规模 | 视频事件 | HID事件 | 耗时s | 峰值RSS MiB |
|---|---:|---:|---:|---:|
| 1倍 | {s1['video_events']} | {s1['hid_events']} | {s1['seconds']:.3f} | {s1['peak_rss_kib']/1024:.3f} |
| 4倍，约20分钟事件数量 | {s4['video_events']} | {s4['hid_events']} | {s4['seconds']:.3f} | {s4['peak_rss_kib']/1024:.3f} |

4倍回放保留原始重复时钟造成的边界reset，输出51个异常（4×12原异常＋3个重复边界），没有伪装成真实连续采集。该测试没有复制原bag或批量重新编码图像，也不是完整20分钟JPEG+bag端到端验证。

另分配真实rosbag索引对象的合成压力测试：528,576 / 1,057,152 / 1,585,728 / 2,114,304项对应峰值RSS约{', '.join(f"{x['peak_rss_kib']/1024:.1f}" for x in idx['points'])}MiB。证明该残余结构线性增长，**不能声称整个检查器恒定内存**。该测试设置1GiB安全中止限制，实际未触发；不等于完整检查器的峰值预测。

## 保护和后续边界

59个原文件哈希核对中，仅check_recording.py入口发生预期修改；旧配置、采集C++、JPEG编码、GNSS核心及三时钟算法哈希不变。原会话与上轮review保存身份一致，原结果和原始GNSS SHA未变；大型bag未额外做整文件SHA重扫，以size/mtime及全记录回归核对。所有JPEG哈希参与结果一致性对比。

20分钟规模的sidecar处理已有软件证据，按当前消息率估计也在显式bag索引预算内；但完整20分钟bag＋所有JPEG组合尚未实测，离线JSON外层消费者及真实负载变化仍需核查。因此只能说**具备带预算的进一步离线验收基础，不能宣布20分钟完整验收或实机采集已通过**。20分钟采集配置未开放。本轮到此停止。
'''
for name,text in reports.items():
 with (W/name).open('x') as f:f.write(text)
print('\n'.join(str(W/name) for name in reports))
