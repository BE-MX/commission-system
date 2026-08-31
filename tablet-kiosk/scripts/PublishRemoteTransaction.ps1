Set-StrictMode -Version Latest

function New-PublishRemoteScripts {
    param(
        [Parameter(Mandatory = $true)][string]$RemoteDirectory,
        [Parameter(Mandatory = $true)][string]$TransactionId,
        [Parameter(Mandatory = $true)][ValidateSet('existing', 'initialize')][string]$Mode,
        [Parameter(Mandatory = $true)][string]$RemoteApkUploadName,
        [Parameter(Mandatory = $true)][string]$RemoteManifestUploadName,
        [Parameter(Mandatory = $true)][string]$NewApkSha256,
        [Parameter(Mandatory = $true)][long]$NewApkSize,
        [Parameter(Mandatory = $true)][string]$NewManifestSha256,
        [Parameter(Mandatory = $true)][long]$NewManifestSize,
        [string]$BaselineApkSha256 = '',
        [long]$BaselineApkSize = 0,
        [string]$BaselineManifestSha256 = ''
    )

    $remoteSegments = $RemoteDirectory.Split('/', [System.StringSplitOptions]::RemoveEmptyEntries)
    if ($RemoteDirectory -cnotmatch '^/[A-Za-z0-9._/-]+$' -or
        $RemoteDirectory.EndsWith('/') -or $RemoteDirectory.Contains('//') -or
        $remoteSegments.Where({ $_ -in @('.', '..') }).Count -ne 0) {
        throw 'RemoteDirectory must be an absolute controlled Unix path.'
    }
    if ($TransactionId -cnotmatch '^[0-9a-f]{32}$') { throw 'TransactionId must be lowercase GUID hex.' }
    if ($RemoteApkUploadName -cne ".leshine-expo-$TransactionId.apk.upload" -or
        $RemoteManifestUploadName -cne ".leshine-expo-$TransactionId.json.upload") {
        throw 'Remote upload names must be derived only from TransactionId.'
    }
    foreach ($digest in @($NewApkSha256, $NewManifestSha256)) {
        if ($digest -cnotmatch '^[0-9a-f]{64}$') { throw 'New artifact digests must be lowercase SHA-256.' }
    }
    if ($NewApkSize -le 0 -or $NewManifestSize -le 0) { throw 'New artifact sizes must be positive.' }
    if ($Mode -eq 'existing') {
        if ($BaselineApkSha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $BaselineManifestSha256 -cnotmatch '^[0-9a-f]{64}$' -or $BaselineApkSize -le 0) {
            throw 'Existing-channel baseline identity is incomplete.'
        }
    } elseif ($BaselineApkSha256 -or $BaselineManifestSha256 -or $BaselineApkSize -ne 0) {
        throw 'Initialize mode must have an explicitly empty baseline.'
    }

    $begin = @"
set -eu
work_dir="$RemoteDirectory"
lock_dir="`$work_dir/.publish-lock"
receipt_dir="`$work_dir/.publish-receipts"
receipt_file="`$receipt_dir/$TransactionId.receipt"
receipt_tmp="`$receipt_dir/.$TransactionId.receipt.tmp"
owner="$TransactionId"
mode="$Mode"
created=0
cleanup_begin() {
  rc=`$?
  trap - EXIT
  set +e
  if [ "`$created" = 1 ]; then
    current_owner=`$(sudo cat "`$lock_dir/owner" 2>/dev/null || true)
    if [ -z "`$current_owner" ] || [ "`$current_owner" = "`$owner" ]; then
      sudo rm -f -- "`$lock_dir/owner" "`$lock_dir/mode" "`$lock_dir/state" "`$lock_dir/state.tmp" \
        "`$lock_dir/old-apk.sha256" "`$lock_dir/old-apk.size" "`$lock_dir/old-manifest.sha256"
      sudo rmdir "`$lock_dir" 2>/dev/null || true
    fi
  fi
  exit "`$rc"
}
trap cleanup_begin EXIT
sudo install -d -m 0755 "`$work_dir"
sudo install -d -m 0755 "`$receipt_dir"
test ! -e "`$receipt_file"
test ! -e "`$receipt_tmp"
if ! sudo mkdir "`$lock_dir"; then
  echo 'Another publisher transaction or an unresolved recovery lock exists.' >&2
  exit 73
fi
created=1
printf '%s\n' "`$owner" | sudo tee "`$lock_dir/owner" >/dev/null
printf '%s\n' "`$mode" | sudo tee "`$lock_dir/mode" >/dev/null
printf '%s\n' "$BaselineApkSha256" | sudo tee "`$lock_dir/old-apk.sha256" >/dev/null
printf '%s\n' "$BaselineApkSize" | sudo tee "`$lock_dir/old-apk.size" >/dev/null
printf '%s\n' "$BaselineManifestSha256" | sudo tee "`$lock_dir/old-manifest.sha256" >/dev/null
if [ "`$mode" = initialize ]; then
  test ! -e "`$work_dir/leshine-expo-kiosk.apk"
  test ! -e "`$work_dir/latest.json"
else
  test -f "`$work_dir/leshine-expo-kiosk.apk"
  test -f "`$work_dir/latest.json"
  test "`$(sudo sha256sum "`$work_dir/latest.json" | awk '{print `$1}')" = "$BaselineManifestSha256"
  test "`$(sudo sha256sum "`$work_dir/leshine-expo-kiosk.apk" | awk '{print `$1}')" = "$BaselineApkSha256"
  test "`$(sudo stat -c %s "`$work_dir/leshine-expo-kiosk.apk")" = "$BaselineApkSize"
fi
printf '%s\n' begun | sudo tee "`$lock_dir/state.tmp" >/dev/null
sudo mv -f -- "`$lock_dir/state.tmp" "`$lock_dir/state"
trap - EXIT
"@

    $transactionFunctions = @"
