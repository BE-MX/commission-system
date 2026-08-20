# PDA Physical Scan Broadcast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the foreground PDA reporting app receive the A4G vendor broadcast produced by the physical scan key, without any on-screen scan trigger.

**Architecture:** Route the A4G action through an exported manifest receiver for compatibility with old scanner services that resolve installed receivers, then hand events to the foreground `ScannerInput` through a process-local bridge. Keep other scanner protocols on the lifecycle-bound dynamic receiver with `CATEGORY_DEFAULT`, read only known extras safely, and route malformed broadcasts into an actionable UI error.

**Tech Stack:** Kotlin, Android SDK 23+, AndroidX Core, JUnit 4, Gradle 8.7

---

### Task 1: Manufacturer broadcast contract

**Files:**
- Create: `pda-reporting/app/src/main/java/com/leshine/pdareporting/ScanBroadcastContract.kt`
- Create: `pda-reporting/app/src/test/java/com/leshine/pdareporting/ScanBroadcastContractTest.kt`

- [x] **Step 1: Write the failing contract tests**

Create tests that require the exact manufacturer action, no required category, priority for `barcode_string`, UTF-8 byte-array decoding, trimming, and rejection of empty payloads:

```kotlin
class ScanBroadcastContractTest {
    @Test fun usesA4gActionWithoutCategory() {
        assertFalse(ScanBroadcastContract.dynamicActions.contains(ScanBroadcastContract.VENDOR_ACTION))
        assertTrue(ScanBroadcastContract.requiredCategories.contains("android.intent.category.DEFAULT"))
    }

    @Test fun readsVendorBarcodeStringFirst() {
        assertEquals("ARK-D:1:abcdef12", ScanBroadcastContract.extract(mapOf(
            "data" to "wrong",
            "barcode_string" to "  ARK-D:1:abcdef12  ",
        )))
    }

    @Test fun decodesVendorByteArrayAndRejectsEmptyPayload() {
        assertEquals("ARK-DU:2:abcdef12", ScanBroadcastContract.extract(mapOf(
            "barcode_string" to "ARK-DU:2:abcdef12\u0000".toByteArray(),
        )))
        assertNull(ScanBroadcastContract.extract(mapOf("barcode_string" to "  ")))
    }
}
```

- [x] **Step 2: Run the focused test and verify RED**

Run:

```powershell
$env:ANDROID_HOME='C:\Users\windb\AppData\Local\Android\Sdk'
& "$env:USERPROFILE\.gradle\wrapper\dists\gradle-8.7-bin\f06yd7m8w1d0inql2joytq4az\gradle-8.7\bin\gradle.bat" -p pda-reporting testDebugUnitTest --tests '*ScanBroadcastContractTest' --console=plain
```

Expected: compilation fails because `ScanBroadcastContract` and `ScanBroadcastBridge` do not exist.

- [x] **Step 3: Implement the pure contract**

Create an internal object with `VENDOR_ACTION`, `VENDOR_EXTRA`, non-vendor `dynamicActions`, `CATEGORY_DEFAULT` in `requiredCategories`, and safe extractors for maps and Android Bundles. Normalize `String`, `CharSequence`, and UTF-8 `ByteArray`; trim whitespace and trailing NUL bytes; read only known keys and catch Bundle access failures. Add a process-local bridge whose listener is attached only while the report page is active.

- [x] **Step 4: Run the focused test and verify GREEN**

Run the Step 2 command again. Expected: all `ScanBroadcastContractTest` methods pass.

### Task 2: Foreground receiver and user feedback

**Files:**
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/ScannerInput.kt`
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/MainActivity.kt`
- Modify: `pda-reporting/app/src/main/java/com/leshine/pdareporting/ReportingScreen.kt`
- Modify: `pda-reporting/app/src/main/AndroidManifest.xml`
- Create: `pda-reporting/app/src/main/java/com/leshine/pdareporting/ScanBroadcastBridge.kt`
- Create: `pda-reporting/app/src/main/java/com/leshine/pdareporting/VendorScanReceiver.kt`

- [x] **Step 1: Connect `ScannerInput` to the tested contract**

Add an exported manifest Receiver for `android.intent.ACTION_DECODE_DATA` with `CATEGORY_DEFAULT`. It safely extracts the payload and publishes it through `ScanBroadcastBridge`. Add an `onMalformedBroadcast: (String) -> Unit` callback to `ScannerInput`; attach the bridge listener in `start()`, detach it in `stop()`, and keep non-vendor dynamic actions registered with `CATEGORY_DEFAULT`.

- [x] **Step 2: Add actionable malformed-broadcast feedback**

Pass a callback from `MainActivity` that reports: `已收到 PDA 扫描广播，但 barcode_string 为空；请检查扫描设置中的广播数据标签`. Do not change backend calls or QR parsing.

- [x] **Step 3: Make the non-interactive UI explicit**

Change the status block text from `硬件扫描头输入` to `按 PDA 实体扫描键扫码`. Keep it as a plain `TextView` with no click listener and do not add any `sendBroadcast` or `F6_KEY_DOWN` call.

- [x] **Step 4: Run all PDA unit tests**

Run:

```powershell
$env:ANDROID_HOME='C:\Users\windb\AppData\Local\Android\Sdk'
& "$env:USERPROFILE\.gradle\wrapper\dists\gradle-8.7-bin\f06yd7m8w1d0inql2joytq4az\gradle-8.7\bin\gradle.bat" -p pda-reporting test --console=plain
```

Expected: `BUILD SUCCESSFUL` and both debug and release unit tests pass.

### Task 3: Version, build, and APK verification

**Files:**
- Modify: `pda-reporting/app/build.gradle`
- Modify: `pda-reporting/README.md`
- Generate: `pda-reporting/app/build/outputs/apk/debug/app-debug.apk`

- [x] **Step 1: Increment the installable version**

Set `versionCode 3` and `versionName "1.0.2"` so the PDA can distinguish this build from the previously delivered v1.0.1 APK. Update the README manufacturer section to document A4G physical-key broadcast output with action `android.intent.ACTION_DECODE_DATA` and extra `barcode_string`.

- [x] **Step 2: Run conventions and the complete build**

Run:

```powershell
python scripts/check_conventions.py
$env:ANDROID_HOME='C:\Users\windb\AppData\Local\Android\Sdk'
& "$env:USERPROFILE\.gradle\wrapper\dists\gradle-8.7-bin\f06yd7m8w1d0inql2joytq4az\gradle-8.7\bin\gradle.bat" -p pda-reporting clean test assembleDebug --console=plain
```

Expected: conventions have no red findings and Gradle prints `BUILD SUCCESSFUL`.

- [x] **Step 3: Verify the APK artifact**

Use Android SDK `aapt.exe` and `apksigner.bat` to prove package `com.leshine.pdareporting`, versionCode `3`, versionName `1.0.2`, minimum SDK 23, and valid v1/v2 signatures. Record file size and SHA-256.

- [x] **Step 4: Audit the diff and worktree**

Confirm every changed source line traces to physical-button broadcast reception, no `F6_KEY_DOWN` or screen scan click was added, and unrelated user changes remain untouched. Do not commit because this `main` worktree belongs to Claude Code under repository `AGENTS.md`.
