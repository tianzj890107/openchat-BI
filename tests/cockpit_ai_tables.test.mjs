import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const root = new URL('../bi_agent/web/static/cockpit/', import.meta.url);
const names = ['star-product-order-list', 'affected-order-list', 'overdue-order-list'];

test('the three order DataTables use the shared ProDataTable adapter', async () => {
  const registry = await readFile(new URL('insight-components/index.js', root), 'utf8');
  const runtime = await readFile(new URL('insight-components/table-runtime.js', root), 'utf8');
  assert.match(runtime, /ProUIBi\.ProDataTable/);
  assert.match(runtime, /ai-tables\/\$\{encodeURIComponent\(tableKey\)\}\/query/);
  assert.match(runtime, /tableFields: displayFields/);
  for (const name of names) {
    assert.match(registry, new RegExp(`'${name}'`));
    const source = await readFile(new URL(`insight-components/${name}/index.js`, root), 'utf8');
    assert.match(source, /createTableInsight/);
    assert.match(source, new RegExp(`tableKey: '${name}'`));
    assert.doesNotMatch(source, /postAnalysisDataQuery/);
    assert.doesNotMatch(source, /\/api\/mock\//);
  }
});

test('table columns match the delivered AP facts and validated AI fields', async () => {
  const star = await readFile(new URL('insight-components/star-product-order-list/index.js', root), 'utf8');
  assert.match(star, /label: '口径'/);
  assert.match(star, /YWLN_M_STAR_PRODUCT_ORDER_SHARE/);

  const affected = await readFile(new URL('insight-components/affected-order-list/index.js', root), 'utf8');
  assert.match(affected, /label: '原因'/);
  assert.match(affected, /label: '责任动作'/);

  const overdue = await readFile(new URL('insight-components/overdue-order-list/index.js', root), 'utf8');
  assert.match(overdue, /label: '主因和根因分析'/);
  assert.doesNotMatch(overdue, /YWLN_D003/);
});
