# Expo Kiosk Automatic Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fail-open, same-origin Android self-update channel that silently updates fully managed exhibition tablets and opens Android's confirmation flow on ordinary tablets.

**Architecture:** Pure Kotlin parser, policy, and engine components own deterministic decisions and receive JVM tests. Android adapters handle pinned downloads, APK inspection, and `PackageInstaller`; `MainActivity` only renders state and releases its existing WebView on no-update/failure. A PowerShell publisher uploads a signed APK first and atomically publishes its manifest last.

**Tech Stack:** Kotlin 1.9.24, Android SDK 35/minSdk 26, `PackageInstaller`, JUnit 4, `org.json`, PowerShell, Nginx.

---

## File map

Create:

- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateModel.kt`: manifest, APK identity, states, adapter interfaces.
- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateManifestParser.kt`: strict JSON parsing.
- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdatePolicy.kt`: fixed URLs and validation.
- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateEngine.kt`: fail-open orchestration.
- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/AndroidUpdateRuntime.kt`: network, cache, archive, installer adapters.
- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateInstallReceiver.kt`: installer callbacks.
- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/PackageReplacedReceiver.kt`: relaunch after replacement.
- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateOverlay.kt`: blocking native progress layer.
- `tablet-kiosk/app/src/test/java/com/leshine/expokiosk/UpdateManifestParserTest.kt`.
- `tablet-kiosk/app/src/test/java/com/leshine/expokiosk/UpdatePolicyTest.kt`.
- `tablet-kiosk/app/src/test/java/com/leshine/expokiosk/UpdateEngineTest.kt`.
- `tablet-kiosk/keystore.properties.example`.
- `tablet-kiosk/scripts/publish-update.ps1`.
- `deploy/nginx/expo-kiosk-updates.conf`.

Modify:

- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/KioskUrl.kt`.
- `tablet-kiosk/app/src/main/java/com/leshine/expokiosk/MainActivity.kt`.
- `tablet-kiosk/app/src/main/AndroidManifest.xml`.
- `tablet-kiosk/app/src/main/res/values/strings.xml`.
- `tablet-kiosk/app/build.gradle`.
- `.gitignore`.
- `tablet-kiosk/README.md`.
- `docs/runbook.md`.

## Task 1: Strict manifest and update policy

**Files:**
- Create the two parser/policy tests and three production files listed above.
- Modify `tablet-kiosk/app/build.gradle`.

- [ ] **Step 1: Add JSON test support and write the failing parser test**

Add `testImplementation 'org.json:json:20240303'`. The test must compile against this desired API:

```kotlin
@Test fun `parses exact release manifest`() {
    val raw = """{"version_code":10,"version_name":"1.9","apk_size":4,"sha256":"${"a".repeat(64)}"}"""
    assertEquals(UpdateManifest(10, "1.9", 4, "a".repeat(64)), UpdateManifestParser.parse(raw).getOrThrow())
}

@Test fun `rejects missing extra and malformed fields`() {
    val invalid = listOf(
        "{}",
        """{"version_code":0,"version_name":"1.9","apk_size":4,"sha256":"${"a".repeat(64)}"}""",
        """{"version_code":10,"version_name":"","apk_size":4,"sha256":"${"a".repeat(64)}"}""",
        """{"version_code":10,"version_name":"1.9","apk_size":0,"sha256":"${"a".repeat(64)}"}""",
        """{"version_code":10,"version_name":"1.9","apk_size":4,"sha256":"xyz"}""",
        """{"version_code":10,"version_name":"1.9","apk_size":4,"sha256":"${"a".repeat(64)}","apk_url":"https://evil.invalid/x.apk"}""",
    )
    invalid.forEach { assertTrue(UpdateManifestParser.parse(it).isFailure) }
}
```

- [ ] **Step 2: Run RED**

Run `gradle testDebugUnitTest --tests "com.leshine.expokiosk.UpdateManifestParserTest"`.

Expected: unresolved `UpdateManifest` and `UpdateManifestParser`.

- [ ] **Step 3: Implement the minimal strict parser**

```kotlin
data class UpdateManifest(val versionCode: Long, val versionName: String, val apkSize: Long, val sha256: String)

