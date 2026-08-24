package com.codex.androidperflab.overlay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.ServiceInfo
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

class OverlayService : Service() {
    companion object {
        private const val CHANNEL_ID = "perf_lab_overlay"
        private const val NOTIFICATION_ID = 1001
        private const val STREAM_URL = "http://127.0.0.1:8765/api/overlay/stream"
    }

    private val running = AtomicBoolean(false)
    private val mainHandler = Handler(Looper.getMainLooper())
    private lateinit var windowManager: WindowManager
    private var overlayView: LinearLayout? = null
    private lateinit var panelBackground: GradientDrawable
    private var connection: HttpURLConnection? = null
    private lateinit var preferences: SharedPreferences
    private lateinit var statusView: TextView
    private lateinit var fpsView: TextView
    private lateinit var fpsChartView: FpsChartView
    private lateinit var cpuView: TextView
    private lateinit var memoryView: TextView
    private lateinit var cpuTemperatureView: TextView
    private lateinit var gpuTemperatureView: TextView
    private lateinit var batteryTemperatureView: TextView
    private lateinit var batteryView: TextView
    private lateinit var timeView: TextView
    private var lastFpsSampleToken: String? = null
    private var captureTimerActive = false
    private var timerBaseSeconds = 0.0
    private var timerBaseRealtimeMs = 0L
    private val elapsedTicker = object : Runnable {
        override fun run() {
            updateElapsedTime()
            if (running.get()) mainHandler.postDelayed(this, 250)
        }
    }
    private val preferenceListener = SharedPreferences.OnSharedPreferenceChangeListener { _, _ ->
        mainHandler.post { applyMetricVisibility() }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        val notification = createNotification()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        preferences = OverlayPreferences.preferences(this)
        preferences.registerOnSharedPreferenceChangeListener(preferenceListener)
        showOverlay()
        mainHandler.post(elapsedTicker)
        startStreaming()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        running.set(false)
        if (::preferences.isInitialized) {
            preferences.unregisterOnSharedPreferenceChangeListener(preferenceListener)
        }
        connection?.disconnect()
        mainHandler.removeCallbacks(elapsedTicker)
        overlayView?.let {
            try {
                windowManager.removeView(it)
            } catch (_: Exception) {
            }
        }
        overlayView = null
        super.onDestroy()
    }

