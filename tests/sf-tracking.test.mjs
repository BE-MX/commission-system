import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSfRoutes, querySf, sfTime, sfState } from '../app/lib/sf-tracking.ts';

const track = 'SF1000000000000';
const payload = (routes, mailNo = track) => ({ apiResultCode: 'A1000', apiResultData: JSON.stringify({ success: true, errorCode: 'S0000', msgData: { routeResps: [{ mailNo, routes }] } }) });
const route = (acceptTime, firstStatusCode = '2') => ({ acceptTime, firstStatusCode, remark: '快件运输中', acceptAddress: '济南' });

test('SF Beijing dates sort chronologically, deduplicate, and reject invalid dates', () => {
  const late = route('2026-11-18 09:30:00', '4');
  const result = parseSfRoutes(payload([late, route('2026-7-3 09:30:00'), late, route('2026-02-30 09:30:00')]), track);
  assert.equal(result.events.length, 2);
  assert.equal(result.state, 'delivered');
  assert.equal(result.events[0].time, '2026-11-18T09:30:00+08:00');
  assert.equal(Date.parse(sfTime('2026-11-18 00:01:00')), Date.parse('2026-11-17T16:01:00Z'));
  assert.equal(sfTime('not a date'), null);
});
test('outer permission errors and inner business errors never look like a successful empty route', () => {
  assert.throws(() => parseSfRoutes({ apiResultCode: 'A1004', apiErrorMsg: 'secret must not echo' }, track), /权限尚未开通/);
  assert.throws(() => parseSfRoutes({ apiResultCode: 'A1000', apiResultData: '{"success":false}' }, track));
  assert.deepEqual(parseSfRoutes(payload([]), track).events, []);
  assert.deepEqual(parseSfRoutes(payload([route('2026-11-18 09:30:00')], 'SF9999999999999'), track).events, []);
});
test('returned, exceptional and customs states take precedence over delivered codes', () => {
  assert.equal(sfState({ firstStatusCode: '4', secondaryStatusName: '已退回' }), 'returned');
  assert.equal(sfState({ firstStatusCode: '4', opCode: '934' }), 'exception');
  assert.equal(sfState({ firstStatusCode: '2', secondaryStatusCode: '204' }), 'customs_hold');
  assert.equal(sfState({ firstStatusCode: '11' }), 'out_for_delivery');
});
test('OAuth form protocol, cached token, one A1011 refresh, last-four and no msgDigest', async () => {
  const config = { partnerId: crypto.randomUUID(), checkword: 'test-only-secret', sandbox: true };
  let tokens = 0, queries = 0, reserved = 0;
  const fake = async (url, init) => {
    const form = new URLSearchParams(init.body);
    assert.equal(form.get('partnerID'), config.partnerId);
    if (url.endsWith('/oauth2/accessToken')) {
      tokens++; assert.equal(form.get('secret'), config.checkword);
      return Response.json({ apiResultCode: 'A1000', accessToken: 'test-token-' + tokens, expiresIn: 7200 });
    }
    queries++; assert.equal(form.has('msgDigest'), false);
    assert.equal(form.get('serviceCode'), 'EXP_RECE_SEARCH_ROUTES');
    assert.equal(JSON.parse(form.get('msgData')).checkPhoneNo, '1234');
    return Response.json(queries === 1 ? { apiResultCode: 'A1011' } : payload([route('2026-11-18 09:30:00')]));
  };
  await querySf(config, track, '1234', async () => { reserved++; }, fake);
  await querySf(config, track, '1234', async () => { reserved++; }, fake);
  assert.equal(tokens, 2); assert.equal(queries, 3); assert.equal(reserved, 3);
});
test('failed token never triggers a route query; network errors are sanitized', async () => {
  let calls = 0;
  await assert.rejects(querySf({ partnerId: crypto.randomUUID(), checkword: 'secret', sandbox: false }, track, '', async () => {}, async () => {
    calls++; return Response.json({ apiResultCode: 'A1011' });
  }), /身份校验失败/);
  assert.equal(calls, 1);
  await assert.rejects(querySf({ partnerId: crypto.randomUUID(), checkword: 'secret', sandbox: true }, track, '', async () => {}, async () => { throw new Error('secret'); }), /暂时未响应/);
});
