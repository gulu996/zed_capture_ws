#!/usr/bin/env python3
"""Summarize completed C3 evidence without rereading the source bag or rerunning tests."""
import csv,json,pathlib
B=pathlib.Path(__file__).resolve().parent
P=B/'runs/jpeg_20261017_164934_63c9bc42'
S=json.loads((P/'summary.json').read_text())
A=json.loads((P/'analysis_summary.json').read_text())
D=json.loads((P/'disk_summary.json').read_text())
lines=[]
def add(s=''):lines.append(s)
def table(head,rows):
    add('| '+' | '.join(head)+' |');add('| '+' | '.join(['---']*len(head))+' |')
    for row in rows:add('| '+' | '.join(str(x) for x in row)+' |')
    add()
add('**ZED 720P JPEG Jetson 离线性能验证 — C3，2026-10-17**\n')
add('本机实测完成。Q90/4:2:0 与 Q95/4:2:0 均通过离线功能及各一次 30 秒固定节拍编码测试。推荐优先考虑 Q95/4:2:0 的后续实时影子测试：本样本的角点保持和梯度指标更好，持续处理延迟仍低于 33.33ms。当前结果不证明完整联合采集并发性能、长期热稳定性、真实色彩准确性、SLAM 精度或物理同步。\n')
table(['验收项','结论'],[
['OFFLINE_BENCHMARK','PASS：真实输入、明确 4:2:0、质量指标、独立写盘及 ROS Header 回环检查完成'],
['SUSTAINED_ENCODING','PASS：Q90/Q95 各 900/900 对，30 对/s，溢出 0、超期 0'],
['REALTIME_CAPTURE','PENDING：尚未与视频/HID/雷达/rosbag 并发'],
['SLAM_ACCURACY','PENDING：未运行建图'],['PHYSICAL_SYNC','PENDING：本轮未执行时间映射或物理同步验证']])
add('**输入、抽样和保护**\n')
add('只读输入 `/home/jetson/zed_capture_data/20261017_162911_883e3a79/data.bag`，3,460,013,078 bytes。全包按序扫描一次，统计全部消息的序列化字节数；仅反序列化并缓存 48 对所选图像，原始像素共 176,947,200 bytes。输入扫描 7.388 秒，不计入编码计时。未复制原 bag，未生成派生 bag，未连接传感器。\n')
add('按原始时间均匀分成 48 个抽样位置，包含首尾，实际 pair_id：`'+', '.join(map(str,A['sample_pair_ids']))+'`。每眼确认 1280×720、8UC2、step=2560、1,843,200 bytes。双目 seq/stamp 一致，并与 video_timestamps.csv 的原始整数 raw_ns 匹配。pair_id、驱动 sequence、V4L2 flags/时间域等原始行、每眼 Header（含 frame_id）、像素 SHA256 和尺寸保存在 sample_metadata.json。没有修改图像方向或曝光。\n')
add('样本内容覆盖：暗像素 Y≤32 的比例为 36.00%–51.45%；高亮 Y≥220 为 0.41%–27.84%。最暗比例样本为 pair902/right，最高亮比例 pair519/right，最高抽样梯度 pair672/left。人工查看后两者 JPEG，包含大面积暗衣物、近处遮挡、亮平面以及百叶窗细纹理。抽样覆盖了本会话时间及这些内容，但不能代表开阔、运动或高纹理户外场景；较高压缩比受该场景影响。\n')
add('保护检查：41 个生产代码/二进制/配置/时钟工具文件 SHA256 全部一致；历史 sidecar SHA256 全部一致；原 bag 大小和 mtime_ns 一致。为避免重复全包读取，未做 bag 全文件前后 SHA256 对照。无系统包、系统参数、生产节点、配置、L2-B、IMU 分段或原工程修改，无 commit/push。\n')
add('**编码器和色彩解释**\n')
add('使用现有 libturbojpeg 2.0.3 (`/usr/lib/aarch64-linux-gnu/libturbojpeg.so.0.2.0`)，ctypes 调用 tjCompress2：TJPF_BGR、TJSAMP_420、质量 90/95、TJFLAG_ACCURATEDCT。OpenCV 4.2.0 只用于 YUYV→BGR、解码和质量计算，固定单线程并关闭 OpenCL；该版本 Python JPEG API 没有可用的采样格式控制参数，因此未依赖默认 JPEG 采样。192 个实际写盘 JPEG 均检查 SOF：1280×720，Y 2×2、Cb/Cr 各 1×1，确认为 4:2:0。文件 SHA256 全部核对通过。\n')
add('C2 未保存 colorspace、ycbcr_enc、quantization、xfer_func，四项均为 **UNKNOWN**。参考转换为 OpenCV COLOR_YUV2BGR_YUY2 的 BT.601 limited-range 解释（Y−16，U/V−128）；这是明确声明的软件参考，不是对传感器实际色度的认定。[OpenCV 4.2 官方转换实现](https://raw.githubusercontent.com/opencv/opencv/4.2.0/modules/imgproc/src/color_yuv.simd.hpp)。PSNR 等仅度量 JPEG 相对这一 BGR 参考的损失，不能证明真实色彩准确。未来实时集成仍需保存实际 V4L2 色彩字段。\n')
add('**内存性能实测**\n')
add('每配置排除 5 对预热，48 对真实样本循环 5 次，共 240 对。只用一个编码工作路径，无大量并行或无界缓存。纯编码计时覆盖 tjCompress2 调用，排除 YUYV 转换和 Python 输出复制/释放；完整双目计时包含这些步骤。以下均为双目一对的毫秒数，单眼逐项数据另见 memory_summary.json。\n')
rows=[]
for q in ('90','95'):
    m=S['memory'][q]
    for key,label in [('convert_pair_ms','YUYV→BGR'),('encode_pair_ms','纯 JPEG 编码'),('output_copy_free_pair_ms','输出复制/释放'),('pair_process_ms','双目完整处理')]:
        r=m['metrics'][key];rows.append(['Q'+q,label]+[f'{r[k]:.3f}' for k in ('p50','p95','p99','max')])
