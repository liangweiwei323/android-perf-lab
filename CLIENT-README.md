# Android Perf Lab Windows 客户端

## 使用方法

1. 解压整个目录，不要只复制 `AndroidPerfLab.exe`。
2. 手机开启“开发者选项”和“USB调试”，使用数据线连接电脑。
3. 如 Windows 无法识别手机，请先安装手机厂商的 USB 驱动。
4. 双击 `AndroidPerfLab.exe`，在手机上确认 USB 调试授权。
5. 在客户端选择设备、应用和采集时长，然后开始采集。
6. 测试结束后可打开 HTML 报告；Trace、报告和日志保存在客户端旁的 `data` 目录。

## 手机悬浮窗

点击客户端右上角“安装悬浮窗”。安装后请在手机上允许悬浮窗权限。悬浮窗通过 ADB reverse 连接本机客户端，不依赖互联网。

悬浮窗右上角的齿轮可返回 APK 设置页，实时开关 FPS、FPS 波动曲线、CPU、内存、温度、电量和采集时长等显示项；设置会立即生效并自动保存。

默认采用紧凑布局，仅显示状态点、实时FPS、FPS曲线、CPU App/整机、RAM容量/占比和时间；温度、电量默认关闭，可在齿轮设置中按需开启。

App CPU 与 Total CPU 默认采用和 SoloX 一致的整机归一化口径（0–100%）。HTML 报告会同时显示两者的平均值、峰值和曲线，并保留可能超过 100% 的“单核累加”值用于分析多核并行负载。

GPU占用当前使用经过真机验证的 Qualcomm KGSL `gpubusy` 忙碌/总窗口，桌面、悬浮窗及HTML报告都会显示。设备没有该节点时显示 N/A，不以频率或温度推算。由于读取该节点会消费统计窗口，与 SoloX 同时采集GPU可能互相干扰；做同机对比时建议只让一个软件记录GPU。

对于盖世游戏、Winlator 等多进程模拟器，CPU 与内存会按应用 UID 聚合模拟核心、Wine 和 PC 游戏原生进程；内存显示为总 PSS 及其占设备物理内存的比例。

测试完成后，HTML报告会按60FPS目标生成帧率综合评价，包含目标达成、低帧、稳定性、卡顿四个维度，并统计低于30/24/20/15FPS的时间占比和最长连续时长。该评分为Android Perf Lab透明自定义评分，并非PerfDog官方总分。

## 环境要求

- Windows 10/11 64 位
- Android 10 或更高版本
- Microsoft Edge WebView2 Runtime（Windows 10/11 通常已经安装）
- 已授权的 ADB USB 连接

## 常见问题

- 客户端启动失败：查看 `data/client.log`。
- 设备列表为空：重新插拔数据线，确认 USB 用途不是“仅充电”，并接受手机上的调试授权弹窗。
- FPS 没有数据：确认目标应用位于前台并持续刷新画面。
- 杀毒软件提示未知发布者：当前测试版尚未进行 Windows 代码签名。

此版本为本地客户端，采集数据不会自动上传。

## 许可与归属

Android Perf Lab 的原创源码采用 Apache License 2.0。客户端中包含或调用的第三方
组件仍适用各自许可证。本目录中的 `LICENSE`、`NOTICE`、
`THIRD_PARTY_NOTICES.md`、`PERFETTO-TOOLS-LICENSE.txt`、Android Platform-Tools
`NOTICE.txt` 以及 `licenses/` 目录均属于分发材料，请勿删除。

Android Perf Lab 是独立项目，与文档中提及的 Google、Android、Perfetto、PerfDog、
SoloX、Qualcomm、Microsoft、Gracker 等项目或权利人不存在官方隶属或背书关系；相关
名称仅用于兼容性和技术说明，商标归各自权利人所有。