object UpdateManifestParser {
    private val keys = setOf("version_code", "version_name", "apk_size", "sha256")
    private val digest = Regex("^[0-9a-f]{64}$")
    fun parse(raw: String): Result<UpdateManifest> = runCatching {
        val json = JSONObject(raw)
        require(json.keys().asSequence().toSet() == keys)
        UpdateManifest(
            json.getLong("version_code").also { require(it > 0) },
            json.getString("version_name").trim().also { require(it.isNotEmpty()) },
            json.getLong("apk_size").also { require(it in 1..UpdatePolicy.MAX_APK_BYTES) },
            json.getString("sha256").also { require(digest.matches(it)) },
        )
    }
}
```

- [ ] **Step 4: Run GREEN, then write failing policy tests**

Required cases:

```kotlin
assertEquals("https://154.8.205.162/expo-app/latest.json", UpdatePolicy.manifestUrl("https://154.8.205.162/expo/kiosk"))
assertEquals("https://154.8.205.162/expo-app/leshine-expo-kiosk.apk", UpdatePolicy.apkUrl("https://154.8.205.162/expo/kiosk"))
assertEquals(DownloadedApkDecision.Accept, UpdatePolicy.validateDownloaded(manifest, current, candidate, 4, "a".repeat(64)))
```

Also assert rejection of invalid URL, non-newer version, mismatched manifest/candidate version and version name, wrong package, wrong signer, wrong byte count, wrong digest, and files over 100 MiB.

- [ ] **Step 5: Run policy RED, then implement the policy**

```kotlin
data class ApkIdentity(val packageName: String, val versionCode: Long, val versionName: String, val signers: Set<String>)
sealed interface DownloadedApkDecision {
    data object Accept : DownloadedApkDecision
    data class Reject(val reason: String) : DownloadedApkDecision
}
object UpdatePolicy {
    const val MAX_APK_BYTES = 100L * 1024 * 1024
    fun manifestUrl(kioskUrl: String) = fixedUrl(kioskUrl, "/expo-app/latest.json")
    fun apkUrl(kioskUrl: String) = fixedUrl(kioskUrl, "/expo-app/leshine-expo-kiosk.apk")
    fun shouldUpdate(current: Long, manifest: UpdateManifest) = manifest.versionCode > current
    fun validateDownloaded(manifest: UpdateManifest, current: ApkIdentity, candidate: ApkIdentity, size: Long, sha256: String): DownloadedApkDecision
}
```

`fixedUrl` uses `URI`, accepts only HTTP(S) with a host, preserves explicit ports, discards the kiosk path/query/fragment, and appends only the compile-time fixed path. `validateDownloaded` implements every equality/rejection asserted above with no fallback.

- [ ] **Step 6: Run parser and policy GREEN and commit**

```powershell
git add tablet-kiosk/app/build.gradle tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateModel.kt tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateManifestParser.kt tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdatePolicy.kt tablet-kiosk/app/src/test/java/com/leshine/expokiosk/UpdateManifestParserTest.kt tablet-kiosk/app/src/test/java/com/leshine/expokiosk/UpdatePolicyTest.kt
git commit -m "feat(kiosk): define secure update contract"
```

## Task 2: Fail-open engine and one-attempt invariant

**Files:**
- Create `UpdateEngine.kt` and `UpdateEngineTest.kt`.
- Modify `UpdateModel.kt`.

- [ ] **Step 1: Write failing engine tests with in-memory fakes**

Define the desired interfaces and states in the test:

```kotlin
interface UpdateSource {
    fun fetchManifest(): UpdateManifest
    fun download(manifest: UpdateManifest, onProgress: (Int) -> Unit): DownloadedArtifact
}
interface UpdateVerifier { fun verify(manifest: UpdateManifest, artifact: DownloadedArtifact): DownloadedApkDecision }
interface UpdateInstaller { fun install(artifact: DownloadedArtifact) }
data class DownloadedArtifact(val file: File, val size: Long, val sha256: String)
sealed interface UpdateState {
    data object Checking : UpdateState
    data class Downloading(val versionName: String, val progress: Int) : UpdateState
    data object AwaitingUserAction : UpdateState
    data object Installing : UpdateState
    data object NoUpdate : UpdateState
    data class Failed(val message: String) : UpdateState
}
```

Test exact flows: no newer version emits `Checking, NoUpdate` with zero downloads; valid newer version emits checking/progress/installing; manifest/download/verifier/installer exceptions each end in `Failed`; rejected/failed artifacts are deleted; a second `run` on one engine performs no I/O.

- [ ] **Step 2: Run RED and implement the synchronous engine**

```kotlin
class UpdateEngine(
    private val currentVersionCode: Long,
    private val source: UpdateSource,
    private val verifier: UpdateVerifier,
    private val installer: UpdateInstaller,
) {
    private val attempted = AtomicBoolean(false)
    fun run(onState: (UpdateState) -> Unit) {
        if (!attempted.compareAndSet(false, true)) return
        onState(UpdateState.Checking)
        var artifact: DownloadedArtifact? = null
        try {
            val manifest = source.fetchManifest()
            if (!UpdatePolicy.shouldUpdate(currentVersionCode, manifest)) { onState(UpdateState.NoUpdate); return }
            artifact = source.download(manifest) { onState(UpdateState.Downloading(manifest.versionName, it.coerceIn(0, 100))) }
            when (val decision = verifier.verify(manifest, artifact)) {
                DownloadedApkDecision.Accept -> { installer.install(artifact); onState(UpdateState.Installing) }
                is DownloadedApkDecision.Reject -> error(decision.reason)
            }
        } catch (error: Exception) {
            artifact?.file?.delete()
            onState(UpdateState.Failed(error.message ?: "升级失败"))
        }
    }
}
```

- [ ] **Step 3: Run GREEN and commit**

```powershell
git add tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateModel.kt tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateEngine.kt tablet-kiosk/app/src/test/java/com/leshine/expokiosk/UpdateEngineTest.kt
git commit -m "feat(kiosk): add fail-open update engine"
```

## Task 3: Android adapters and installer callbacks

**Files:**
- Create `AndroidUpdateRuntime.kt`, `UpdateInstallReceiver.kt`, `PackageReplacedReceiver.kt`.
- Modify `AndroidManifest.xml` and `UpdatePolicyTest.kt`.

- [ ] **Step 1: Add failing redirect and signer-normalization tests**

Test that every 3xx is rejected rather than followed and all signer fingerprints are normalized lowercase hex. Run once and confirm failure is due to missing adapter behavior.

- [ ] **Step 2: Implement pinned manifest/APK I/O**

`HttpUpdateSource` builds URLs only through `UpdatePolicy`, sets 3s/5s manifest and 5s/60s APK timeouts, sets `instanceFollowRedirects=false`, applies `PinnedTls`, requires HTTP 200, streams to `cacheDir/kiosk-update.apk.part` in 32 KiB chunks, stops above 100 MiB, updates SHA-256/progress, fsyncs, and closes/disconnects in `finally`.

- [ ] **Step 3: Implement archive validation**

`AndroidApkVerifier` reads the current and archive identities. API 28+ uses `GET_SIGNING_CERTIFICATES`/`apkContentsSigners`; API 26–27 uses `GET_SIGNATURES`. It hashes signer DER through `PinnedTls.sha256Hex` and delegates the final decision to `UpdatePolicy.validateDownloaded`.

- [ ] **Step 4: Implement installer submission**

`AndroidUpdateInstaller` creates `MODE_FULL_INSTALL`, sets package name, size, and install reason, writes `base.apk`, calls `session.fsync`, then commits to an explicit immutable/update-current broadcast `PendingIntent`. API 31+ sets `USER_ACTION_NOT_REQUIRED` only for `DevicePolicyManager.isDeviceOwnerApp(packageName)`; ordinary mode leaves user action unspecified. Once the session owns its copy, delete the private-cache `.part` file whether commit succeeds or throws.

- [ ] **Step 5: Implement receivers and manifest entries**

```xml
<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />
<receiver android:name=".UpdateInstallReceiver" android:exported="false" />
<receiver android:name=".PackageReplacedReceiver" android:exported="false">
  <intent-filter><action android:name="android.intent.action.MY_PACKAGE_REPLACED" /></intent-filter>
