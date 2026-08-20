# PDA Unit Continuous Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make unit-only domestic reporting automatically submit one piece and reuse one readable result dialog for continuous physical-button scans.

**Architecture:** Keep `MainActivity` as the network/idempotency coordinator, extract the unit-mode decision and result states into a small pure Kotlin model, and render those states through a dedicated `UnitReportDialog`. `ReportingScreen` remains the page façade and quantity-mode confirmation stays unchanged.

**Tech Stack:** Android SDK 23+, Kotlin, `AlertDialog`, `Handler`, `JSONObject`, JUnit 4, Gradle Android plugin.

---

## File Structure

- Create `pda-reporting/app/src/main/java/com/leshine/pdareporting/UnitReportFlow.kt`: pure unit-mode policy and submitting/success/error presentation states.
- Create `pda-reporting/app/src/test/java/com/leshine/pdareporting/UnitReportFlowTest.kt`: verifies fixed auto-submit policy, close/scan gates, and 3-second success visibility.
- Create `pda-reporting/app/src/main/java/com/leshine/pdareporting/UnitReportDialog.kt`: owns one reusable dialog, key-information rendering, full-width close button, and result-banner timer.
- Modify `pda-reporting/app/src/main/java/com/leshine/pdareporting/ReportingScreen.kt`: expose unit-dialog operations while retaining quantity confirmation.
- Modify `pda-reporting/app/src/main/java/com/leshine/pdareporting/MainActivity.kt`: route every unit-mode scan directly to submit, keep the dialog open, and route explicit failures to it.
- Modify `pda-reporting/app/build.gradle`: bump the APK to version `1.0.3` / code `4`.
- Modify `pda-reporting/README.md`: document fixed unit auto-submit and continuous scan behavior; remove the obsolete setting description.

### Task 1: Define the unit reporting state contract

**Files:**
- Create: `pda-reporting/app/src/test/java/com/leshine/pdareporting/UnitReportFlowTest.kt`
- Create: `pda-reporting/app/src/main/java/com/leshine/pdareporting/UnitReportFlow.kt`

- [ ] **Step 1: Write the failing policy and state tests**

```kotlin
class UnitReportFlowTest {
    @Test fun unit_mode_always_auto_submits() {
        assertTrue(UnitReportFlow.shouldAutoSubmit("unit"))
        assertFalse(UnitReportFlow.shouldAutoSubmit("quantity"))
    }

    @Test fun submitting_blocks_close_and_next_scan() {
        val state = UnitReportFlow.submitting()
        assertFalse(state.closeEnabled)
        assertFalse(state.nextScanEnabled)
    }

    @Test fun success_allows_close_and_next_scan_for_three_seconds() {
        val state = UnitReportFlow.success("工序 · 1 件")
        assertTrue(state.closeEnabled)
        assertTrue(state.nextScanEnabled)
        assertEquals(3_000L, state.autoHideAfterMs)
    }

    @Test fun explicit_error_allows_rescan_without_auto_hiding() {
        val state = UnitReportFlow.error("操作失败：当前不能报工")
        assertTrue(state.closeEnabled)
        assertTrue(state.nextScanEnabled)
        assertNull(state.autoHideAfterMs)
    }
}
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd pda-reporting && .\gradlew.bat testDebugUnitTest --tests com.leshine.pdareporting.UnitReportFlowTest`

Expected: compilation fails because `UnitReportFlow` does not exist.

- [ ] **Step 3: Implement the minimal pure Kotlin contract**

```kotlin
enum class UnitReportTone { PROGRESS, SUCCESS, ERROR }

data class UnitReportPresentation(
    val tone: UnitReportTone,
    val message: String,
    val closeEnabled: Boolean,
    val nextScanEnabled: Boolean,
    val autoHideAfterMs: Long? = null,
)

object UnitReportFlow {
    const val SUCCESS_VISIBLE_MS = 3_000L

    fun shouldAutoSubmit(reportMode: String) = reportMode == "unit"

    fun submitting() = UnitReportPresentation(
        UnitReportTone.PROGRESS, "正在报工…", closeEnabled = false, nextScanEnabled = false,
    )

    fun success(detail: String) = UnitReportPresentation(
        UnitReportTone.SUCCESS, "✓ 报工成功\n$detail", closeEnabled = true,
        nextScanEnabled = true, autoHideAfterMs = SUCCESS_VISIBLE_MS,
    )

    fun error(message: String) = UnitReportPresentation(
        UnitReportTone.ERROR, message, closeEnabled = true, nextScanEnabled = true,
    )
}
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `cd pda-reporting && .\gradlew.bat testDebugUnitTest --tests com.leshine.pdareporting.UnitReportFlowTest`

Expected: all four tests pass.

- [ ] **Step 5: Commit the state contract**

```bash
git add pda-reporting/app/src/main/java/com/leshine/pdareporting/UnitReportFlow.kt pda-reporting/app/src/test/java/com/leshine/pdareporting/UnitReportFlowTest.kt
git commit -m "test(pda): define continuous unit report states"
```

### Task 2: Build the reusable unit result dialog

**Files:**
- Create: `pda-reporting/app/src/main/java/com/leshine/pdareporting/UnitReportDialog.kt`
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/ReportingScreen.kt`

