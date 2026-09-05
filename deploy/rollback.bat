chcp 65001 >nul
@echo off
setlocal
REM Legacy snapshots are incompatible with content-addressed releases and shared schema checks.
echo [BLOCKED] The old rollback snapshot is no longer a valid release boundary.
echo Failed activations restore their previous code/assets automatically when the schema is unchanged.
echo For a completed release rollback, inspect .deploy_state/publish-current.json and follow deploy/README.md.
echo Database downgrade and raw SCP into managed static roots are prohibited.
exit /b 1
