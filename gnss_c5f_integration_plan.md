# GNSS与C5-F最小集成计划

本轮完成审计/软件测试，**生产集成尚未实施**。原因是独立串口实测HARDWARE_PENDING，尚不能确认实际协议、校验与质量码；用户要求独立通过后再集成。本轮未把任何GNSS订阅或新驱动加到正式capture_node。

## 当前结束状态

C5-F历史会话20261018_141750_265b3cbf的manager returncode=0、正常结束、文件最终同步完成。本轮沙箱只见自己的进程，不能保证宿主当前没有其他活跃任务。因此未来集成修改前仍需主机进程/锁检查，不能凭沙箱ps空结果宣布宿主空闲。现阶段没有实施生产修改。

## 复用边界

复用旧gnss_serial_driver解析器和五个原消息；消息类型/MD5清单见gnss_usb_receiver_audit.md。复用已有真实协议和软件回归，而非整个record_all.launch。独立GNSS数据采集适配层负责稳定设备身份、排他读取、断连清缓冲、原字节/三钟sidecar；不启用GNSS ENU/融合节点。

旧驱动的AGRICA未校验CRC、质量枚举不一致、anchor模式无映射丢PVT等问题在实际语句确认前必须显式标记，不能将其旧valid_for_fusion直接作为新系统同步通过凭据。

## 唯一bag写入器

现capture_node已有topic_tools::ShapeShifter订阅和relay→有界任务队列→唯一bagwriter。未来以默认关闭gnss_enable为条件，注册白名单五话题并校验datatype+MD5；共享不可变消息生命周期，任务入队按实际序列化字节计费。GNSS回调不能同步写bag或等待JPEG；超限记录具体话题与计数并失败，不静默丢弃。

配置仅新建 `capture_hd720_c5f_gnss.yaml`（拟议，本轮不创建为可运行配置）。所有旧配置/default behavior保持不变。JPEG保持左右文件，MID/ZEDIMU/IMA1继续原路径，新增GNSS消息进入同一个sensors.bag。不能启动第二个rosbag writer；不启动旧SessionRecorder。

会话管理器复用当前ROS Master和Livox；GNSS读取进程只允许一个。既有GNSS进程/端口占用时不能另起、不能强杀；若想复用现有publisher，必须检查节点参数、消息MD5、时钟sidecar能力和会话归属，否则明确拒绝。本轮独立探针在退出后释放所有fd，不作为后台常驻服务。

原始串口sidecar由唯一GNSS采集进程写入新会话专属目录；通过source_sequence、chunk_id、字节偏移、boot_id关联ROS消息和三钟。每条记录分开测量UTC有效性、位置质量、测量映射有效性；边界读/断连/过长行/解析错误不删除raw。记录adapter软件哈希与parser哈希。故障退出保存已有文件并写结果。

## 启动、停止与独立验收

启动只要求指定身份串口可独占读取、原始字节到达和必要诊断可写；不要求RTK Fixed。GNSS源启用但静默/断连必须明确GNSS_RECEPTION_FAIL，不能掩盖成无Fixed；校验/解析错误保留统计与独立状态。关闭配置时不增加任何GNSS门禁或订阅。

开始：检查空间、串口身份/已有读者、原消息MD5，建立新唯一会话及bag订阅，再启动单个GNSS reader，等raw稳定后按现有原始传感器就绪规则录制。停止：按会话拥有关系停reader、排空GNSS与JPEG队列、完成bag和sidecar同步；保留断线与失败条数。不要因定位质量低删除原始数据或禁止启动。

须分别输出GNSS_RAW_RECEPTION、GNSS_PROTOCOL_CHECKSUM、GNSS_POSITION_QUALITY、GNSS_MEASUREMENT_TIME、GNSS_RECEIVE_CLOCK、GNSS_MEASUREMENT_MAPPING、原DATA_INTEGRITY、SLAM_REQUIRED_DATA_STATUS。测量映射不通过始终PENDING/FAIL，绝不因Fixed改PASS。

## 验证顺序

1. 普通SSH运行独立15秒命令，复核真实协议分布/校验/UTC/质量/主机接收时钟。暂不要求用户真实拔插；软件断连缓存测试通过不代表物理重连通过。
2. 明确旧协议适配风险，实施独立适配层和正式唯一writer最小订阅扩展；备份源码/二进制。不得改原catkin_ws。
3. 离线小bag验证已完成五类旧消息16条全读/MD5测试（SYNTHETIC）。未来还须对真正C5-F writer扩展测试白名单MD5拒绝、队列满、GNSS断连、低质量保留、无映射PVT保留、旧配置回归；本轮尚未宣称完成这些尚不存在的生产改动测试。
4. 提交具体变更与软件结果，**等待用户明确确认**后才执行一次30秒JPEG+MID+GNSS联合实测。
5. 检查bag全部记录、各GNSS类型/MD5、raw和parsed数量/关联、checksum错误、每source测量UTC连续性、三钟接收连续性、质量分布、版本/不确定度；同时比较JPEG完成、MID连续性、IMA1质量、三时钟和CPU/内存/磁盘负载。

## 本轮可执行命令

```bash
/home/jetson/zed_capture_ws/diagnostics/gnss_usb/run_independent.sh --duration 15
```

只采GNSS原字节/解析诊断，不运行融合或完整联合采集。唯一输出路径GNSS_DIR用于下一轮检查。当前完整联合采集命令尚不提供，避免在独立验证前错误启用功能。

新增文件均在zed_capture_ws诊断目录及三份报告；没有旧源码/消息/配置改动，不需系统回退。无需卸载软件或修改系统依赖。