- [ ] **Step 1: Add a renderer that owns one dialog instance**

Create `UnitReportDialog` with these exact public operations:

```kotlin
class UnitReportDialog(
    private val context: Context,
    private val loadImage: (String, ImageView) -> Unit,
    private val onClosed: () -> Unit,
) {
    fun show(scan: JSONObject, presentation: UnitReportPresentation)
    fun render(presentation: UnitReportPresentation): Boolean
    fun isShowing(): Boolean
    fun dispose()
}
```

`show` must create the `AlertDialog` only when none is showing, otherwise clear and rebuild the existing details container. Render the five primary rows using bold `15sp` labels and bold `19sp` values: 产品、客户、订单、单件编号、当前工序. Put a custom `关闭` button below the scroll area using `MATCH_PARENT` width and `56dp` height. It is the only action button.

The banner rendering must follow the state model exactly:

```kotlin
when (presentation.tone) {
    UnitReportTone.PROGRESS -> showBanner("正在报工…", Ui.warning, progressBackground)
    UnitReportTone.SUCCESS -> showBanner(presentation.message, Color.WHITE, Ui.green)
    UnitReportTone.ERROR -> showBanner(presentation.message, Ui.danger, errorBackground)
}
closeButton.isEnabled = presentation.closeEnabled
presentation.autoHideAfterMs?.let { handler.postDelayed(hideBanner, it) }
```

Cancel the previous timer before every render and in `dispose`. Do not animate banner entry or exit. Set the dialog non-cancelable while submitting and cancelable after an explicit result.

- [ ] **Step 2: Make `ReportingScreen` the dialog façade**

Add these operations and keep `showQuantityConfirmation` quantity-only:

```kotlin
fun showUnitReport(scan: JSONObject, loadImage: (String, ImageView) -> Unit) {
    val renderer = unitReportDialog ?: UnitReportDialog(context, loadImage, ::showReady)
        .also { unitReportDialog = it }
    renderer.show(scan, UnitReportFlow.submitting())
}

fun showUnitSuccess(message: String) = unitReportDialog?.render(UnitReportFlow.success(message)) == true
fun showUnitError(message: String) = unitReportDialog?.render(UnitReportFlow.error(message)) == true
fun isUnitDialogShowing() = unitReportDialog?.isShowing() == true

override fun onDetachedFromWindow() {
    unitReportDialog?.dispose()
    unitReportDialog = null
    super.onDetachedFromWindow()
}
```

Remove unit-specific disabled quantity-input rendering from `showQuantityConfirmation`; this method will now only serve `report_mode=quantity`.

- [ ] **Step 3: Compile after the UI extraction**

Run: `cd pda-reporting && .\gradlew.bat compileDebugKotlin`

Expected: `BUILD SUCCESSFUL` with no unresolved Android or Kotlin symbols.

- [ ] **Step 4: Commit the reusable dialog**

```bash
git add pda-reporting/app/src/main/java/com/leshine/pdareporting/UnitReportDialog.kt pda-reporting/app/src/main/java/com/leshine/pdareporting/ReportingScreen.kt
git commit -m "feat(pda): add reusable unit report dialog"
```

### Task 3: Route unit scans through automatic continuous submission

