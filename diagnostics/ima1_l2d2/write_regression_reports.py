from pathlib import Path
import json,hashlib
W=Path('/home/jetson/zed_capture_ws');D=W/'diagnostics/ima1_l2d2';O=Path(Path('/tmp/l2d2_exact_output').read_text());R=W/'diagnostics/l2d2_regression_20261018_203653'
r=json.loads((O/'exact_regression_result.json').read_text());v=json.loads((O/'input_verification.json').read_text());protect=json.loads((O/'protection_after.json').read_text())
candidate=D/'candidate_source_20261018_203653';build=D/'build_candidate_03';b=json.loads((build/'build_manifest.json').read_text())
source_binding={}
for relative in ['src/zed_capture/src/capture_node.cpp','src/zed_capture/include/zed_capture/ima1_reader_diag.hpp']:
 source_binding[relative]=hashlib.sha256((candidate/relative).read_bytes()).hexdigest()==b['files'][str(W/relative)]
assert all(source_binding.values())
(O/'candidate_source_binding_read_only.json').write_text(json.dumps(source_binding,indent=2)+'\n')
rows=[]
for label,g in r['groups'].items():
 x=g['off'];rows.append(f"| {label} | {x['valid_pairs']}/{x['total_pairs']} | {x['rejected_pairs']} | {json.dumps(x['rejection_reasons'])} | PASS |")
