**C4.1 原因分析与软件准备 — 2026-10-17**

结论：SOFTWARE_TESTED；新受控实机对照为 PENDING_HARDWARE。已复现首次调用额外开销并增加录制前同线程预热；pair257等待根因及JPEG与视频缺口的因果关系仍为UNRESOLVED。本轮没有启动设备、重新录制、扫描大型bag或实施C5-E。

**证据与原因边界**

复用 `zed_720p_jpeg_c4_review_20261017_201258.md`、其机器复核及C4原始CSV。历史会话 `/home/jetson/zed_capture_data/20261017_201258_9aeecafa` 保持只读。C4 JPEG输入/完成901/901，拒收0、队列峰值1；严格33.333333ms门限保持不变。

| pair | YUYV转换ms | JPEG纯编码ms | worker ms | 提交→worker ms | 复制完成→编码完成ms |
|---|---:|---:|---:|---:|---:|
|1|13.692466|21.788625|35.985907|0.019807|36.030802|
|2|8.414647|20.325889|28.790614|5.747883|34.551104|
|257|8.716632|20.882150|29.652732|4.762575|34.421291|

VERIFIED：pair1自身处理超期。pair2提交时，pair1尚需5.151614ms才完成编码，解释其主要等待；队列没有持续积压。pair257提交时前一对已完成3.116546ms，因此其4.762575ms等待不能归因为前一对仍在编码。旧日志完成时刻在CSV写出及任务释放之前，缺少通知/等待返回证据，尚不能区分收尾阻塞、唤醒与调度。

为核实首次成本，使用同一Codec、Q95/420、720P SYNTHETIC YUYV，在三个独立进程各处理6对；不使用相机、不写bag。以下不是硬件测试：

| 独立进程 | 首次转换 / 后续中位ms | 首次编码 / 后续中位ms | 首次总处理 / 后续中位ms |
|---|---:|---:|---:|
|0|11.413 / 7.319|27.458 / 25.326|39.632 / 32.677|
|1|9.716 / 7.329|27.538 / 25.327|37.960 / 32.686|
|2|8.928 / 7.319|27.618 / 25.359|36.861 / 32.713|

VERIFIED：这三个进程均复现首调用额外4.15～6.95ms。SUPPORTED_HYPOTHESIS：C4 pair1主要受首次转换/编码路径开销影响。尚未区分库初始化、内存分配/缺页、缓存或频率状态，不能将某个库函数认定为唯一根因；合成纹理的编码难度也与真实场景不同。

**两次视频长间隔**

| 项目 | pair115 | pair516 |
|---|---:|---:|
|原始V4L2 ns|27414654694000|27428054652000|
|相对首帧s|3.833382|17.233340|
|sequence|113→116|516→519|
|帧间隔ms|66.751|66.607|
|上一QBUF→select开始ms|0.008224|0.005631|
|select等待ms|65.718286|65.485839|
|DQBUF ioctl ms|0.016799|0.017056|
|本对JPEG总延迟ms|25.997212|26.317154|
|上一JPEG完成→本次DQ返回ms|40.067369|40.079378|
|本对原始writer任务ms|8.289856|7.552100|

VERIFIED：这两次事件无select超时、DQBUF EAGAIN/致命错误或QBUF错误；全场两个select超时仅在首帧前。不是三次JPEG超期发生的位置，QBUF之后快速重新select，没有观察到采集回调同步等待编码。两个sequence_delta=3共缺4个驱动编号，不等同4次物理曝光丢失。select等待不能直接解释成线程失去调度。

SUPPORTED_HYPOTHESIS：新增编码负载可能间接增加设备/USB/UVC处理的时序敏感性。UNRESOLVED：现有记录不足以锁定USB、内核、设备或JPEG为原因。C2与C4不同时间/场景、1Hz系统资源统计均不足以建立因果关系。C4 writer等待最大1.082ms、任务最大12.486ms，没有观察到相应长堵塞，但不能据此排除未采样的瞬态。

