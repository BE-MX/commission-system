# Cloud translation routing and validation

Version `1.2.6` uses the cloud translation API. It was verified first as `1.2.6-cloud-test`, based on main `204cd788`, then promoted by removing the test display label without changing request behavior. Source integration does not deploy the backend or publish the download site.

- All extension API requests use `https://leshine.cloud/api/whatsapp-translation`.
- Host permission is limited to `https://leshine.cloud/*`.
- The stable extension ID remains `bnkecbkoidckffckbefjjcbchmngjobi`; the storage schema and device token handling are unchanged. Updating the existing installation without uninstalling is intended to preserve its pairing; the successful cloud session validation is recorded below.
- The pairing confirmation URL remains restricted to `https://leshine.work/whatsapp-translation/authorize`, matching the Beijing backend's verified `SHORT_LINK_BASE_URL`. Opening this normal web page does not require extension host permission.
- No domain fallback, new telemetry, automatic sending, token export, backend modification or deployment was added.

## User-assisted loading

Browser automation is blocked from opening the extension manager by the browser URL policy. Loading/updating and accepting any Chrome permission prompt must therefore be done by the user; do not work around this restriction.

1. Back up the folder currently loaded by Chrome. Do not uninstall the extension or clear its storage.
2. Replace the contents of that existing loaded folder with the contents of the `1.2.6` ZIP, keeping `manifest.json` directly in the loaded folder.
3. Reload the extension in Chrome's extension manager and review the cloud host permission if Chrome asks. Confirm the displayed version is `1.2.6`.
4. Refresh WhatsApp Web and check that the extension remains signed in. If it asks for pairing, use the normal Ark confirmation flow; do not share any token.

## End-to-end acceptance

2026-09-07 15:30: the user loaded the test ZIP and reported approximately three seconds for a synthetic self-chat translation. Cloud device metadata confirmed active version `1.2.6`; cloud session and translation requests returned 200. The matching latest outgoing model call succeeded in 1692 ms. This verifies one authenticated live path with user-observed timing, not a precise multi-sample UI benchmark. No token or chat content was retrieved.

Use a self-chat or an agreed test conversation. Put only the following synthetic text into the composer and click the extension's translate button; do not click WhatsApp's Send control:

> 您好，SKU-T42 的顺发接发样品已准备好，数量是 2 件。请确认色号和收货地址。

Record time from clicking Translate until the preview and back-translation are visible. Check the SKU, quantity and product term. For further samples use a new synthetic SKU each time (for example T43, T44), because the extension's in-memory cache can make repeated identical text appear artificially fast.

The existing automated synthetic tests verify client routing, authentication behavior, rendering and the no-send boundary; they do not replace this authenticated live test. No real chat content, contact identity, screenshot or token should be copied into the report.

For rollback, restore the backed-up loaded folder and reload the extension and WhatsApp Web. No database migration is involved.
