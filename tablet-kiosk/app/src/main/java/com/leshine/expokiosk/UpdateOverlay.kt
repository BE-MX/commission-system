package com.leshine.expokiosk

import android.content.Context
import android.graphics.Color
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView

enum class UpdateMessage {
    CHECKING,
    DOWNLOADING,
    AWAITING_USER_ACTION,
    INSTALLING,
    FAILURE,
}

/** Thread-safe update state that never regresses from a released terminal state to blocking. */
internal class UpdateSessionState {
    private val lock = Any()
    private var value: UpdateState? = null

    fun transition(next: UpdateState): UpdateState = synchronized(lock) {
        val current = value
        if (current != null && current.isReleaseTerminal() && next.isBlockingActive()) {
            current
        } else {
            value = next
            next
        }
    }

    fun current(): UpdateState? = synchronized(lock) { value }

    private fun UpdateState.isReleaseTerminal(): Boolean =
        this == UpdateState.NoUpdate || this is UpdateState.Failed

    private fun UpdateState.isBlockingActive(): Boolean = when (this) {
        UpdateState.Checking,
        is UpdateState.Downloading,
        UpdateState.AwaitingUserAction,
        UpdateState.Installing,
        -> true
        UpdateState.NoUpdate,
        is UpdateState.Failed,
        -> false
    }
}

internal object UpdateInteractionPolicy {
    fun allowMaintenanceGestures(blocksKiosk: Boolean): Boolean = !blocksKiosk
}

data class UpdatePresentation(
    val blocksKiosk: Boolean,
    val message: UpdateMessage?,
    val versionName: String? = null,
    val progress: Int? = null,
) {
    companion object {
        fun from(state: UpdateState): UpdatePresentation = when (state) {
            UpdateState.Checking -> UpdatePresentation(true, UpdateMessage.CHECKING)
            is UpdateState.Downloading -> UpdatePresentation(
                blocksKiosk = true,
                message = UpdateMessage.DOWNLOADING,
                versionName = state.versionName,
                progress = state.progress.coerceIn(0, 100),
            )
            UpdateState.AwaitingUserAction -> UpdatePresentation(
                true,
                UpdateMessage.AWAITING_USER_ACTION,
            )
            UpdateState.Installing -> UpdatePresentation(true, UpdateMessage.INSTALLING)
            UpdateState.NoUpdate -> UpdatePresentation(false, null)
            is UpdateState.Failed -> UpdatePresentation(false, UpdateMessage.FAILURE)
        }
    }
}

/** Full-screen, non-interactive gate shown while a startup update is in progress. */
class UpdateOverlay(context: Context) : FrameLayout(context) {
    private val title = TextView(context).apply {
        setText(R.string.update_title)
        setTextColor(Color.rgb(212, 175, 55))
        textSize = 28f
        gravity = Gravity.CENTER
    }
    private val detail = TextView(context).apply {
        setTextColor(Color.rgb(154, 160, 166))
        textSize = 16f
        gravity = Gravity.CENTER
        autoLinkMask = 0
        linksClickable = false
    }
    private val progressBar = ProgressBar(
        context,
        null,
        android.R.attr.progressBarStyleHorizontal,
    ).apply {
        max = 100
        isIndeterminate = true
    }

    init {
        visibility = View.GONE
        setBackgroundColor(Color.BLACK)
        isClickable = true
        isFocusable = true
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES

        val content = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            val horizontalPadding = dp(48)
            setPadding(horizontalPadding, dp(32), horizontalPadding, dp(32))
            addView(title, LinearLayout.LayoutParams(MATCH, WRAP))
            addView(detail, LinearLayout.LayoutParams(MATCH, WRAP).apply {
                topMargin = dp(14)
            })
            addView(progressBar, LinearLayout.LayoutParams(MATCH, dp(6)).apply {
                topMargin = dp(28)
            })
        }
        addView(
            content,
            LayoutParams(MATCH, WRAP, Gravity.CENTER).apply {
                marginStart = dp(72)
                marginEnd = dp(72)
            },
        )
    }

    fun render(state: UpdatePresentation) {
        if (!state.blocksKiosk) {
            hide()
            return
        }

        val detailText = when (state.message) {
            UpdateMessage.CHECKING -> context.getString(R.string.update_checking)
            UpdateMessage.DOWNLOADING -> context.getString(
                R.string.update_downloading,
                state.versionName.orEmpty(),
                state.progress ?: 0,
            )
            UpdateMessage.AWAITING_USER_ACTION ->
                context.getString(R.string.update_awaiting_user_action)
            UpdateMessage.INSTALLING -> context.getString(R.string.update_installing)
            UpdateMessage.FAILURE,
            null,
            -> context.getString(R.string.update_failed_safe)
        }
        detail.text = detailText
        contentDescription = detailText
        progressBar.isIndeterminate = state.message != UpdateMessage.DOWNLOADING
        progressBar.progress = state.progress ?: 0
        visibility = View.VISIBLE
        bringToFront()
    }

    fun hide() {
        visibility = View.GONE
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        private val MATCH = ViewGroup.LayoutParams.MATCH_PARENT
        private val WRAP = ViewGroup.LayoutParams.WRAP_CONTENT
    }
}
