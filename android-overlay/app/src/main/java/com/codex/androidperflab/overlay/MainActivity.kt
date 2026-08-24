package com.codex.androidperflab.overlay

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView

class MainActivity : Activity() {
    private lateinit var statusText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Perf Lab Overlay"
        setContentView(buildContent())
        requestNotificationPermission()
    }

    override fun onResume() {
        super.onResume()
        updatePermissionStatus()
    }

    private fun buildContent(): ScrollView {
        val scroll = ScrollView(this).apply {
            setBackgroundColor(Color.rgb(7, 17, 29))
            isFillViewport = true
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(28), dp(24), dp(24))
            setBackgroundColor(Color.rgb(7, 17, 29))
        }
        scroll.addView(root, matchWrap())
        root.addView(TextView(this).apply {
            text = "Perf Lab Overlay"
            textSize = 27f
            setTextColor(Color.WHITE)
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        })
        root.addView(TextView(this).apply {
            text = "电脑端采集，手机端只负责悬浮显示"
            textSize = 14f
            setTextColor(Color.rgb(126, 166, 192))
            setPadding(0, dp(6), 0, dp(24))
        })

        statusText = TextView(this).apply {
            textSize = 15f
            setTextColor(Color.rgb(66, 216, 207))
            setPadding(dp(14), dp(14), dp(14), dp(14))
            setBackgroundColor(Color.rgb(13, 34, 51))
        }
        root.addView(statusText, matchWrap())

        root.addView(Button(this).apply {
            text = "授权并启动悬浮窗"
            isAllCaps = false
            setOnClickListener { startOverlay() }
        }, marginTop(18))

        root.addView(Button(this).apply {
            text = "停止悬浮窗"
            isAllCaps = false
            setOnClickListener {
                stopService(Intent(this@MainActivity, OverlayService::class.java))
                statusText.text = "悬浮窗已停止"
            }
        }, marginTop(10))

        root.addView(TextView(this).apply {
            text = "悬浮窗显示指标"
            textSize = 18f
            setTextColor(Color.WHITE)
            setTypeface(typeface, android.graphics.Typeface.BOLD)
            setPadding(0, dp(28), 0, dp(8))
        }, matchWrap())

        root.addView(TextView(this).apply {
            text = "开关会立即同步到正在运行的悬浮窗"
            textSize = 13f
            setTextColor(Color.rgb(126, 166, 192))
            setPadding(0, 0, 0, dp(6))
        }, matchWrap())

        val preferences = OverlayPreferences.preferences(this)
        OverlayPreferences.options.forEach { (key, label) ->
            @Suppress("DEPRECATION")
            root.addView(Switch(this).apply {
                text = label
                textSize = 15f
                setTextColor(Color.rgb(220, 235, 245))
                setPadding(dp(4), dp(5), dp(4), dp(5))
                isChecked = OverlayPreferences.enabled(preferences, key)
                setOnCheckedChangeListener { _, checked ->
                    preferences.edit().putBoolean(key, checked).apply()
                }
            }, matchWrap())
        }

        root.addView(TextView(this).apply {
            text = "使用步骤\n\n1. 保持USB调试连接\n2. 启动悬浮窗\n3. 在电脑打开 Android Perf Lab 并开始任务\n4. 端口转发会在任务开始时自动建立\n\n悬浮窗右上角齿轮可随时返回本页调整显示项。"
            textSize = 14f
            setTextColor(Color.rgb(188, 207, 223))
            setLineSpacing(0f, 1.2f)
            setPadding(0, dp(26), 0, 0)
        }, matchWrap())
        return scroll
    }

    private fun startOverlay() {
        if (!Settings.canDrawOverlays(this)) {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName"),
            )
            startActivity(intent)
            statusText.text = "请允许“显示在其他应用上层”，然后返回再次点击启动"
            return
        }
        val intent = Intent(this, OverlayService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
        statusText.text = "悬浮窗已启动，等待电脑端数据"
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
        }
    }

    private fun updatePermissionStatus() {
        statusText.text = if (Settings.canDrawOverlays(this)) {
            "悬浮窗权限：已授权"
        } else {
            "悬浮窗权限：未授权"
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
    private fun matchWrap() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
    )
    private fun marginTop(value: Int) = matchWrap().apply { topMargin = dp(value) }
}