</receiver>
```

`UpdateInstallReceiver` sends an app-scoped `ACTION_UPDATE_AWAITING_USER` event and opens only Android's `Intent.EXTRA_INTENT` for `STATUS_PENDING_USER_ACTION`, ignores success, and launches `MainActivity.updateFailedIntent` for every failure status. `MainActivity` registers a non-exported receiver for that one app-scoped event while alive and renders `AwaitingUserAction`. `PackageReplacedReceiver` accepts only `ACTION_MY_PACKAGE_REPLACED` and launches `MainActivity` with `NEW_TASK | CLEAR_TOP`.

- [ ] **Step 6: Run update tests plus `assembleDebug`, inspect merged manifest, commit**

```powershell
git add tablet-kiosk/app/src/main/AndroidManifest.xml tablet-kiosk/app/src/main/java/com/leshine/expokiosk/AndroidUpdateRuntime.kt tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateInstallReceiver.kt tablet-kiosk/app/src/main/java/com/leshine/expokiosk/PackageReplacedReceiver.kt tablet-kiosk/app/src/test/java/com/leshine/expokiosk/UpdatePolicyTest.kt
git commit -m "feat(kiosk): download and install verified updates"
```

## Task 4: Startup overlay and MainActivity integration

**Files:**
- Create `UpdateOverlay.kt`.
- Modify `KioskUrl.kt`, `MainActivity.kt`, `strings.xml`, and `UpdateEngineTest.kt`.

- [ ] **Step 1: Write a failing presentation test**

Add `UpdateState.presentation()` and assert that checking/downloading/installing block kiosk while no-update/failure release it:

```kotlin
data class UpdatePresentation(val blocksKiosk: Boolean, val title: String, val progress: Int?)