**最小修改与内存/并发保护**

1. `src/zed_capture/src/jpeg_shadow.cpp`：使用实际编码worker执行3对明确标注SYNTHETIC的720P Q95/420预热；每次检查实际JPEG SOF。预热失败直接使初始化失败，不静默继续。输出独立 `jpeg_shadow_warmup.csv/json`，不计入真实输入数，不进入bag，不替代真实首帧。
2. `src/zed_capture/include/zed_capture/jpeg_shadow_worker.hpp`：增加准备完成屏障，构造函数等待预热结束；现有调用顺序为initShadow→bag.open→camera.initializeVideo，因此预热在录制前完成。增加通知、锁获取、条件等待返回、线程CPU、CSV写出和任务释放时间证据。
3. `src/zed_capture/test/jpeg_shadow_test.cpp`：准备屏障/准备失败回归；保留满队列、编码异常、退出排空、不可变Header/像素及配对测试。
4. `src/zed_capture/test/jpeg_startup_probe.cpp`（新增）及 `src/zed_capture/CMakeLists.txt`：独立合成冷启动诊断目标。没有新增系统依赖。
5. `src/zed_capture/config/capture_hd720_c41_off.yaml`、`capture_hd720_c41_on.yaml`（新增）：均来自C2，只相差jpeg_shadow_enable=false/true。
6. `diagnostics/zed_jpeg_c41/`（新增）：run_control.sh/py、analyze_worker.py、test_c41.py、证据、备份和构建/测试结果。

重新构建的运行组件只有影子插件 `devel/lib/libcapture_jpeg_shadow.so` 发生内容变化；主节点二进制及源码保持原SHA256。旧C4配置仍启用同一插件，因此今后用旧C4配置也会得到预热和诊断；其历史记录不受影响。默认1080P和C2均关闭影子功能，其路径不执行预热。

仍为单编码线程、4对有界队列、try_lock非等待提交，满队列/锁忙明确拒收且影子失败，不阻塞或丢弃原始录包任务。消费对象为已有安全复制后的共享图像，未引用已QBUF的MMAP。时间诊断使用已有固定4096事件槽；新增CSV在生产者停止、worker join后写出，不在逐帧回调增加文件I/O。原事件CSV写出逻辑保留并被计时。证据容量/写出错误必须失败，不将不完整记录称为通过。

新增 `jpeg_shadow_worker_timing.csv` 可将前一任务日志/释放尾部与下一次提交关联，也可看到通知、条件等待返回及线程CPU差异。wait_return包含条件唤醒、重新取锁和调度，不是内核就绪时刻；unlock记录是解锁后的观测，不能强行要求其早于worker开始。不能仅凭wall−CPU唯一归因调度。

预热可以将首调用工作移到录制之前；是否安全消除实机首对超期仍PENDING_HARDWARE。相机准备等待期间缓存/频率可能变化，真实纹理也可能更复杂。不得保证每对33.33ms，亦不调整门限。新诊断随正常退出保存；若SIGKILL/掉电，内存中的worker诊断可能不完整，必须标记缺证，不能伪造完整性。

**软件验证和保护**

`build_c41.log`：catkin_make -j2成功，没有clean。6项C++测试通过：shadow、core、watchdog、IMU分段、V4L2、HID。6项Python回归通过：仅配置开关差异、ON不得先运行、一次只起一个mock子进程且无重试、预热不计真实输入、拒收/编码失败有诊断、预热先于bag/相机。模拟测试均不代表实机通过。

`dynamic_dependencies.json`：主节点及插件ldd -r通过，使用系统libusb、OpenCV、libturbojpeg。`protection_check.json`：19个安装前关注文件中仅上述4个既有源码/构建文件及插件改变，14个保持；24个历史C4证据文件校验无变化。未读写原bag内容、未改原始sidecar、catkin_ws、STM32、Livox、L2-B、三时钟算法、NTP或系统依赖；无commit/push。