table(['配置','阶段','P50 ms','P95 ms','P99 ms','最大 ms'],rows)
add('离线最快连续处理：Q90 **41.405 对/s**，Q95 **40.080 对/s**。进程 CPU 分别约 100.36%、100.49%（单核=100%，含少量监测开销）。这不是固定节拍持续结果。\n')
add('**固定 30 FPS 持续测试**\n')
add('每配置独立执行一次 30 秒实验，绝对 MONOTONIC deadline 每 33.333333ms 输入一对，共 900 对/1800 张；重复使用上述真实样本，不修改其原 Header。计划时刻仅作基准诊断。一个编码工作线程，有界队列容量 4 对，不写 JPEG 图像文件。PASS 要求全部完成、零溢出、每对从计划输入至完成≤33.333333ms；不得通过跳帧或延后基准获得 PASS。\n')
rows=[]
for q in ('90','95'):
    r=S['sustained'][q];d=r['end_to_end_ms'];t=A['telemetry']['sustained_Q'+q]
    rows.append(['Q'+q,f"{r['completed']}/900",r['observed_pairs_per_s']]+[f'{d[k]:.3f}' for k in ('p50','p95','p99','max')]+[r['queue_peak'],r['queue_overflow'],r['deadline_misses_33_333ms'],f"{r['cpu_percent_one_core_100']:.2f}%"])
table(['配置','完成对数','对/s','总延迟P50','P95','P99','最大 ms','队列峰值','溢出','超期','进程CPU'],rows)
add('Q90/Q95 处理本身 P99 为 24.371/25.716ms，计划输入延迟最大 0.462/0.369ms，队列等待最大 0.394/0.417ms。没有持续队列积压。全部逐对数据保留在 sustained_Q90.csv 和 sustained_Q95.csv。\n')
add('**资源与温度观测**\n')
table(['配置/阶段','RSS 起始→结束 / 峰值 MB','CPU温度 起始→结束 / 峰值 °C'],[
['Q'+q+' 持续',f"{A['telemetry']['sustained_Q'+q]['start_rss_MB']:.3f} → {A['telemetry']['sustained_Q'+q]['end_rss_MB']:.3f} / {A['telemetry']['sustained_Q'+q]['peak_rss_MB']:.3f}", ' → '.join(f'{v:.3f}' for v in A['telemetry']['sustained_Q'+q]['cpu_temp_C_start_end_max'][:2])+f" / {A['telemetry']['sustained_Q'+q]['cpu_temp_C_start_end_max'][2]:.3f}"] for q in ('90','95')])
add('全实验 1Hz 采样 RSS 峰值 402.354MB，发生于质量分析；持续编码峰值 334.397MB，未触发 1GiB RSS/剩余可用内存保护。CPU 温度全程采样最高 48.593°C。持续阶段 scaling_cur_freq 读到不同 CPU/频率域的 729.6/1344MHz，热降频/冷却状态采样均为 0；未观察到热限制证据。普通 DVFS 数值不能直接作为降频故障证据，1Hz 采样也不能排除瞬态限制；未锁频、绑核或改变调度策略。INA3221 功率/电流接口不可读，**功耗 UNAVAILABLE**，不能计算能效；CV 温度 -256000 为无效值。没有长期热稳定性结论。\n')
add('**实际文件写盘（与编码分离）**\n')
add('每配置先完成 96 张 JPEG 编码并缓存，再独立计时写 48 对文件；每文件 flush+fdatasync，末尾目录 fsync。下列数字包含实际写入及同步，不含编码和读包。文件均保留供复查。\n')
rows=[]
for q in ('90','95'):
    r=D[q];v=r['pair_write_including_fdatasync_ms'];rows.append(['Q'+q,f'{r["MBps_including_sync"]:.3f}']+[f'{v[k]:.3f}' for k in ('p50','p95','p99','max')])
