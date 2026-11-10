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
  assert.match(runtime, /filterFields = \[\]/);
  assert.match(runtime, /function apQuery\(ctx, fields, filterFields, sort\)/);
  assert.match(runtime, /commonConfig\.sorts = sorts/);
  assert.match(runtime, /dataConfig: \{[\s\S]{0,200}sort/);
  assert.match(runtime, /dataConfig: \{[\s\S]{0,240}filter: filterFields/);
  assert.match(runtime, /uiScope: pageScope\(props\)/);
  assert.match(runtime, /period: String\(slot\.period \|\| ''\)/);
  assert.match(runtime, /cacheOnly: true/);
  assert.match(runtime, /已加载上次保存的表格/);
  assert.match(runtime, /querySignature[\s\S]*props\.analysis\?\.id[\s\S]*props\.analysis\?\.updatedAt/);
  assert.match(runtime, /componentKey = Vue\.computed\(\(\) => `\$\{pageScope\(props\)\}:\$\{revision\.value\}`\)/);
  assert.doesNotMatch(runtime, /componentKey[\s\S]{0,80}analysis\?\.updatedAt/);
  assert.match(runtime, /stable\(live\.data\) !== stable\(previous\?\.data \|\| \[\]\)/);
  assert.doesNotMatch(runtime, /live\.meta\.generatedAt[\s\S]{0,100}revision\.value/);
  assert.match(runtime, /contentSignature\(tableKey, props, ctx, fields, filterFields, sort\)/);
  assert.match(runtime, /Vue\.watch\(\(\) => \[props\.analysis\?\.id[\s\S]{0,220}refreshInBackground/);
  for (const name of names) {
    assert.match(registry, new RegExp(`'${name}'`));
    const source = await readFile(new URL(`insight-components/${name}/index.js`, root), 'utf8');
    assert.match(source, /createTableInsight/);
    assert.match(source, /const SORT_FIELDS = \[/);
    assert.match(source, /sort: SORT_FIELDS/);
    assert.match(source, new RegExp(`tableKey: '${name}'`));
    assert.doesNotMatch(source, /postAnalysisDataQuery/);
    assert.doesNotMatch(source, /\/api\/mock\//);
  }
});

test('table columns match the delivered AP facts and validated AI fields', async () => {
  const star = await readFile(new URL('insight-components/star-product-order-list/index.js', root), 'utf8');
  assert.match(star, /label: '口径'/);
  assert.match(star, /YWLN_M_ORDER_RECEIPT_ENERGY_PCT/);
  assert.match(star, /label: '去年参考电量'/);
  assert.doesNotMatch(star, /YWLN_M_STAR_PRODUCT_ORDER_SHARE/);

  const affected = await readFile(new URL('insight-components/affected-order-list/index.js', root), 'utf8');
  assert.match(affected, /YWLN_D016/);
  assert.match(affected, /YWLN_M0032/);
  assert.match(affected, /YWLN_M0033/);
  assert.match(affected, /label: '原因'/);
  assert.match(affected, /label: '责任动作'/);
  assert.match(affected, /operator: \{code: 'IN', type: 'STRING'\}/);
  assert.match(affected, /value: \['order_change', 'order_cancel'\]/);
  assert.match(affected, /filterFields/);

  const overdue = await readFile(new URL('insight-components/overdue-order-list/index.js', root), 'utf8');
  assert.match(overdue, /label: '主因和根因分析'/);
  assert.doesNotMatch(overdue, /YWLN_D003/);
  assert.match(overdue, /operator: \{code: 'GT', type: 'NUMBER'\}/);
  assert.match(overdue, /filterFields/);
  assert.match(overdue, /isTree: true, label: '承诺发货日'/);
});

test('upstream default, click and explicit clear reach AP with the same sorting semantics', async () => {
  const text=await readFile(new URL('insight-components/table-runtime.js',root),'utf8');
  globalThis.window={InsightRuntime:{cockpitApiBase:()=>'/api/cockpit',cockpitIdentityId:()=>1}};
  const {apQuery}=await import('data:text/javascript;base64,'+Buffer.from(text).toString('base64'));
  const defaults=[{identifierCode:'ENERGY',order:'DESC'}];
  const fields=[{identifierCode:'ENERGY',fieldType:'Indicator',label:'电量'}];
  assert.deepEqual(apQuery({},fields,[],defaults).commonConfig.sorts,[{identifierCode:'ENERGY',order:'DESC'}]);
  assert.deepEqual(apQuery({params:{sortField:'ENERGY',sortOrder:'ascend'}},fields,[],defaults).commonConfig.sorts,[{identifierCode:'ENERGY',order:'ASC'}]);
  for(const params of [{sortCleared:true},{sortOrder:null}]) {
    const payload=apQuery({params},fields,[],defaults);
    assert.deepEqual(payload.commonConfig.sorts,[],'clear must remain explicit, so server does not reapply defaults');
  }
  assert.equal(defaults[0].order,'DESC');
});
