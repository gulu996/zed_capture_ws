**C5-E 独立JPEG压缩录包实验设计 — 2026-10-17**

状态：DESIGN_ONLY，未实现、未启用、未生成派生bag。C4证明901/901对能够并发编码，但视频出现2次长间隔、JPEG有3次超期；C4.1仅完成软件预热和工作线程诊断，等待OFF/ON实机对照。本设计不是批准替换默认存储或宣称实时验收通过。

**实验边界**

以后只有显式独立实验配置才允许启用C5-E，例如新增capture_hd720_c5e.yaml与专用实验入口。默认1080P、既有C2原始YUYV、C4影子均保持原语义；配置无效或编码器缺失必须拒绝启动，不回退到未知模式。未来实现须另获授权，本轮没有创建C5-E配置或改动原始writer。

输入仍为原生双目2560×720 YUYV 30FPS、4个MMAP。安全复制后每目1280×720、8UC2、step2560、1843200bytes；不缩放、裁剪、补帧或改时间戳。Q95/420复用经过验证的YUYV→BGR→TurboJPEG路径，逐张校验真实JPEG SOF采样与尺寸。不得把8UC2改标签为bgr8。

仅未来明确选择的C5-E新会话可将实时图像存储为JPEG，而非同时持续存储全量原始图像；这是有损实验数据格式选择，不能声称可恢复原始YUYV像素。已有原始会话、源码路径和配置保留不动。正式C2仍可用于原始对照与回退。JPEG内容质量及FAST-LIVO2精度尚待验证。

**建议流水线与所有权**

```text
V4L2 DQBUF → 安全复制、原始元数据 → 尽快QBUF
                     ↓ 非阻塞提交整个双目任务
              有界原始双目队列（建议4对）
                     ↓ 单JPEG工作线程
          YUYV→BGR→Q95/420，检查左右SOF
                     ↓ 非阻塞提交完整压缩双目任务
        有界writer队列（条数及总字节双重限制）
                     ↓ 单rosbag工作线程
             左右CompressedImage + 元数据

MID点云、双IMU、锚点、诊断 → 同一受控writer入口
```

采集回调只提交已有安全复制、不可变的共享图像及元数据，不等待JPEG或磁盘。JPEG线程不持有V4L2 MMAP，不在QBUF之后引用失效像素；完整双目任务持有所有权至编码完毕。JPEG buffer由任务独占/RAII管理，writer消费完成后释放；编码线程不得复用仍由writer持有的字节。

左右目一起接收和编码，两个编码均成功才提交一个逻辑双目writer任务，避免正常路径只收一目。rosbag不具备跨两条消息的磁盘事务原子性：若第二条写入失败，必须记录未完成pair并使会话失败，不能声称原子落盘或删除已写成功记录来掩盖问题。

有界队列建议从4对原始任务开始：仅像素约14.75MB，另有活动任务约3.69MB、BGR临时空间、编码输出及writer容量。不能只按平均JPEG大小分配上限；未来按本机tjBufSize合法上界和明确的总字节预算计算，并计入MID消息、诊断、OS页缓存和8GB内存约束。不得在原有writer预算之外无依据再加大缓冲。双目和传感器任务共用writer时需预留可观测传感器容量或公平调度，禁止JPEG挤占MID任务后静默丢弃。队列/字节峰值、排队时间和拒收均记录。

任何队列满、try_lock失败、编码错误、输出超过字节预算都应在有界失败台账记录pair_id、原始时间、原因，然后置会话失败并请求现有管理流程有序停止。不能让采集回调阻塞等队列腾空，也不能将拒收帧从应收数量中减去。原始输入已接收但未录制的数量必须明确计入失败。队列排空仅处理已接受任务，不能不断追加新任务。

结束顺序建议：停止接收→停止并join视频生产者→排空/停止JPEG→排空writer→关闭/必要同步bag→完成最终诊断。编码或写盘卡死须有明确监测与失败状态；异常时保留已写bag及sidecar，不谎报bag_finalized。无法正常关闭时保留未完成文件，不强行标记成功。实际中断恢复、超时处理和磁盘错误路径必须先单元测试，不通过扩展无限等待来掩盖故障。

**消息与时间可追溯性**

建议实验专用主题 `/zed2i/left/image_raw/compressed` 与 `/zed2i/right/image_raw/compressed`，类型sensor_msgs/CompressedImage。format建议采用ROS常规表示 `bgr8; jpeg compressed bgr8`，未来与本机解码器验证兼容；JPEG实际内容需Q95/420、1280×720。只写明确白名单，不使用record -a。

