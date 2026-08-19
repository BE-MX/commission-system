package com.leshine.pdareporting

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

object Ui {
    val green: Int = Color.rgb(0, 115, 72)
    val greenBright: Int = Color.rgb(10, 166, 111)
    val greenSoft: Int = Color.rgb(232, 245, 239)
    val ink: Int = Color.rgb(24, 43, 35)
    val secondary: Int = Color.rgb(85, 105, 96)
    val muted: Int = Color.rgb(139, 153, 147)
    val border: Int = Color.rgb(219, 229, 224)
    val page: Int = Color.rgb(243, 246, 244)
    val danger: Int = Color.rgb(192, 57, 43)
    val warning: Int = Color.rgb(180, 118, 18)

    fun dp(context: Context, value: Int): Int =
        (value * context.resources.displayMetrics.density).toInt()

    fun rounded(color: Int, radiusDp: Int, context: Context, strokeColor: Int? = null): GradientDrawable =
        GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(context, radiusDp).toFloat()
            if (strokeColor != null) setStroke(dp(context, 1), strokeColor)
        }

    fun text(
        context: Context,
        value: String,
        sizeSp: Float = 14f,
        color: Int = ink,
        bold: Boolean = false,
    ) = TextView(context).apply {
        text = value
        textSize = sizeSp
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
        includeFontPadding = false
    }

    fun button(
        context: Context,
        label: String,
        primary: Boolean = true,
        onClick: () -> Unit,
    ) = Button(context).apply {
        text = label
        textSize = 14f
        isAllCaps = false
        setTextColor(if (primary) Color.WHITE else green)
        background = rounded(if (primary) green else Color.WHITE, 10, context, if (primary) null else border)
        setOnClickListener { onClick() }
        minHeight = dp(context, 48)
    }

    fun vertical(context: Context, paddingDp: Int = 0) = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        if (paddingDp > 0) setPadding(dp(context, paddingDp), dp(context, paddingDp), dp(context, paddingDp), dp(context, paddingDp))
    }

    fun margin(
        width: Int = ViewGroup.LayoutParams.MATCH_PARENT,
        height: Int = ViewGroup.LayoutParams.WRAP_CONTENT,
        left: Int = 0,
        top: Int = 0,
        right: Int = 0,
        bottom: Int = 0,
        context: Context,
    ) = LinearLayout.LayoutParams(width, height).apply {
        setMargins(dp(context, left), dp(context, top), dp(context, right), dp(context, bottom))
    }
}