@Test fun `only active update states block kiosk`() {
    assertTrue(UpdateState.Checking.presentation().blocksKiosk)
    assertTrue(UpdateState.Downloading("1.9", 50).presentation().blocksKiosk)
    assertTrue(UpdateState.AwaitingUserAction.presentation().blocksKiosk)
    assertTrue(UpdateState.Installing.presentation().blocksKiosk)
    assertFalse(UpdateState.NoUpdate.presentation().blocksKiosk)
    assertFalse(UpdateState.Failed("offline").presentation().blocksKiosk)
}
```

- [ ] **Step 2: Run RED, implement presentation and native overlay, run GREEN**

`UpdateOverlay` is a programmatic black `FrameLayout` with gold title, muted detail, and horizontal progress bar. Its entire public API is:

```kotlin
class UpdateOverlay(context: Context) : FrameLayout(context) {
    fun render(state: UpdateState)
    fun hide()
}
```

It contains no cancel button, URL input, WebView, or arbitrary Intent.

- [ ] **Step 3: Expose current origin without a second setting**

Add `fun origin(ctx: Context): String` to `KioskUrl`. `get(ctx)` becomes `origin(ctx) + KIOSK_PATH`; the origin still comes only from the existing normalized SharedPreferences/default URL.

- [ ] **Step 4: Integrate exactly one cold-start check**

Add the overlay above `errorView`, start the current kiosk WebView underneath it, and run `UpdateEngine` on the existing single-thread executor:

```kotlin
private fun startUpdateCheck(intent: Intent) {
    if (intent.action == ACTION_UPDATE_FAILED) { releaseUpdate(intent.getStringExtra(EXTRA_UPDATE_ERROR)); return }
    val engine = AndroidUpdateRuntime.createEngine(this, KioskUrl.get(this))
    io.execute { engine.run { state -> runOnUiThread { renderUpdateState(state) } } }
}