**Files:**
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/MainActivity.kt`

- [ ] **Step 1: Make the unit decision independent of scan source**

Replace the old keyboard-and-preference branch with:

```kotlin
private fun handleScanResult(payload: ScanPayload, scan: JSONObject) {
    if (UnitReportFlow.shouldAutoSubmit(scan.optString("report_mode"))) {
        reportingScreen?.showUnitReport(scan, ::loadImage)
        submit(scan, payload, 1, UUID.randomUUID().toString())
        return
    }
    reportingScreen?.showQuantityConfirmation(
        scan = scan,
        onConfirm = { qty -> submit(scan, payload, qty, UUID.randomUUID().toString()) },
        onCancel = { busy = false; reportingScreen?.showReady() },
        loadImage = ::loadImage,
    )
}
```

Change the scan callback to call this signature. The `ScanSource` argument remains accepted at the raw-input boundary because scanner and manual-input callbacks share that contract, but it no longer changes unit business behavior.

- [ ] **Step 2: Keep the unit dialog alive through submit results**

In `submit`, compute `val unitMode = UnitReportFlow.shouldAutoSubmit(scan.optString("report_mode"))`. For unit mode, do not replace the dialog with the page-level submitting card. On success clear the pending record, set `busy=false`, call feedback, render `showUnitSuccess(message)`, and refresh history. For quantity mode preserve `showSubmitting` and `showSuccess`.

For explicit 4xx or local persistence failures, clear the pending record using existing rules, set `busy=false`, and call:

```kotlin
private fun showOperationFailure(error: Exception, written: Boolean, preferUnitDialog: Boolean) {
    if (error is ApiException && error.statusCode == 401) {
        sessionExpired()
        return
    }
    busy = false
    feedback.error()
    val prefix = if (written) "操作失败：" else "扫码失败："
    val message = prefix + readableError(error)
    if (!preferUnitDialog || reportingScreen?.showUnitError(message) != true) {
        reportingScreen?.showError(message)
    }
}
```

Transport, 5xx, and decode-unknown failures must continue using the existing non-cancelable idempotent retry dialog and keep `busy=true`.

- [ ] **Step 3: Route invalid next scans into an already-open unit dialog**

When raw parsing or the scan lookup fails and the unit dialog is already visible, use `showUnitError` so the result appears inside the dialog and `busy` is released. When no unit dialog is visible, retain the main page error card.

- [ ] **Step 4: Remove the obsolete auto-unit setting**

Delete the `Switch` import, `autoUnit` control, `KEY_AUTO_UNIT`, and `putBoolean(KEY_AUTO_UNIT, ...)`. Keep only server configuration and the physical-broadcast information in the settings dialog.

- [ ] **Step 5: Run all unit tests and compile**

Run: `cd pda-reporting && .\gradlew.bat testDebugUnitTest compileDebugKotlin`

Expected: all tests pass and Kotlin compilation succeeds.

- [ ] **Step 6: Commit the flow integration**

```bash
git add pda-reporting/app/src/main/java/com/leshine/pdareporting/MainActivity.kt
git commit -m "feat(pda): auto-submit continuous unit scans"
```

### Task 4: Version, document, and produce the APK

**Files:**
- Modify: `pda-reporting/app/build.gradle`
- Modify: `pda-reporting/README.md`

- [ ] **Step 1: Bump the application version**

```groovy
versionCode 4
versionName "1.0.3"
```

- [ ] **Step 2: Update operator documentation**

Document that `report_mode=unit` always auto-submits one piece, one result dialog supports repeated physical scans, the green success banner hides after three seconds, and quantity reporting still requires confirmation. Remove instructions for the deleted auto-unit switch.

- [ ] **Step 3: Run animation and design review**

Read `C:/Users/windb/.agents/skills/review-animations/STANDARDS.md` and verify that the high-frequency physical-button flow uses no movement or bounce animation, immediate feedback, no focus theft, and no timer surviving dialog disposal.

- [ ] **Step 4: Run the complete Android verification**

Run: `cd pda-reporting && .\gradlew.bat clean test lintDebug assembleDebug`

Expected: `BUILD SUCCESSFUL`; unit-test reports, lint results, and `app/build/outputs/apk/debug/app-debug.apk` are generated.

- [ ] **Step 5: Run repository conventions and inspect the packaged manifest**

Run: `python scripts/check_conventions.py --base $(git merge-base main HEAD)` and use Android build tools `aapt dump badging` plus `aapt dump xmltree` to verify package `com.leshine.pdareporting`, version `1.0.3`, and the vendor scan receiver/action.

Expected: no new convention violations; package/version/receiver match the design. Any unrelated pre-existing convention finding must be reported separately rather than hidden or edited.

- [ ] **Step 6: Name and hash the delivery artifact**

Copy the built APK to `pda-reporting/app/build/outputs/apk/debug/LeShine-PDA-v1.0.3-continuous-unit-report.apk`, verify it with `apksigner verify --verbose`, and calculate SHA-256 with `Get-FileHash`.

- [ ] **Step 7: Request the required adversarial review**

Because this feature changes more than three files and alters a reporting state machine, dispatch one independent read-only review covering scan concurrency, idempotent retry, dialog lifecycle, permission-mode separation, and Android 6 compatibility. Fix every blocking issue and rerun affected checks.

- [ ] **Step 8: Commit documentation and packaged version changes**

```bash
git add pda-reporting/app/build.gradle pda-reporting/README.md
git commit -m "chore(pda): release continuous unit reporting"
```

- [ ] **Step 9: Confirm branch and worktree state**

Run: `git branch --show-current` and `git status --short`.

Expected: branch is `codex/pda-physical-scan` and the worktree is clean. Push the feature branch as required by repository policy; do not merge or push `main`.
