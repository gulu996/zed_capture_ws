# C5-I-A 安全停止设计

## 请求与身份

stop先核对field_identity中目录/SESSION_ID/token，当前boot_id、manager PID/start_ticks、cmdline包含实际manager入口及对应目录。PID复用、旧boot、损坏JSON、未知会话均拒绝，不向这些PID发信号。

外部stop不调用kill；原子写入本会话field_stop_request.json，包含身份、原因和整数MONOTONIC。runner轮询并向其自己创建、未回收的候选节点发送一次SIGINT。重复请求幂等；已经结束只报告终态。已进入明确finalization阶段时不再发节点信号，避免干扰同步。

候选SIGINT/SIGTERM处理器只写sig_atomic_t；NoSigintHandler避免先关闭ROS。录制循环/准备等待在正常控制线程观察停止标志。随后沿用原GNSS握手与队列排空次序。原C5-G节点、GNSS串口解析及消息类型完全不变。

## 停止等待

stop默认等待120秒，显示FINALIZING和节点阶段；超时返回失败并打印runner未退出进程/启动标识、路径和状态。没有SIGKILL、pkill、killall或模糊进程名操作。超时后manager继续收尾；用户可再次status检查，不把超时当成功。

先等待capture node完成，随后等待GNSS reader退出，再对自己启动的Livox/roscore发SIGINT并等待。不会在node尚等GNSS回调时先停GNSS或ROS Master。重复stop不会缩短GNSS或JPEG排空过程。

## 软件验证边界

通过真实子进程/信号进行SYNTHETIC生命周期测试：自动结束（虚拟300秒，实际缩短）、前台SIGINT、manager SIGHUP存活、新查询/请求停止、finalization重复停止、初始化停止、低空间预检失败。真实C++信号测试验证ROS shutdown标志未被停止处理器置位，原有界writer排空100条模拟IMU消息，bag全部读回、整数时间保持。

旧JPEG测试覆盖部分写、短写、零写、磁盘失败、有界队列拒收、所有权、排空和分目录。GNSS真实历史消息经过原唯一writer写入新离线bag，五类话题计数与MD5检查保持。

这些并非新的传感器实测，也不等于验证真实网络断开、USB阻塞、内核I/O长停顿情况下的关闭时限。SAFE_STOP_VALIDATED=SOFTWARE_ONLY；硬件GNSS stop/done/ack以及实际bag/JPEG同步仍需受控30秒验证。

正常停止代码不使用强杀。原clock_diag回归套件包含一个独立clock_monitor不可捕获死亡的持久化反例；它只验证缺失summary不能冒充成功，不涉及采集进程，也不作为正常收尾证据。