证据与备份根目录：`/home/jetson/zed_capture_ws/diagnostics/zed_jpeg_c41`。包括 `before/`、`before_sha256.json`、4份diff、`cpp_tests.json`、`python_tests.log`、3份startup_probe_SYNTHETIC CSV及汇总。备份包含修改前源码、插件与节点。回退时先保证采集自然退出，再根据diff仅撤销本轮改动或恢复对应备份并增量重建；不得覆盖用户后续修改，不使用git reset/clean，不删除历史数据。当前未执行回退。

**受控OFF/ON实机方案（等待用户运行）**

保持相机静止、场景/照明/USB连接不变，MID-360与STM32正常供电；避免另起编码/大文件写入任务。两组均完整原始720P30 YUYV、MID、双IMU、锚点、三时钟、严格检查；唯一计划配置变化是JPEG影子开关。各一次30秒，保留原15秒前后时钟监测。记录实际配置及SHA、程序SHA、用户条件备注、USB速度/身份、进程CPU/RSS、负载、1Hz温度/频率/冷却状态；备注是用户声明，不是机器证实场景相同。

先在普通SSH终端执行OFF（请按真实情况修改备注）：

```bash
/home/jetson/zed_capture_ws/diagnostics/zed_jpeg_c41/run_control.sh --arm off --experiment c41_pair01 --conditions-note '固定场景和照明；相机静止；连接不变；无额外任务'
```

OFF正常结束、检查结果保留后，在相同条件下手动执行ON：

```bash
/home/jetson/zed_capture_ws/diagnostics/zed_jpeg_c41/run_control.sh --arm on --experiment c41_pair01 --conditions-note '固定场景和照明；相机静止；连接不变；无额外任务'
```

每条命令最多启动一次采集，不自动启动另一组/重试。同名已尝试目录拒绝覆盖。ON要求OFF的CAPTURE_RUNTIME_PASS且软件/配置哈希一致；已知ZED IMU/锚点导致的严格DATA_INTEGRITY_FAIL不被改成PASS，也不作为阻止研究JPEG的前置条件。若OFF运行本身失败，先分析，不运行ON。继承原空间及设备预检；每组约3.46GB，两组额外约7GB，并保持原10GB安全余量策略。Ctrl-C由运行器转发给本次joint管理器，保留日志与退出记录。

结果位于 `diagnostics/zed_jpeg_c41/runs/c41_pair01/{off,on}/`，其中arm_result.json、conditions_before/after.json、capture_config.yaml、thermal.jsonl、terminal.log保存环境和结果；ON额外有c41_worker_analysis.json。原始bag仍在zed_capture_data唯一新会话，时钟记录仍在clock_diag/runs唯一目录。原始完整性阈值、33.333333ms延迟阈值不变。

后续比较两组视频间隔/sequence、CPU/内存/温度、writer/影子队列、每对耗时与worker尾部时间线。固定OFF先ON后仍有热状态、时间顺序和场景微变混杂；一次两组结果只能缩小范围，不能证明最终因果。当前没有新的实机结果。

**最终状态**

| 项目 | 状态 |
|---|---|
|首次额外开销软件复现|VERIFIED（SYNTHETIC）|
|预热屏障、所有权、退出和回归|SOFTWARE_TESTED|
|实机首对/第二对改善|PENDING_HARDWARE|
|pair257等待根因|UNRESOLVED，已补充可判别证据|
|JPEG负载导致视频缺口|UNRESOLVED，尚未建立因果|
|C4既有严格DATA_INTEGRITY|FAIL，未修改|
|C4.1 OFF/ON实机验收|PENDING_HARDWARE|
|L2-B与物理同步|PENDING|
|C5-E|仅设计，未实施|

FAST-LIVO2现有话题配置使用MID-360 IMU，ZED IMU启动旧报告不作为C4/C5开发前置修复。全部原始ZED IMU和异常分类继续保留。C4的414次锚点漏读、视频缺口、设备时间比例疑点不因本轮预热消失；候选锚点覆盖仍不等于L2-B通过。