| 保存对象 | 必须保持 |
|---|---|
|CompressedImage.header|原始seq、sec/nsec、frame_id；左右stamp一致|
|视频元数据/sidecar|pair_id、原始整数V4L2 sec/usec及ns、driver sequence、flags、timestamp type/source、原始像素尺寸/stride|
|编码事件|input_id/pair_id、接收/开始/完成时刻、转换/编码耗时、JPEG大小、SOF及失败原因|
|采集参数|实际G_FMT/G_PARM、颜色枚举、相机身份、配置和软件版本/哈希|
|MID与IMU/锚点|原消息及时间戳、原始HID/分段分类、IMA1更新与失败poll，不覆写|

Header.seq不能替代64位pair_id；driver sequence及pair_id分别保存。编码完成时间仅作为性能字段，不替代曝光或V4L2时间。沿用已记录的CLOCK_MONOTONIC域语义，不声称V4L2时间等于曝光中心。左右图像对应和候选锚点覆盖不等于L2-B有效映射或物理同步。

未来离线解码得到sensor_msgs/Image时应为1280×720、bgr8、step3840、2764800bytes，并逐字段恢复原Header。原始整数时间与时钟域依旧通过VideoStamp/sidecar追溯，不依赖JPEG文件内部包含ROS Header。无需修改FAST-LIVO2输入代码或运行SLAM来完成格式验收。

C4实际颜色记录为colorspace=8、ycbcr_enc=1、quantization=0、xfer_func=1；当前驱动默认量化规则对应601 limited参考，但传递函数元数据不是颜色校准。保留原枚举与转换声明，未来每次实机记录实际值；若不可读则UNKNOWN，不猜测固定色域，不擅自调整转换。720P内参、外参仍待标定，不能填伪造单位外参。

**诊断、预热与验收**

复用C4.1同worker、录制前3对SYNTHETIC预热；预热不是实际采集输入、不写到bag、不计完成率。完成屏障和失败退出必须在C5-E亦可验证。33.333333ms严格延迟门限不变，另外分别报告复制完成→JPEG完成、JPEG排队、JPEG完成→writer开始/写入完成，避免用吞吐掩盖单对延迟。

未来软件测试至少覆盖：

- 默认/C2模式原始话题与像素不变，只有显式C5-E选择改变新会话图像存储格式。
- 双目Header、pair_id、整数时间、sequence不可变，真实样本解码尺寸/色度采样正确，质量损失相对声明参考统计。
- 慢编码、编码异常、满原始/压缩队列、MID突发、日志失败：不阻塞V4L2、失败台账完整、总内存有界。
- 左成功右失败、writer中途失败/磁盘满、用户中断、启动失败：不伪称双目完整/会话完成，不覆盖历史。
- 正常退出排空与所有线程join、共享buffer生命周期；bag逐条可读及消息总数/元数据一一对应。

未来实机只在授权后进行独立唯一会话，先30秒，与C2/C4在尽可能相同场景下比较；JPEG减少磁盘写入同时改变CPU/内存路径，不能从单次结果断言因果。保存V4L2/HID底层诊断、原始时间锚点、三时钟与资源记录，验证实际格式而不是只检查配置文件。

验收分别输出CAPTURE_RUNTIME、VIDEO_CONTINUITY、JPEG_COMPLETION、JPEG_QUEUE、JPEG_LATENCY、MID360_CONTINUITY、CLOCK_DIAGNOSTIC、DATA_INTEGRITY、L2B_MAPPING、PHYSICAL_SYNC。原始严格DATA_INTEGRITY的ZED IMU/锚点失败条件继续保留。可增加SLAM_REQUIRED_DATA_STATUS描述当前MID点云+MID IMU+图像的可观察完整性，但不能将其作为SLAM精度或标定/同步成功结论，也不能覆盖严格FAIL。

ZED IMU启动旧报告不作为C5研发前置修复，仍完整记录与分类。414次历史锚点漏读、约1.28%设备时间比例、当前L2-B/物理同步待验证不会由JPEG格式变更自动解决。

**进入条件与尚待解决事项**

C4.1软件已可进行OFF/ON受控对照。首次额外开销预热后是否改善、pair257等待的真实来源、视频长间隔与新增编码负载的关系均需要新实机证据。即使对照一次零缺口，也不能宣称长期稳定或因果已确定。

可以继续评审本独立实验设计；不具备直接替换正式原始录包的证据。C5-E实现、软件故障注入测试、真实CompressedImage bag读写与实际容量、持续采集稳定性全部PENDING。REALTIME_CAPTURE、SLAM_ACCURACY和PHYSICAL_SYNC不得由C3离线吞吐或C4影子完成率直接置PASS。

本轮实际只交付设计，没有删除、禁用或改写原始YUYV存储链路，没有生成JPEG bag，没有修改FAST-LIVO2、Livox、STM32、L2-B或三时钟算法。