table='\n'.join(rows)
validation=f'''# L2-D2 离线软件回归报告

本轮结论：**L2B_EXACT_REGRESSION=PASS；FORMAL_C5G_FROZEN=VERIFIED；DEPLOYMENT=NOT_PERFORMED；PHYSICAL_SYNC=PENDING。**

2026-10-18仅执行材料校验和离线回归，没有运行 L2-D2采集二进制、启动传感器、部署候选程序或修改正式配置。软件映射等价性不代表物理同步通过，也不取消历史严格完整性 FAIL。

## 输入身份与完整性

材料目录：`{R}`。重新核验远端清单的202个文件，共{v['total_bytes']}字节；文件数量、相对路径集合、长度和SHA256全部匹配。远端主机名为RTX4090，仅为主机名，未据此判断GPU型号。

A/B/EXTERNAL分别绑定真实会话20261018_141750_265b3cbf、20261018_174130_d85a69b1、20261017_130643_750bf403。原基准的34/37/17项输入哈希均与Jetson历史sidecar匹配。没有读取或复制大型bag、JPEG。三组各6项基准结果（共18项）也匹配L2-C freeze.json记录的原始evaluation哈希。

迁移的evaluate_open_capture.py、time_mapping.py及本机只读使用的sensor_time_bridge/imu_anchor.py均与三组provenance源码哈希一致。未运行L2-C恢复策略，没有 monkey patch mapper、Config、REQUIRED或斜率/残差门限。

## 实际执行结果

| 组 | 有效/总对数 | 拒绝数 | 拒绝原因 | 精确回归 |
|---|---:|---:|---|---|
{table}

每组执行两次：原输入副本、同副本增加IMA1诊断sidecar，共6次未修改evaluator执行。追加的诊断内容来自软件故障注入，并明确标记SYNTHETIC；不是新实机数据。两种输入的逐图映射CSV、锚点观察CSV、时钟模型JSON、锚点质量JSON与基准全部逐字节一致。mapped_stamp_ns及左右目映射整数完全一致；拒绝原因、模型分段、斜率、训练与独立留出结果和门限均包含在精确比较中。

A/B原输入组的6个结果文件全部逐字节一致。EXTERNAL有一项明确的输入来源差异：笔记本旧导出缺capture_metrics.jsonl，Jetson原会话有真实文件。本轮把该真实文件复制进独立输入目录，从而无需修改evaluator的必需文件校验。它不被映射算法读取。EXTERNAL的summary.source_sha256及provenance.input_hashes只多出该文件哈希；其它字段完全相等。

增加诊断sidecar的三组中，上述两个来源哈希字典另增加ima1_reader_diagnostics.jsonl及ima1_reader_diagnostics_summary.json；已有哈希不变。检查明确要求新增键集合准确匹配，未忽略其它差异。新的诊断文件没有成为mapper输入事件。

## 保护与软件边界

本轮前后核验83项正式程序/检查器/时钟源码及二进制，变化0；与L2-D2开发前68项原文件基线比较，变化0。catkin_ws原dirty diff及status均保持一致。迁移202项文件与历史输入在运行后再次核验未改变。

正式zed_capture_node SHA256：`{protect['formal_binary_sha256']}`。

本轮没有重编译、部署或替换C5-G。上一轮的独立候选构建及合成reader测试仍是独立软件证据；本轮不把它们解释为实机开销已验证。候选源快照与build_candidate_03 manifest中的两项C++源码哈希相符，但旧manifest的源码路径指向已恢复的正式源码，不能直接用于部署。本轮仅报告此状态，不改绑定或放行启动脚本。

## 证据位置

- 新输出目录：`{O}`
- `input_verification.json`、`baseline_freeze_hash_verification.json`：迁移及基准验证。
- `exact_regression_result.json`、A/B/EXTERNAL_comparison.json：完整逐文件比较和6条执行命令。
- A_off、B_off、EXTERNAL_off：三组原输入回归结果。
- *_diagnostic_sidecars：追加软件诊断文件后的回归结果。
- `protection_after.json`：冻结核查。

本轮完成后停止。受控实机OFF/ON对照、候选启动绑定复核和物理同步仍待后续授权；明天室外采集继续使用原已验证C5-G。
'''
implementation=f'''# L2-D2 实现状态

**候选实现保留，未部署。正式C5-G保持冻结。** 本轮只完成L2-B离线等价性回归及报告。

上一轮候选源码位于 `{candidate}`，独立二进制位于 `{build}/lib/zed_capture/zed_capture_node`。正式capture_node.cpp和session.py已恢复至L2-D2开始前版本，正式二进制从未替换。新增诊断头文件/配置辅助模块未被正式冻结入口引用。

候选改动仅包括：

1. capture_node.cpp：默认OFF；OFF reader源码保持原样，ON进入独立旁路观察路径；原两次pread、stable表达式、1ms期限、100ms stat、快照更新、skipped计数及旧poll记录保持原控制语义。
2. ima1_reader_diag.hpp：8192个368字节固定槽（3014656字节）；完整快照才解码，errno仅错误返回有效；读取失败、恢复、生命周期/语义变化和约1Hz健康样本进入缓冲。满后保留旧记录，记录dropped及首末遗漏poll。join及原收尾之后排他创建诊断JSONL/summary。
3. session.py及ima1_diagnostic_config.py候选：显式开关与隔离二进制manifest校验、会话/boot/config/文件哈希绑定；不改变原默认配置。

不改变IMA1协议、L2-B退役行为或恢复策略；不增加reader重试、高频日志、写盘线程或JPEG/bag诊断队列任务。

独立故障测试工具位于 `{D}`：reader_harness.cpp对实际提取reader函数体执行链接期syscall故障替身，并对照修改前函数体；diagnostic_test.cpp验证固定容量、排他创建、短写、ENOSPC、fsync错误及观察者计时。本轮不重新执行传感器测试，也不更新或部署候选。

三组回归已精确复现887/903、879/902、873/887。完整结果见[软件验证报告](l2d2_software_validation.md)。候选路径重绑定及未来硬件启动需要单独复核；原run_diagnostic.sh的软件放行状态本轮保持不变，不应现在执行。
'''
overhead=f'''# L2-D2 开销及风险边界

本轮仅进行固定历史输入回归，没有测量新的实机读写竞争、CPU、RSS或丢帧率。PHYSICAL_SYNC=PENDING；HARDWARE_OBSERVER_EFFECT=PENDING。

上一轮独立软件测试留下的测量：每槽368字节，8192槽总3014656字节（约2.875MiB）；仅启用时分配。ON在真正执行双读的poll中新增3次CLOCK_MONOTONIC获取，B后时间复用原read_after；原OFF reader循环没有新增诊断调用。新增计时失败只标为诊断不可用，不新增生产失败；保存errno后额外计时恢复进入时errno。

软件微基准（100000次合成观察操作，不含真实共享文件争用）：P50=288ns、P95=320ns、P99=320ns、最大18304ns。该测量包括测试边界及计时成本，不是新增硬件poll开销的精确估计；不应据此宣称零开销或保证实机不受影响。

9000次合成无fd事件测试保存8192条、遗漏808条，首末遗漏poll为8193/9000；保持DIAGNOSTIC_TRUNCATED。事件JSONL为8656736字节；该次事件导出及fsync约84.432ms，不含完整进程退出或全部摘要写盘。单行有4096字节硬上限；文本预算为约32MiB加固定摘要，未构造全文件字符串。

失败测试覆盖短写继续、ENOSPC保留部分文件且无成功summary、同步错误、O_EXCL拒绝覆盖，以及无缓冲状态。高频reader不写盘，退出前崩溃/断电可能丢失全部内存诊断。完整导出与详细记录全覆盖是两个指标，DIAGNOSTIC_TRUNCATED不能当作完整诊断通过。

本轮证明的范围：原历史数据加入诊断文件后，原L2-B逐图映射、模型、原因和门限不变。此结果不证明ON插桩不会改变实时调度或双读碰撞概率，不证明所有不稳定读取可安全恢复。

正式C5-G二进制、配置、JPEG、GNSS、IMA1及三时钟路径保持冻结。候选不部署，受控硬件对照等待后续授权。

证据：`{D}/unit_20261018_202721/`（上一轮软件实验）；`{O}`（本轮历史精确回归）。
'''
for name,body in [('l2d2_implementation.md',implementation),('l2d2_software_validation.md',validation),('l2d2_overhead_risk.md',overhead)]:
 with (W/name).open('x') as f:f.write(body)
status={'l2b_exact_regression':'PASS','formal_c5g_frozen':'VERIFIED','deployment':'NOT_PERFORMED_NOT_AUTHORIZED','hardware_tests_started':0,'physical_sync':'PENDING','output_dir':str(O),'candidate_hardware_release':'NOT_GRANTED','original_runtime_gate_unchanged':True}
(O/'completion_status.json').write_text(json.dumps(status,indent=2)+'\n')
print(json.dumps(status,indent=2))