work_dir="$RemoteDirectory"
lock_dir="`$work_dir/.publish-lock"
receipt_dir="`$work_dir/.publish-receipts"
receipt_file="`$receipt_dir/$TransactionId.receipt"
receipt_tmp="`$receipt_dir/.$TransactionId.receipt.tmp"
owner="$TransactionId"
expected_mode="$Mode"
apk_upload="`$HOME/$RemoteApkUploadName"
manifest_upload="`$HOME/$RemoteManifestUploadName"
apk_stage="`$work_dir/.leshine-expo-kiosk.$TransactionId.apk.stage"
manifest_stage="`$work_dir/.latest.$TransactionId.json.stage"
restore_apk="`$work_dir/.leshine-expo-kiosk.$TransactionId.restore.apk"
restore_manifest="`$work_dir/.latest.$TransactionId.restore.json"
backup_apk="`$lock_dir/previous.apk"
backup_manifest="`$lock_dir/previous.json"
state_file="`$lock_dir/state"
write_state() {
  printf '%s\n' "`$1" | sudo tee "`$lock_dir/state.tmp" >/dev/null
  sudo mv -f -- "`$lock_dir/state.tmp" "`$state_file"
}
verify_new_official() {
  test "`$(sudo sha256sum "`$work_dir/leshine-expo-kiosk.apk" | awk '{print `$1}')" = "$NewApkSha256"
  test "`$(sudo stat -c %s "`$work_dir/leshine-expo-kiosk.apk")" = "$NewApkSize"
  test "`$(sudo sha256sum "`$work_dir/latest.json" | awk '{print `$1}')" = "$NewManifestSha256"
  test "`$(sudo stat -c %s "`$work_dir/latest.json")" = "$NewManifestSize"
}
verify_old_official() {
  test "`$(sudo sha256sum "`$work_dir/leshine-expo-kiosk.apk" | awk '{print `$1}')" = "$BaselineApkSha256"
  test "`$(sudo stat -c %s "`$work_dir/leshine-expo-kiosk.apk")" = "$BaselineApkSize"
  test "`$(sudo sha256sum "`$work_dir/latest.json" | awk '{print `$1}')" = "$BaselineManifestSha256"
}
verify_empty_official() {
  test ! -e "`$work_dir/leshine-expo-kiosk.apk"
  test ! -e "`$work_dir/latest.json"
}
verify_receipt_identity() {
  test -f "`$receipt_file"
  test "`$(sudo sed -n '1p' "`$receipt_file")" = "owner=`$owner"
  test "`$(sudo sed -n '2p' "`$receipt_file")" = "mode=`$expected_mode"
  test "`$(sudo sed -n '4p' "`$receipt_file")" = "new_apk_sha256=$NewApkSha256"
  test "`$(sudo sed -n '5p' "`$receipt_file")" = "new_apk_size=$NewApkSize"
  test "`$(sudo sed -n '6p' "`$receipt_file")" = "new_manifest_sha256=$NewManifestSha256"
  test "`$(sudo sed -n '7p' "`$receipt_file")" = "new_manifest_size=$NewManifestSize"
  test "`$(sudo sed -n '8p' "`$receipt_file")" = "old_apk_sha256=$BaselineApkSha256"
  test "`$(sudo sed -n '9p' "`$receipt_file")" = "old_apk_size=$BaselineApkSize"
  test "`$(sudo sed -n '10p' "`$receipt_file")" = "old_manifest_sha256=$BaselineManifestSha256"
  test "`$(sudo wc -l < "`$receipt_file" | tr -d ' ')" = 10
}
receipt_outcome() {
  sudo sed -n '3s/^outcome=//p' "`$receipt_file"
}
write_receipt() {
  outcome="`$1"
  test ! -e "`$receipt_file"
  sudo install -d -m 0755 "`$receipt_dir"
  printf '%s\n' \
    "owner=`$owner" "mode=`$expected_mode" "outcome=`$outcome" \
    "new_apk_sha256=$NewApkSha256" "new_apk_size=$NewApkSize" \
    "new_manifest_sha256=$NewManifestSha256" "new_manifest_size=$NewManifestSize" \
    "old_apk_sha256=$BaselineApkSha256" "old_apk_size=$BaselineApkSize" \
    "old_manifest_sha256=$BaselineManifestSha256" | sudo tee "`$receipt_tmp" >/dev/null
  sudo mv -f -- "`$receipt_tmp" "`$receipt_file"
  verify_receipt_identity
  test "`$(receipt_outcome)" = "`$outcome"
}
cleanup_owned_lock() {
  test -d "`$lock_dir"
  test "`$(sudo cat "`$lock_dir/owner")" = "`$owner"
  test "`$(sudo cat "`$lock_dir/mode")" = "`$expected_mode"
  rm -f -- "`$apk_upload" "`$manifest_upload"
  sudo rm -f -- "`$apk_stage" "`$manifest_stage" "`$restore_apk" "`$restore_manifest" \
    "`$backup_apk" "`$backup_manifest" "`$lock_dir/old-apk.sha256" "`$lock_dir/old-apk.size" \
    "`$lock_dir/old-manifest.sha256" "`$lock_dir/mode" "`$state_file" "`$lock_dir/state.tmp"
  sudo rm -f -- "`$lock_dir/owner"
  sudo rmdir "`$lock_dir"
}
cleanup_residual_lock_if_owned() {
  if [ -d "`$lock_dir" ]; then cleanup_owned_lock; fi
}
rollback_owned_transaction() {
  if [ -f "`$receipt_file" ]; then
    verify_receipt_identity
    outcome=`$(receipt_outcome)
    if [ "`$outcome" = rolled_back ]; then
      if [ "`$expected_mode" = existing ]; then verify_old_official; else verify_empty_official; fi
      cleanup_residual_lock_if_owned
      echo PUBLISH_TXN_ROLLED_BACK
      return 0
    fi
    if [ "`$outcome" = finalized ]; then
      verify_new_official
      cleanup_residual_lock_if_owned
      echo PUBLISH_TXN_FINALIZED
      return 0
    fi
    echo 'Unknown transaction receipt outcome; no files were changed.' >&2
    return 77
  fi
  test -d "`$lock_dir"
  test "`$(sudo cat "`$lock_dir/owner")" = "`$owner"
  mode=`$(sudo cat "`$lock_dir/mode")
  test "`$mode" = "`$expected_mode"
  state=`$(sudo cat "`$state_file")
  if [ "`$mode" = existing ]; then
    case "`$state" in
      begun) verify_old_official ;;
      backed_up|switching|switched)
        test -f "`$backup_apk"
        test -f "`$backup_manifest"
        test "`$(sudo sha256sum "`$backup_apk" | awk '{print `$1}')" = "$BaselineApkSha256"
        test "`$(sudo stat -c %s "`$backup_apk")" = "$BaselineApkSize"
        test "`$(sudo sha256sum "`$backup_manifest" | awk '{print `$1}')" = "$BaselineManifestSha256"
        sudo cp -p -- "`$backup_apk" "`$restore_apk"
        sudo cp -p -- "`$backup_manifest" "`$restore_manifest"
        test "`$(sudo sha256sum "`$restore_apk" | awk '{print `$1}')" = "$BaselineApkSha256"
        test "`$(sudo stat -c %s "`$restore_apk")" = "$BaselineApkSize"
        test "`$(sudo sha256sum "`$restore_manifest" | awk '{print `$1}')" = "$BaselineManifestSha256"
        sudo mv -f -- "`$restore_apk" "`$work_dir/leshine-expo-kiosk.apk"
        sudo mv -f -- "`$restore_manifest" "`$work_dir/latest.json"
        verify_old_official
        ;;
      restored) verify_old_official ;;
      *) echo 'Unknown existing-channel transaction state; recovery material was preserved.' >&2; return 76 ;;
    esac
  elif [ "`$mode" = initialize ]; then
    case "`$state" in
      begun) verify_empty_official ;;
      switching|switched)
        sudo rm -f -- "`$work_dir/leshine-expo-kiosk.apk"
        sudo rm -f -- "`$work_dir/latest.json"
        verify_empty_official
        ;;
      restored) verify_empty_official ;;
      *) echo 'Unknown initialize transaction state; recovery material was preserved.' >&2; return 76 ;;
    esac
  else
    echo 'Unknown transaction mode; recovery material was preserved.' >&2
    return 76
  fi
  write_state restored
  write_receipt rolled_back
  cleanup_owned_lock
  echo PUBLISH_TXN_ROLLED_BACK
}
"@

    $switch = @"