table(['配置','短批次 MB/s','双目写盘P50 ms','P95','P99','最大'],rows)
add('两批仅约 0.115/0.125 秒，1Hz 遥测没有独立磁盘阶段资源样本；不能据此声称长时磁盘吞吐稳定。逐文件同步最大约 30ms，应由未来独立写线程/有界队列实测评估，不能让逐文件 fdatasync 阻塞正式采集回调。本轮没有实施该集成，也不能将独立编码与写盘的分位数相加当作完整流水线实测。\n')
add('**压缩和质量**\n')
rows=[]
for q in ('90','95'):
    r=A['quality'][q];rows.append(['Q'+q,f"{r['mean_jpeg_bytes']/1000:.3f}",f"{r['ratio']:.2f}:1",f"{r['payload_reduction_percent']:.2f}%",f"{r['psnr_bgr_db']['mean']:.3f}",f"{r['ssim_gray']['mean']:.6f}",f"{r['corner_retention_weighted']*100:.2f}%",f"{r['gradient_mae_fraction_of_ref_mean']['mean']*100:.2f}%"])
table(['配置','单张均值 kB','原YUYV/JPEG','图像载荷减少','PSNR dB','灰度SSIM','角点保持率','归一梯度差'],rows)
add('Q90 文件 61,194–82,207 bytes，Q95 93,983–123,678 bytes。角点保持率按全部参考角点加权；单张最小保持率 Q90 70.54%、Q95 80.10%。梯度幅值平均绝对差分别 1.702、1.278（Sobel 3×3 的灰度幅值单位）。Q95 比 Q90 文件平均大约 52.73%，但角点保持率提高约 7.10 个百分点。\n')
add('方法：PSNR 用全 BGR 像素 MSE；SSIM 用灰度 11×11、σ=1.5 高斯窗口，C1=6.5025、C2=58.5225，去 5 像素边缘；角点用 Shi–Tomasi（最多1000，qualityLevel=0.01，minDistance=7，blockSize=3），参考角点四舍五入位置附近 2px 内有解码图角点即保留，这是非一一匹配的检测重复性指标，不是特征跟踪/SLAM 精度。梯度差为 Sobel 幅值 MAE，归一化分母为参考幅值均值。原 YUYV 4:2:2 转为 JPEG 4:2:0 的色度损失也包含在质量差异中。\n')
add('**ROS 元数据完整性**\n')
add('192/192 个 JPEG 解码为 1280×720 BGR，并构造 sensor_msgs/Image：encoding=bgr8、step=3840、data=2,764,800 bytes。内存序列化/反序列化回环后原始 seq、stamp.sec/nsec、整数 stamp_ns 和 frame_id 全部一致。双目以原 pair_id、sequence、stamp 保持对应。JPEG 文件本身没有 ROS Header；必须连同 jpeg_metadata_integrity.json 与 sample_metadata.json 使用，不能把编码完成时刻当采集时间。未生成正式 CompressedImage 消息流或派生 bag。\n')
add('**整包容量预测，非压缩 bag 实测**\n')
add('原包实际 3.460013078GB，图像原始像素共 3,325,132,800 bytes，图像 ROS 消息开销 100,122 bytes。点云 120,092,420 bytes；MID IMU 2,041,683 bytes；ZED IMU 4,021,710 bytes；锚点 1,111,772 bytes；其他时间戳/有效性/诊断 4,176,401 bytes；容器与索引等差额 3,336,170 bytes。各类消息字节数均来自全包 raw 消息序列化长度，含各自 Header/数组等，未重复计算。\n')
add('估算用真实样本 JPEG 均值×60 张/s，另加非图像数据、预计 CompressedImage Header/format/data 长度字段、原容器差额的线性代理。非图像按本次请求 30 秒会话归一（实际消息记录跨度 32.889s，含启停余量）；图像估算每 30 秒900对，而原包为902对。各分类见 CSV，不忽略点云和双IMU。\n')
pro=list(csv.DictReader((P/'jpeg_storage_projection.csv').open()));rows=[]
for sec in (30,120,300,600,1200):
    a=next(r for r in pro if r['quality']=='90' and int(r['duration_s'])==sec);b=next(r for r in pro if r['quality']=='95' and int(r['duration_s'])==sec)
    rows.append([sec,f"{float(a['raw_C2_linear_GB_est']):.3f}",f"{float(a['stereo_jpeg_payload_bytes_est'])/1e9:.3f}",f"{float(a['total_GB_est']):.3f}",f"{float(b['stereo_jpeg_payload_bytes_est'])/1e9:.3f}",f"{float(b['total_GB_est']):.3f}"])
