# L2-D2 开销及风险边界

本轮仅进行固定历史输入回归，没有测量新的实机读写竞争、CPU、RSS或丢帧率。PHYSICAL_SYNC=PENDING；HARDWARE_OBSERVER_EFFECT=PENDING。

上一轮独立软件测试留下的测量：每槽368字节，8192槽总3014656字节（约2.875MiB）；仅启用时分配。ON在真正执行双读的poll中新增3次CLOCK_MONOTONIC获取，B后时间复用原read_after；原OFF reader循环没有新增诊断调用。新增计时失败只标为诊断不可用，不新增生产失败；保存errno后额外计时恢复进入时errno。

软件微基准（100000次合成观察操作，不含真实共享文件争用）：P50=288ns、P95=320ns、P99=320ns、最大18304ns。该测量包括测试边界及计时成本，不是新增硬件poll开销的精确估计；不应据此宣称零开销或保证实机不受影响。

9000次合成无fd事件测试保存8192条、遗漏808条，首末遗漏poll为8193/9000；保持DIAGNOSTIC_TRUNCATED。事件JSONL为8656736字节；该次事件导出及fsync约84.432ms，不含完整进程退出或全部摘要写盘。单行有4096字节硬上限；文本预算为约32MiB加固定摘要，未构造全文件字符串。

失败测试覆盖短写继续、ENOSPC保留部分文件且无成功summary、同步错误、O_EXCL拒绝覆盖，以及无缓冲状态。高频reader不写盘，退出前崩溃/断电可能丢失全部内存诊断。完整导出与详细记录全覆盖是两个指标，DIAGNOSTIC_TRUNCATED不能当作完整诊断通过。

本轮证明的范围：原历史数据加入诊断文件后，原L2-B逐图映射、模型、原因和门限不变。此结果不证明ON插桩不会改变实时调度或双读碰撞概率，不证明所有不稳定读取可安全恢复。

正式C5-G二进制、配置、JPEG、GNSS、IMA1及三时钟路径保持冻结。候选不部署，受控硬件对照等待后续授权。

证据：`/home/jetson/zed_capture_ws/diagnostics/ima1_l2d2/unit_20261018_202721/`（上一轮软件实验）；`/home/jetson/zed_capture_ws/diagnostics/ima1_l2d2/exact_regression_20261018_204650`（本轮历史精确回归）。
