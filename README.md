# Android Perf Lab

面向 Android 游戏/模拟器的本地性能采集与确定性报告工具。第一版复用
`D:\codex\perfetto-tools` 进行 Perfetto FrameTimeline 采集，并独立计算FPS、
Frame Time、掉帧、Jank、CPU、内存和温度指标，不依赖AI。

## 启动

```powershell
cd D:\codex\android-perf-lab
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

浏览器打开 <http://127.0.0.1:8765>。

## 第一版范围

- 自动识别ADB设备和第三方应用
- 5秒至3600秒定时采集
- 实时 App CPU、Total CPU、GPU占用、Total PSS、CPU/GPU/电池温度
- FrameTimeline最终呈现FPS和Surface来源拆分
- 独立SurfaceFlinger TimeStats实时FPS（1秒统计窗，前端0.5秒刷新）
- 平均FPS、1秒FPS范围、P5/P1 Low、Frame Time分位数、掉帧率、Jank率
- SQLite任务历史和离线中文HTML报告

## 当前口径与限制

- App CPU 与 Total CPU 默认采用和 SoloX 一致的整机归一化口径，范围 0–100%；
  HTML 报告另保留可超过 100% 的“单核累加”值用于多核并行诊断。
- GPU占用当前仅采集经过真机验证的 Qualcomm KGSL `gpubusy` 忙碌/总窗口；
  节点不支持时明确显示 N/A，不以GPU频率或温度估算占用率。该节点读取会消费
  当前统计窗口，因此与 SoloX 同时采集GPU可能互相干扰，建议GPU只由一个工具记录。
- FPS优先选择`display`（SurfaceFlinger最终输出）；缺失时选择包名匹配Surface。
- 实时FPS按PerfDog公开口径使用1秒内真实画面平均刷新次数；优先应用Surface，
  缺失时回退到全局最终显示帧率，并按屏幕刷新率封顶。
- P5/P1 Low基于1秒FPS桶，不等同于GPU工具的逐帧1% Low实现。
- GameHub插帧会反映在最终呈现FPS中；原始PC渲染FPS需要DXVK/VKD3D遥测。
- GPU使用率与功耗尚未纳入第一版；厂商节点差异将在后续版本适配。

## 手机悬浮窗 APK

源码位于 `android-overlay/`，构建产物位于：

```text
dist/PerfLabOverlay-v0.1.1-debug.apk
```

安装与启动：

```powershell
adb install -r .\dist\PerfLabOverlay-v0.1.1-debug.apk
adb shell monkey -p com.codex.androidperflab.overlay `
  -c android.intent.category.LAUNCHER 1
```

在手机中点击“授权并启动悬浮窗”，允许“显示在其他应用上层”。电脑端开始
任务时会自动执行 `adb reverse tcp:8765 tcp:8765`，APK通过本地SSE连接实时
显示实时FPS、App CPU、Total CPU、GPU占用、内存、CPU/GPU温度、电量和已采集时间；任务完成后
FPS切换为最终平均值。

重新构建APK：

```powershell
cd .\android-overlay
$env:JAVA_HOME = "D:\android\jbr"
.\gradlew.bat assembleDebug
```
