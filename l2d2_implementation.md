# L2-D2 实现状态

**候选实现保留，未部署。正式C5-G保持冻结。** 本轮只完成L2-B离线等价性回归及报告。

上一轮候选源码位于 `/home/jetson/zed_capture_ws/diagnostics/ima1_l2d2/candidate_source_20261018_203653`，独立二进制位于 `/home/jetson/zed_capture_ws/diagnostics/ima1_l2d2/build_candidate_03/lib/zed_capture/zed_capture_node`。正式capture_node.cpp和session.py已恢复至L2-D2开始前版本，正式二进制从未替换。新增诊断头文件/配置辅助模块未被正式冻结入口引用。

候选改动仅包括：

1. capture_node.cpp：默认OFF；OFF reader源码保持原样，ON进入独立旁路观察路径；原两次pread、stable表达式、1ms期限、100ms stat、快照更新、skipped计数及旧poll记录保持原控制语义。
2. ima1_reader_diag.hpp：8192个368字节固定槽（3014656字节）；完整快照才解码，errno仅错误返回有效；读取失败、恢复、生命周期/语义变化和约1Hz健康样本进入缓冲。满后保留旧记录，记录dropped及首末遗漏poll。join及原收尾之后排他创建诊断JSONL/summary。
3. session.py及ima1_diagnostic_config.py候选：显式开关与隔离二进制manifest校验、会话/boot/config/文件哈希绑定；不改变原默认配置。

不改变IMA1协议、L2-B退役行为或恢复策略；不增加reader重试、高频日志、写盘线程或JPEG/bag诊断队列任务。

独立故障测试工具位于 `/home/jetson/zed_capture_ws/diagnostics/ima1_l2d2`：reader_harness.cpp对实际提取reader函数体执行链接期syscall故障替身，并对照修改前函数体；diagnostic_test.cpp验证固定容量、排他创建、短写、ENOSPC、fsync错误及观察者计时。本轮不重新执行传感器测试，也不更新或部署候选。

三组回归已精确复现887/903、879/902、873/887。完整结果见[软件验证报告](l2d2_software_validation.md)。候选路径重绑定及未来硬件启动需要单独复核；原run_diagnostic.sh的软件放行状态本轮保持不变，不应现在执行。