    private fun showOverlay() {
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        panelBackground = GradientDrawable().apply {
            cornerRadius = dp(9).toFloat()
            setColor(Color.argb(232, 7, 20, 34))
            setStroke(dp(1), Color.rgb(38, 85, 111))
        }
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(7), dp(5), dp(7), dp(6))
            background = panelBackground
            elevation = dp(6).toFloat()
        }

        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        fpsView = metricText("-- FPS", 12f, Color.WHITE).apply {
            setTypeface(Typeface.MONOSPACE, Typeface.BOLD)
            includeFontPadding = false
        }
        header.addView(
            fpsView,
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
        )
        statusView = metricText("连接中", 8f, Color.rgb(255, 190, 92)).apply {
            setTypeface(Typeface.DEFAULT, Typeface.BOLD)
            gravity = Gravity.CENTER
            includeFontPadding = false
            setPadding(dp(5), dp(2), dp(5), dp(2))
            contentDescription = "正在连接电脑"
        }
        updateStatusBadge("连接中", Color.rgb(255, 190, 92), "正在连接电脑")
        header.addView(
            statusView,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { marginEnd = dp(2) },
        )
        header.addView(metricText("⚙", 13f, Color.rgb(185, 211, 229)).apply {
            contentDescription = "设置悬浮窗指标"
            gravity = Gravity.CENTER
            typeface = Typeface.DEFAULT
            minWidth = dp(26)
            minHeight = dp(26)
            setOnClickListener { openSettings() }
        })
        header.addView(metricText("×", 15f, Color.WHITE).apply {
            contentDescription = "关闭悬浮窗"
            gravity = Gravity.CENTER
            minWidth = dp(24)
            minHeight = dp(26)
            setOnClickListener { stopSelf() }
        })
        panel.addView(header)

        fpsChartView = FpsChartView(this)
        panel.addView(
            fpsChartView,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(28),
            ).apply { topMargin = dp(1) },
        )
        cpuView = metricText("CPU A/T  --/--\nGPU      --", 9.5f, Color.rgb(132, 170, 255))
        memoryView = metricText("RAM  --", 9.5f, Color.rgb(255, 184, 100))
        cpuTemperatureView = metricText("CPU 温度  --", 10f, Color.rgb(255, 111, 121))
        gpuTemperatureView = metricText("GPU 温度  --", 10f, Color.rgb(255, 139, 110))
        batteryTemperatureView = metricText("电池温度  --", 10f, Color.rgb(255, 171, 111))
        batteryView = metricText("电量      --", 10f, Color.rgb(101, 220, 157))
        timeView = metricText("00:00", 9f, Color.rgb(173, 196, 214))
        listOf(
            cpuView,
            memoryView,
            timeView,
            cpuTemperatureView,
            gpuTemperatureView,
            batteryTemperatureView,
            batteryView,
        ).forEach {
            it.setPadding(0, 0, 0, 0)
            panel.addView(it)
        }
        applyMetricVisibility()

        val params = WindowManager.LayoutParams(
            dp(158),
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = dp(8)
            y = dp(72)
        }
        panel.setOnTouchListener(DragTouchListener(params))
        windowManager.addView(panel, params)
        overlayView = panel
    }

    private fun startStreaming() {
        if (!running.compareAndSet(false, true)) return
        Thread({
            while (running.get()) {
                try {
                    updateConnectionState("Perf Lab · 正在连接")
                    val opened = (URL(STREAM_URL).openConnection() as HttpURLConnection).apply {
                        requestMethod = "GET"
                        connectTimeout = 3000
                        readTimeout = 0
                        setRequestProperty("Accept", "text/event-stream")
                        useCaches = false
                    }
                    connection = opened
                    opened.connect()
                    if (opened.responseCode != 200) {
                        throw IllegalStateException("HTTP ${opened.responseCode}")
                    }
                    updateConnectionState("Perf Lab · 已连接")
                    BufferedReader(InputStreamReader(opened.inputStream, Charsets.UTF_8)).use { reader ->
                        while (running.get()) {
                            val line = reader.readLine() ?: break
                            if (line.startsWith("data:")) {
                                val payload = JSONObject(line.substringAfter("data:").trim())
                                mainHandler.post { render(payload) }
                            }
                        }
                    }
                } catch (_: Exception) {
                    updateConnectionState("Perf Lab · 等待电脑")
                    if (running.get()) Thread.sleep(1800)
                } finally {
                    connection?.disconnect()
                    connection = null
                }
            }
        }, "perf-overlay-stream").apply {
            isDaemon = true
            start()
        }
    }

    private fun render(data: JSONObject) {
        val status = data.optString("status", "idle")
        val statusText = data.optString("status_text", "等待任务")
        updateSessionState(status, statusText)
        fpsView.text = if (data.isNull("realtime_fps")) {
            "-- FPS"
        } else {
            "${format(data.optDouble("realtime_fps"), 1)} FPS"
        }
        cpuView.text = formatCpu(data)
        memoryView.text = formatMemory(data)
        cpuTemperatureView.text = "CPU 温度  ${formatValue(data, "cpu_temperature_c", "°C")}" 
        gpuTemperatureView.text = "GPU 温度  ${formatValue(data, "gpu_temperature_c", "°C")}" 
        batteryTemperatureView.text = "电池温度  ${formatValue(data, "battery_temperature_c", "°C")}" 
        batteryView.text = "电量      ${formatValue(data, "battery_level_percent", "%")}" 
        timerBaseSeconds = data.optDouble("elapsed_seconds", 0.0).coerceAtLeast(0.0)
        timerBaseRealtimeMs = SystemClock.elapsedRealtime()
        captureTimerActive = status in setOf("starting", "capturing", "stopping")
        updateElapsedTime()
        val sampleToken = if (data.isNull("fps_sample_token")) null else {
            data.optString("fps_sample_token")
        }
        if (sampleToken != null && sampleToken != lastFpsSampleToken && !data.isNull("realtime_fps")) {
            fpsChartView.addSample(data.optDouble("realtime_fps"))
            lastFpsSampleToken = sampleToken
        }
    }

    private fun updateElapsedTime() {
        if (!::timeView.isInitialized) return
        val localDelta = if (captureTimerActive) {
            (SystemClock.elapsedRealtime() - timerBaseRealtimeMs).coerceAtLeast(0L) / 1000.0
        } else {
            0.0
        }
        val seconds = (timerBaseSeconds + localDelta).toInt().coerceAtLeast(0)
        timeView.text = String.format(Locale.US, "%02d:%02d", seconds / 60, seconds % 60)
    }

    private fun applyMetricVisibility() {
        if (!::fpsView.isInitialized) return
        fpsView.visibility = metricVisibility(OverlayPreferences.REALTIME_FPS)
        fpsChartView.visibility = metricVisibility(OverlayPreferences.FPS_CHART)
        cpuView.visibility = metricVisibility(OverlayPreferences.APP_CPU)
        memoryView.visibility = metricVisibility(OverlayPreferences.MEMORY)
        cpuTemperatureView.visibility = metricVisibility(OverlayPreferences.CPU_TEMPERATURE)
        gpuTemperatureView.visibility = metricVisibility(OverlayPreferences.GPU_TEMPERATURE)
        batteryTemperatureView.visibility = metricVisibility(OverlayPreferences.BATTERY_TEMPERATURE)
        batteryView.visibility = metricVisibility(OverlayPreferences.BATTERY_LEVEL)
        timeView.visibility = metricVisibility(OverlayPreferences.ELAPSED_TIME)
    }

    private fun metricVisibility(key: String): Int = if (
        OverlayPreferences.enabled(preferences, key)
    ) View.VISIBLE else View.GONE

    private fun openSettings() {
        startActivity(Intent(this, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        })
    }

    private fun formatValue(data: JSONObject, key: String, suffix: String): String {
        if (data.isNull(key) || !data.has(key)) return "--"
        return format(data.optDouble(key), 1) + suffix
    }

    private fun formatMemory(data: JSONObject): String {
        if (data.isNull("memory_mb") || !data.has("memory_mb")) return "RAM  --"
        val memoryMb = data.optDouble("memory_mb")
        val memoryText = if (memoryMb >= 1024.0) {
            "${format(memoryMb / 1024.0, 1)}G"
        } else {
            "${format(memoryMb, 0)}M"
        }
        val percentText = if (
            data.isNull("memory_usage_percent") || !data.has("memory_usage_percent")
        ) {
            ""
        } else {
            "  ${format(data.optDouble("memory_usage_percent"), 1)}%"
        }
        return "RAM  $memoryText$percentText"
    }

    private fun formatCpu(data: JSONObject): String {
        val appText = if (
            data.isNull("app_cpu_normalized_percent") ||
            !data.has("app_cpu_normalized_percent")
        ) {
            "--"
        } else {
            "${format(data.optDouble("app_cpu_normalized_percent"), 1)}%"
        }
        val totalText = if (
            data.isNull("system_cpu_percent") || !data.has("system_cpu_percent")
        ) {
            "--"
        } else {
            "${format(data.optDouble("system_cpu_percent"), 1)}%"
        }
        val gpuText = if (
            data.isNull("gpu_usage_percent") || !data.has("gpu_usage_percent")
        ) {
            "N/A"
        } else {
            "${format(data.optDouble("gpu_usage_percent"), 1)}%"
        }
        return "CPU A/T  $appText/$totalText\nGPU      $gpuText"
    }

    private fun format(value: Double, digits: Int): String =
        String.format(Locale.US, "%.${digits}f", value)

    private fun updateConnectionState(text: String) {
        mainHandler.post {
            if (::statusView.isInitialized) {
                val connected = text.contains("已连接")
                updateStatusBadge(
                    if (connected) "已连接" else if (text.contains("等待")) "待电脑" else "连接中",
                    if (connected) Color.rgb(66, 216, 145) else Color.rgb(255, 190, 92),
                    text,
                )
            }
        }
    }

    private fun updateSessionState(status: String, statusText: String) {
        val label = when (status) {
            "capturing" -> "采集中"
            "failed" -> "已失败"
            "starting" -> "启动中"
            "stopping" -> "结束中"
            "analyzing" -> "分析中"
            "completed" -> "已完成"
            else -> "待机"
        }
        val color = when (status) {
            "capturing" -> Color.rgb(66, 216, 145)
            "failed" -> Color.rgb(255, 96, 108)
            "starting", "stopping", "analyzing" -> Color.rgb(255, 190, 92)
            "completed" -> Color.rgb(66, 216, 207)
            else -> Color.rgb(142, 166, 185)
        }
        updateStatusBadge(label, color, statusText)
    }

    private fun updateStatusBadge(label: String, color: Int, description: String) {
        statusView.text = label
        statusView.contentDescription = description
        statusView.setTextColor(color)
        statusView.background = GradientDrawable().apply {
            cornerRadius = dp(8).toFloat()
            setColor(Color.argb(30, Color.red(color), Color.green(color), Color.blue(color)))
            setStroke(dp(1), Color.argb(88, Color.red(color), Color.green(color), Color.blue(color)))
        }
        if (::panelBackground.isInitialized) {
            panelBackground.setStroke(
                dp(1),
                Color.argb(120, Color.red(color), Color.green(color), Color.blue(color)),
            )
        }
    }

    private fun metricText(textValue: String, size: Float, color: Int) = TextView(this).apply {
        text = textValue
        textSize = size
        setTextColor(color)
        typeface = Typeface.MONOSPACE
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "性能悬浮窗",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "保持性能数据悬浮窗运行"
                setShowBadge(false)
            }
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(channel)
        }
    }

    private fun createNotification(): Notification {
        val activityIntent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            activityIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentTitle("Perf Lab Overlay")
            .setContentText("性能悬浮窗正在运行")
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private inner class DragTouchListener(
        private val params: WindowManager.LayoutParams,
    ) : View.OnTouchListener {
        private var startX = 0
        private var startY = 0
        private var touchX = 0f
        private var touchY = 0f

        override fun onTouch(view: View, event: MotionEvent): Boolean {
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    startX = params.x
                    startY = params.y
                    touchX = event.rawX
                    touchY = event.rawY
                    return true
                }
                MotionEvent.ACTION_MOVE -> {
                    params.x = startX + (event.rawX - touchX).toInt()
                    params.y = startY + (event.rawY - touchY).toInt()
                    overlayView?.let { windowManager.updateViewLayout(it, params) }
                    return true
                }
                MotionEvent.ACTION_UP -> {
                    if (kotlin.math.abs(event.rawX - touchX) < dp(4) &&
                        kotlin.math.abs(event.rawY - touchY) < dp(4)
                    ) {
                        view.performClick()
                    }
                    return true
                }
            }
            return false
        }
    }
}
