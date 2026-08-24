package com.codex.androidperflab.overlay

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.util.TypedValue
import android.view.View
import java.util.Locale
import kotlin.math.abs

class FpsChartView(context: Context) : View(context) {
    private val samples = ArrayDeque<Float>()
    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(38, 67, 88)
        strokeWidth = dp(1).toFloat()
    }
    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(66, 216, 207)
        strokeWidth = resources.displayMetrics.density * 1.4f
        style = Paint.Style.STROKE
        strokeJoin = Paint.Join.ROUND
        strokeCap = Paint.Cap.ROUND
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(153, 183, 204)
        textSize = TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_SP,
            6.5f,
            resources.displayMetrics,
        )
    }

    fun addSample(value: Double) {
        if (!value.isFinite() || value < 0) return
        samples.addLast(value.toFloat())
        while (samples.size > 60) samples.removeFirst()
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (samples.isEmpty()) {
            canvas.drawText("等待 FPS 数据", dp(3).toFloat(), dp(14).toFloat(), textPaint)
            return
        }
        val values = samples.toList()
        var low = values.minOrNull() ?: 0f
        var high = values.maxOrNull() ?: 1f
        if (abs(high - low) < 0.1f) {
            low -= 1f
            high += 1f
        }
        val left = dp(21).toFloat()
        val right = width - dp(3).toFloat()
        val top = dp(3).toFloat()
        val bottom = height - dp(7).toFloat()
        for (index in 0..2) {
            val y = top + (bottom - top) * index / 2f
            canvas.drawLine(left, y, right, y, gridPaint)
        }
        canvas.drawText(String.format(Locale.US, "%.0f", high), dp(1).toFloat(), top + dp(6), textPaint)
        canvas.drawText(String.format(Locale.US, "%.0f", low), dp(1).toFloat(), bottom, textPaint)
        val path = Path()
        values.forEachIndexed { index, value ->
            val x = if (values.size == 1) right else {
                left + (right - left) * index / (values.size - 1).toFloat()
            }
            val y = top + (bottom - top) * (high - value) / (high - low)
            if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        canvas.drawPath(path, linePaint)
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
