# L2-D2 离线软件回归报告

本轮结论：**L2B_EXACT_REGRESSION=PASS；FORMAL_C5G_FROZEN=VERIFIED；DEPLOYMENT=NOT_PERFORMED；PHYSICAL_SYNC=PENDING。**

2026-10-18仅执行材料校验和离线回归，没有运行 L2-D2采集二进制、启动传感器、部署候选程序或修改正式配置。软件映射等价性不代表物理同步通过，也不取消历史严格完整性 FAIL。

## 输入身份与完整性

材料目录：`/home/jetson/zed_capture_ws/diagnostics/l2d2_regression_20261018_203653`。重新核验远端清单的202个文件，共73833249字节；文件数量、相对路径集合、长度和SHA256全部匹配。远端主机名为RTX4090，仅为主机名，未据此判断GPU型号。

A/B/EXTERNAL分别绑定真实会话20261018_141750_265b3cbf、20261018_174130_d85a69b1、20261017_130643_750bf403。原基准的34/37/17项输入哈希均与Jetson历史sidecar匹配。没有读取或复制大型bag、JPEG。三组各6项基准结果（共18项）也匹配L2-C freeze.json记录的原始evaluation哈希。

迁移的evaluate_open_capture.py、time_mapping.py及本机只读使用的sensor_time_bridge/imu_anchor.py均与三组provenance源码哈希一致。未运行L2-C恢复策略，没有 monkey patch mapper、Config、REQUIRED或斜率/残差门限。

## 实际执行结果

| 组 | 有效/总对数 | 拒绝数 | 拒绝原因 | 精确回归 |
|---|---:|---:|---|---|
| A | 887/903 | 16 | {"ANCHOR_FIT_WARMUP": 14, "ANCHOR_OUTSIDE_SESSION": 2} | PASS |
| B | 879/902 | 23 | {"ANCHOR_FIT_WARMUP": 15, "ANCHOR_OUTSIDE_SESSION": 8} | PASS |
| EXTERNAL | 873/887 | 14 | {"ANCHOR_OUTSIDE_SESSION": 4, "ANCHOR_FIT_WARMUP": 8, "ANCHOR_READ_POLL_UNSTABLE": 2} | PASS |

每组执行两次：原输入副本、同副本增加IMA1诊断sidecar，共6次未修改evaluator执行。追加的诊断内容来自软件故障注入，并明确标记SYNTHETIC；不是新实机数据。两种输入的逐图映射CSV、锚点观察CSV、时钟模型JSON、锚点质量JSON与基准全部逐字节一致。mapped_stamp_ns及左右目映射整数完全一致；拒绝原因、模型分段、斜率、训练与独立留出结果和门限均包含在精确比较中。

A/B原输入组的6个结果文件全部逐字节一致。EXTERNAL有一项明确的输入来源差异：笔记本旧导出缺capture_metrics.jsonl，Jetson原会话有真实文件。本轮把该真实文件复制进独立输入目录，从而无需修改evaluator的必需文件校验。它不被映射算法读取。EXTERNAL的summary.source_sha256及provenance.input_hashes只多出该文件哈希；其它字段完全相等。

增加诊断sidecar的三组中，上述两个来源哈希字典另增加ima1_reader_diagnostics.jsonl及ima1_reader_diagnostics_summary.json；已有哈希不变。检查明确要求新增键集合准确匹配，未忽略其它差异。新的诊断文件没有成为mapper输入事件。

## 保护与软件边界

本轮前后核验83项正式程序/检查器/时钟源码及二进制，变化0；与L2-D2开发前68项原文件基线比较，变化0。catkin_ws原dirty diff及status均保持一致。迁移202项文件与历史输入在运行后再次核验未改变。

正式zed_capture_node SHA256：`4bc5bae4c14d917bffac8b72ac4d03122fca3153536c668ce7bb2ea2d657d4ef`。

本轮没有重编译、部署或替换C5-G。上一轮的独立候选构建及合成reader测试仍是独立软件证据；本轮不把它们解释为实机开销已验证。候选源快照与build_candidate_03 manifest中的两项C++源码哈希相符，但旧manifest的源码路径指向已恢复的正式源码，不能直接用于部署。本轮仅报告此状态，不改绑定或放行启动脚本。

## 证据位置

- 新输出目录：`/home/jetson/zed_capture_ws/diagnostics/ima1_l2d2/exact_regression_20261018_204650`
- `input_verification.json`、`baseline_freeze_hash_verification.json`：迁移及基准验证。
- `exact_regression_result.json`、A/B/EXTERNAL_comparison.json：完整逐文件比较和6条执行命令。
- A_off、B_off、EXTERNAL_off：三组原输入回归结果。
- *_diagnostic_sidecars：追加软件诊断文件后的回归结果。
- `protection_after.json`：冻结核查。

本轮完成后停止。受控实机OFF/ON对照、候选启动绑定复核和物理同步仍待后续授权；明天室外采集继续使用原已验证C5-G。
