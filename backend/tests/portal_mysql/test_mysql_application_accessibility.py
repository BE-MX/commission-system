"""Actual customer error recovery; no quote, order, PI or financial graph writes."""
import json
from pathlib import Path
import pytest
from test_mysql_application_trade import commerce, business_snapshot  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_customer_application_browser import ROOT, live_application, run_browser


def test_actual_customer_keyboard_quantity_error_and_catalog_recovery(commerce, request):
    c=commerce
    runtime=[request.config.getoption('portal_browser_'+name) for name in ('node','module','chromium')]
    if not all(runtime):pytest.skip('Explicit owned Node, Playwright and Chrome paths required')
    node,playwright,chrome=(str(Path(value).resolve(strict=True)) for value in runtime)
    output=Path(request.config.getoption('portal_mysql_workspace')).resolve()/'accessibility-evidence';output.mkdir()
    before=business_snapshot(c)[:9]
    with live_application(c) as (origin,shell):
        summary=run_browser(c,shell,node,ROOT/'frontend-portal/tests/applicationAccessibility.browser.mjs',origin,playwright,chrome,output)
        (output/'runner-summary.json').write_text(json.dumps(summary),encoding='utf-8')
        assert summary['exit_code']==0 and not summary['timed_out'] and summary['child_reaped'] and not summary['cleanup_failure']
        report=json.loads((output/'report.json').read_text())
        assert report['status']=='pass' and report['catalogGetAborts']==1 and report['catalogGetContinues']>=1
        assert report['businessResponseReplacements']==0 and report['quantityErrorAccessible'] and report['quantityRecovered']==3
        assert report['reduced']['media'] and report['interaction']['mode']=='keyboard'
        assert not shell.pdf_documents and not shell.arm_accept and shell.fault_count==0
        assert all(method!='POST' or not (path.endswith('/quotes') or path.endswith('/orders') or path.endswith('/accept')) for method,path in shell.calls)
        # OTP queues are expected authentication writes; all nine original
        # request/revision/PI/receipt/conversion/publication graphs stay exact.
        assert business_snapshot(c)[:9]==before
        assert c.calls==[] and c.forbidden_writes==[]