table(['时长 s','原始C2线性 GB','Q90 双目JPEG GB','Q90 整包估计 GB','Q95 双目JPEG GB','Q95 整包估计 GB'],rows)
add('本场景整包估计减少 Q90 92.48%、Q95 90.57%；平均总数据率估计 8.673/10.875MB/s。单图大小全部取样本 P95 的敏感性场景，30秒整包为 0.271/0.343GB；这不是统计置信上界。实际 JPEG bag 的 chunk/index、消息布局、变化场景、额外 sidecar/文件系统分配和新 CameraInfo 都可能改变容量，本模型未加入后两类额外内容。没有声称已取得这些整包写盘收益。\n')
add('**文件、测试和复现**\n')
add('独立实验代码目录：`'+str(B)+'`。新增 codec.py、monitor.py、benchmark.py、test_benchmark.py、run_benchmark.sh、make_report.py，另保存 encoder/OpenCV 环境、保护哈希和软件测试日志。Python 实际执行完成，调用已安装本地共享库，无 C++ 或生产 catkin 构建改动。4 项独立软件测试通过：明确420编码/参考黑白转换、坏JPEG拒绝、Header整数精度、相同图像质量指标；合成输入仅用于软件测试，实测性能和质量全部使用真实样本。\n')
add('本次结果目录：`'+str(P)+'`。\n')
for name in ['jpeg_benchmark.csv','jpeg_quality.csv','jpeg_storage_projection.csv','jpeg_metadata_integrity.json','sample_metadata.json','memory_summary.json','disk_summary.json','sustained_Q90.csv','sustained_Q95.csv','resources.jsonl','analysis_summary.json','summary.json','bag_accounting.json','environment.json']:
    add('- ['+name+']('+str(P/name)+')')
add('\n上述测试已执行完毕，无需再次运行。如以后获准复现，普通 SSH 命令为：\n\n```bash\n'+str(B/'run_benchmark.sh')+'\n```\n')
add('脚本每次创建唯一 run 目录，读取同一源会话，内存限制 1GiB、最低可用内存 1GiB、持续队列容量4；中断/失败写 summary，保留已有输出，不重试或覆盖。当前结果不会被下次覆盖。\n')
add('**遗留问题与下一阶段边界**\n')
add('C2 原有首条 ZED IMU 启动异常、433 次锚点漏读、L2-B/物理同步和720P标定待验状态全部保留，本实验不改变其验收。约1.28%设备时间比例差也未研究或修正。正式采集核心、默认1080P及独立720P配置均未修改。\n')
add('建议候选为 Q95/4:2:0：本场景持续 P99 26.110ms，比周期余约7.22ms，最差26.870ms；角点与梯度损失较Q90小。Q90则提供更低容量和延迟。此建议仅依据本次真实数据的相对结果，不构成复杂场景实时保证。获授权后才考虑有界影子编码与原采集并发、保留完整原始记录并观察资源/队列/颜色元数据；本轮不实施生产 JPEG 链路。\n')
add('回退无需恢复生产文件：此次只增加独立实验目录及本报告；停止调用实验脚本即可。保留原始记录与本次证据，不执行删除。')
report=pathlib.Path('/home/jetson/zed_capture_ws/zed_720p_jpeg_jetson_benchmark.md')
with report.open('x') as f:f.write('\n'.join(lines)+'\n')
print(report)
