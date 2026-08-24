package com.codex.androidperflab.overlay

import android.content.Context
import android.content.SharedPreferences

object OverlayPreferences {
    const val FILE_NAME = "overlay_preferences"
    const val REALTIME_FPS = "realtime_fps"
    const val FPS_CHART = "fps_chart"
    const val APP_CPU = "app_cpu"
    const val MEMORY = "memory"
    const val CPU_TEMPERATURE = "cpu_temperature"
    const val GPU_TEMPERATURE = "gpu_temperature"
    const val BATTERY_TEMPERATURE = "battery_temperature"
    const val BATTERY_LEVEL = "battery_level"
    const val ELAPSED_TIME = "elapsed_time"

    val options = listOf(
        REALTIME_FPS to "实时 FPS",
        FPS_CHART to "FPS 波动曲线",
        APP_CPU to "CPU（App / 整机）与 GPU 占用",
        MEMORY to "内存",
        CPU_TEMPERATURE to "CPU 温度",
        GPU_TEMPERATURE to "GPU 温度",
        BATTERY_TEMPERATURE to "电池温度",
        BATTERY_LEVEL to "电量",
        ELAPSED_TIME to "采集时长",
    )

    private val enabledByDefault = setOf(
        REALTIME_FPS,
        FPS_CHART,
        APP_CPU,
        MEMORY,
        ELAPSED_TIME,
    )

    fun preferences(context: Context): SharedPreferences =
        context.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE)

    fun enabled(preferences: SharedPreferences, key: String): Boolean =
        preferences.getBoolean(key, key in enabledByDefault)
}