private fun renderUpdateState(state: UpdateState) {
    updateOverlay.render(state)
    when (state) {
        UpdateState.NoUpdate -> updateOverlay.hide()
        is UpdateState.Failed -> releaseUpdate(state.message)
        else -> Unit
    }
}
```

Override `onNewIntent` so `ACTION_UPDATE_FAILED` releases the overlay and never starts a second download. Do not check from `onResume`; returning from camera, printer, settings, or installer is not a cold start.

- [ ] **Step 5: Preserve kiosk and Lock Task boundaries**

Pending user action updates the overlay through the app-scoped event, then opens only the package install confirmation returned by `PackageInstaller`. Register/unregister the receiver with the Activity lifecycle and `RECEIVER_NOT_EXPORTED`. Do not whitelist Settings, browsers, file managers, or arbitrary packages. Existing `KioskNavigationPolicy` remains unchanged and all its tests must stay green.

- [ ] **Step 6: Run Android tests/build and commit**

```powershell
gradle testDebugUnitTest assembleDebug
git add tablet-kiosk/app/src/main/java/com/leshine/expokiosk/MainActivity.kt tablet-kiosk/app/src/main/java/com/leshine/expokiosk/KioskUrl.kt tablet-kiosk/app/src/main/java/com/leshine/expokiosk/UpdateOverlay.kt tablet-kiosk/app/src/main/res/values/strings.xml tablet-kiosk/app/src/test/java/com/leshine/expokiosk/UpdateEngineTest.kt
git commit -m "feat(kiosk): gate startup on automatic updates"
```

## Task 5: Stable signing, atomic publisher, and operations

**Files:**
- Modify `tablet-kiosk/app/build.gradle`, `.gitignore`, `tablet-kiosk/README.md`, `docs/runbook.md`.
- Create `keystore.properties.example`, `scripts/publish-update.ps1`, `deploy/nginx/expo-kiosk-updates.conf`.

- [ ] **Step 1: Capture the current release-signing failure test**

Run `gradle assembleRelease` without signing properties. Record that it currently creates an unsigned artifact. After implementation the exact same command must fail with an instruction to copy `keystore.properties.example`; `assembleDebug` must still pass.

- [ ] **Step 2: Configure version 1.9/code 10 and fail-closed release signing**

The untracked local file has exactly these keys:

```properties
storeFile=C:/secure/leshine-expo-release.jks
storePassword=replace-locally
keyAlias=leshine-expo
keyPassword=replace-locally
```

When a requested Gradle task name contains `Release`, throw `GradleException` if the file or any key is missing. Configure `signingConfigs.release` from those values. Add:

```gitignore
/tablet-kiosk/keystore.properties
/tablet-kiosk/*.jks
/tablet-kiosk/*.keystore
```

- [ ] **Step 3: Implement publisher prepare-only mode**

The script signature is fixed:

```powershell
param(
  [Parameter(Mandatory=$true)][string]$ApkPath,
  [switch]$PrepareOnly,
  [string]$Target = 'ubuntu@154.8.205.162',
  [string]$CaCertificatePath
)
```

It locates the newest Android SDK build-tools; runs `aapt dump badging` and `apksigner verify --print-certs`; requires `com.leshine.expokiosk`, version code greater than 9, valid signature, and a signer different from the standard Android debug certificate; computes size/SHA-256; and writes an exact four-field `latest.json` into a temporary directory. `-PrepareOnly` prints the directory and executes no `ssh`, `scp`, or `curl`.

- [ ] **Step 4: Prove publisher rejection and acceptance**

Run against `app-debug.apk`; expected non-zero exit with “debug-signed APK cannot be published.” Run against signed 1.9 release; expected JSON version 10/name 1.9 with exact bytes and lowercase digest.

- [ ] **Step 5: Implement atomic remote publication**

Without `-PrepareOnly`, fetch the current online manifest through `curl.exe --cacert $CaCertificatePath` and require the new versionCode to be strictly greater than the published version. Then upload `.apk.tmp` and `.json.tmp`, and run one quoted SSH command that creates `/var/www/ark-updates/expo-kiosk`, compares the remote APK digest, moves APK temp to `leshine-expo-kiosk.apk`, and moves manifest temp to `latest.json` last. The script must reject a missing CA certificate and must never use `-k`/`--insecure`.

- [ ] **Step 6: Add Nginx and operational documentation**

The Nginx snippet serves only `/var/www/ark-updates/expo-kiosk/`, disables autoindex, returns 404 for missing files, and sends `Cache-Control: no-store`. README/runbook commands must cover `nginx -t` before reload, release build, prepare-only validation, publication, first reinstall, device-owner removal/re-enrollment, and rollback by publishing a newer versionCode built from the previous source (Android downgrade remains forbidden).

- [ ] **Step 7: Verify and commit**

Run debug build, missing-signing release failure, signed release build, both publisher checks, and `git check-ignore tablet-kiosk/keystore.properties`.

```powershell
git add .gitignore tablet-kiosk/app/build.gradle tablet-kiosk/keystore.properties.example tablet-kiosk/scripts/publish-update.ps1 deploy/nginx/expo-kiosk-updates.conf tablet-kiosk/README.md docs/runbook.md
git commit -m "feat(kiosk): publish signed automatic updates"
```

## Task 6: Final regression and adversarial review

**Files:** Modify only files directly required by findings.

- [ ] **Step 1: Run focused Android tests**

```powershell
gradle testDebugUnitTest --tests "com.leshine.expokiosk.UpdateManifestParserTest" --tests "com.leshine.expokiosk.UpdatePolicyTest" --tests "com.leshine.expokiosk.UpdateEngineTest" --tests "com.leshine.expokiosk.KioskNavigationPolicyTest"
```

Expected: all pass.

- [ ] **Step 2: Run complete project verification for the touched surfaces**

```powershell
gradle testDebugUnitTest assembleDebug
npm run test:expo-kiosk
npm run build
python scripts/check_conventions.py --base main
```

Expected: Android success, 24+ kiosk regression passes, Vite production build success, no incremental convention violation.

- [ ] **Step 3: Inspect generated APK and manifest**

Use `aapt dump badging`, `apksigner verify --print-certs`, and merged-manifest inspection to record package, version, signer SHA-256, install permission, and both non-exported receivers. Compute final APK SHA-256.

- [ ] **Step 4: Dispatch independent adversarial review**

Review boundaries, interrupted downloads, one-attempt idempotency, manifest/APK race, redirect/origin enforcement, signing/downgrade checks, both installer modes, Lock Task interaction, and whether any update intent can open Ark backend or an arbitrary external page. Every P0–P2 finding receives a failing test before its fix.

- [ ] **Step 5: Sweep and final status**

```powershell
python scripts/git_sweep.py
git diff --check main
git status --short
git log --oneline main..HEAD
```

Expected: this worktree is clean; unrelated repository debts remain untouched.

- [ ] **Step 6: Keep hardware acceptance as a release gate**

Do not claim rollout complete until hardware proves device-owner silent update, ordinary-mode system confirmation, and fail-open behavior for offline/404/corrupt/wrong signer/wrong package/lower version cases. Do not upload to cloud, install devices, merge main, or push main without the user's deployment instruction.