set -eu
$transactionFunctions
on_switch_failure() {
  original_rc=`$?
  trap - EXIT
  set +e
  ( set -e; rollback_owned_transaction )
  rollback_rc=`$?
  set -e
  if [ "`$rollback_rc" -ne 0 ]; then
    echo "Automatic rollback failed with status `$rollback_rc; recovery material was preserved." >&2
  fi
  if [ "`$original_rc" -eq 0 ]; then original_rc=1; fi
  exit "`$original_rc"
}
trap on_switch_failure EXIT
test "`$(sudo cat "`$lock_dir/owner")" = "`$owner"
test "`$(sudo cat "`$state_file")" = begun
mode=`$(sudo cat "`$lock_dir/mode")
test "`$mode" = "`$expected_mode"
sudo install -m 0644 "`$apk_upload" "`$apk_stage"
sudo install -m 0644 "`$manifest_upload" "`$manifest_stage"
test "`$(sudo sha256sum "`$apk_stage" | awk '{print `$1}')" = "$NewApkSha256"
test "`$(sudo stat -c %s "`$apk_stage")" = "$NewApkSize"
test "`$(sudo sha256sum "`$manifest_stage" | awk '{print `$1}')" = "$NewManifestSha256"
test "`$(sudo stat -c %s "`$manifest_stage")" = "$NewManifestSize"
if [ "`$mode" = existing ]; then
  sudo cp -p -- "`$work_dir/leshine-expo-kiosk.apk" "`$backup_apk"
  sudo cp -p -- "`$work_dir/latest.json" "`$backup_manifest"
  test "`$(sudo sha256sum "`$backup_apk" | awk '{print `$1}')" = "$BaselineApkSha256"
  test "`$(sudo stat -c %s "`$backup_apk")" = "$BaselineApkSize"
  test "`$(sudo sha256sum "`$backup_manifest" | awk '{print `$1}')" = "$BaselineManifestSha256"
  write_state backed_up
