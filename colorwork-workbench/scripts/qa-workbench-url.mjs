import assert from 'node:assert/strict';
import test from 'node:test';
import { WORKBENCH_PATH, workbenchUrl } from '../lib/workbench-url.ts';

test('all root-relative file/API paths stay inside the Ark module', () => {
  for (const path of ['/api/artifacts?scope=shared', '/api/runtime-assets/a%20b.jpg', '/?view=master']) {
    assert.equal(workbenchUrl(path), WORKBENCH_PATH + path);
    assert.equal(workbenchUrl(workbenchUrl(path)), WORKBENCH_PATH + path);
  }
});

test('persisted data/blob URLs and missing optional images remain usable', () => {
  for (const path of ['data:image/png;base64,abc', 'blob:http://localhost/id', 'https://example.com/image.jpg']) {
    assert.equal(workbenchUrl(path), path);
  }
  assert.equal(workbenchUrl(undefined), '');
});