fi
write_state switching
sudo mv -f -- "`$apk_stage" "`$work_dir/leshine-expo-kiosk.apk"
sudo mv -f -- "`$manifest_stage" "`$work_dir/latest.json"
write_state switched
rm -f -- "`$apk_upload" "`$manifest_upload"
trap - EXIT
"@

    $rollback = @"
set -eu
$transactionFunctions
rollback_owned_transaction
"@

    $finalize = @"
set -eu
$transactionFunctions
if [ -f "`$receipt_file" ]; then
  verify_receipt_identity
  outcome=`$(receipt_outcome)
  if [ "`$outcome" = finalized ]; then
    verify_new_official
    cleanup_residual_lock_if_owned
    echo PUBLISH_TXN_FINALIZED
    exit 0
  fi
  if [ "`$outcome" = rolled_back ]; then
    if [ "`$expected_mode" = existing ]; then verify_old_official; else verify_empty_official; fi
    echo 'Finalize refused because this transaction was already rolled back.' >&2
    exit 78
  fi
  echo 'Unknown transaction receipt outcome; no files were changed.' >&2
  exit 77
fi
test -d "`$lock_dir"
test "`$(sudo cat "`$lock_dir/owner")" = "`$owner"
test "`$(sudo cat "`$lock_dir/mode")" = "`$expected_mode"
test "`$(sudo cat "`$lock_dir/state")" = switched
verify_new_official
write_receipt finalized
cleanup_owned_lock
echo PUBLISH_TXN_FINALIZED
"@

    return [pscustomobject]@{ Begin = $begin; Switch = $switch; Rollback = $rollback; Finalize = $finalize }
}
