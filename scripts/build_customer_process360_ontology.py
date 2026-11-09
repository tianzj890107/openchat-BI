#!/usr/bin/env python3
"""Build a customer ontology workbook from a trusted DDL-only deployment ZIP.

Does not connect to databases, execute SQL, change business formulas, or enable
queries. Raw customer workbooks and generated delivery files stay outside Git.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import copy, deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_process360_catalog import load_workbook_sheets
from bi_agent.process360.catalog import Process360Catalog

IDENT = r'(?:"[^"]+"|[A-Za-z_][A-Za-z_0-9]*)'
QUALIFIED = rf'{IDENT}\.{IDENT}'
STATUS_OK = 'DDL结构匹配；实库、权限及业务口径未验收'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identifier(text):
    return text.strip().strip('"')


def qualified(text):
    return '.'.join(identifier(part) for part in text.strip().split('.'))


def parse_package(path):
    with zipfile.ZipFile(path) as package:
        def read(suffix):
            matches = [n for n in package.namelist() if n.endswith('/' + suffix) or n == suffix]
            if len(matches) != 1:
                raise ValueError(f'Expected exactly one {suffix}')
            return package.read(matches[0]).decode('utf-8-sig')
        ddl, views, fks = (read(n) for n in ('02_建表_主键_注释.sql', '06_兼容视图.sql', '04_外键.sql'))
    tables = {}
    for match in re.finditer(rf'CREATE TABLE\s+({QUALIFIED})\s*\((.*?)\n\);', ddl, re.I | re.S):
        name, body = qualified(match[1]), match[2]
        columns = {}
        pk = set()
        for found in re.finditer(r'PRIMARY KEY\s*\(([^)]+)\)', body, re.I):
            pk.update(identifier(c) for c in found[1].split(','))
        for line in body.splitlines():
            line = line.strip().rstrip(',')
            if not line or re.match(r'(?:CONSTRAINT|CHECK|PRIMARY|FOREIGN|UNIQUE)\b', line, re.I):
                continue
            found = re.fullmatch(rf'({IDENT})\s+(.+)', line)
            if not found:
                raise ValueError(f'Unsupported column definition: {name}')
            col, rest = identifier(found[1]), found[2]
            dtype = re.split(r'\s+(?:NOT NULL|NULL|DEFAULT|CONSTRAINT|CHECK|REFERENCES)\b', rest, maxsplit=1, flags=re.I)[0]
            if col in columns:
                raise ValueError(f'Duplicate physical column: {name}.{col}')
            columns[col] = dict(type=dtype, notNull=bool(re.search(r'\bNOT NULL\b', rest, re.I)))
        for col in pk:
            if col not in columns:
                raise ValueError(f'Primary key column absent: {name}.{col}')
        tables[name] = dict(columns=columns, primaryKey=sorted(pk))
    if not tables:
        raise ValueError('Deployment DDL contains no tables')
    aliases = {}
    for match in re.finditer(rf'CREATE VIEW\s+({QUALIFIED})\s+AS SELECT\s+(.+?)\s+FROM\s+({QUALIFIED})\s*;', views, re.I | re.S):
        view, source = qualified(match[1]), qualified(match[3])
        if source not in tables:
            raise ValueError(f'Unknown view source: {source}')
        fields = {}
        # The supported package has simple projections and NULL::<type> placeholders.
        # Reject richer SQL instead of guessing joins, casts, expressions or literals.
        for item in match[2].split(','):
            item = item.strip()
            found = re.fullmatch(rf'({IDENT})(?:\s+AS\s+({IDENT}))?', item, re.I)
            missing = re.fullmatch(rf'NULL::[A-Za-z_0-9]+\s+AS\s+({IDENT})', item, re.I)
            if missing:
                fields[identifier(missing[1])] = None
            elif found:
                field, alias = identifier(found[1]), identifier(found[2] or found[1])
                if field not in tables[source]['columns']:
                    raise ValueError(f'View column absent: {source}.{field}')
                if alias in fields:
                    raise ValueError(f'Duplicate view alias: {view}.{alias}')
                fields[alias] = field
            else:
                raise ValueError(f'Unsupported compatibility expression: {view}: {item}')
        aliases[view.split('.', 1)[1]] = dict(table=source, fields=fields, view=view)
    declared_views = len(re.findall(r'\bCREATE VIEW\b', views, re.I))
    if len(aliases) != declared_views:
        raise ValueError('Not all compatibility views were parsed')
    foreign_keys = []
    pattern = rf'ALTER TABLE\s+({QUALIFIED})\s+ADD CONSTRAINT\s+({IDENT})\s+FOREIGN KEY\s*\(([^)]+)\)\s+REFERENCES\s+({QUALIFIED})\s*\(([^)]+)\)\s+NOT VALID'
    for match in re.finditer(pattern, fks, re.I):
        child, name, parent = qualified(match[1]), identifier(match[2]), qualified(match[4])
        children = [identifier(c) for c in match[3].split(',')]
        parents = [identifier(c) for c in match[5].split(',')]
        if len(children) != len(parents):
            raise ValueError('Invalid foreign key arity')
        for table, cols in ((child, children), (parent, parents)):
            if table not in tables or any(c not in tables[table]['columns'] for c in cols):
                raise ValueError(f'Invalid foreign key: {name}')
        foreign_keys.append(dict(name=name, childTable=child, childFields=children,
                                 parentTable=parent, parentFields=parents))
    if len(foreign_keys) != len(re.findall(r'ADD CONSTRAINT\s+\S+\s+FOREIGN KEY', fks, re.I)):
        raise ValueError('Not all foreign keys were parsed')
    return dict(tables=tables, aliases=aliases, foreignKeys=foreign_keys)


def rows(ws):
    headers = {str(cell.value): cell.column for cell in ws[1] if cell.value is not None}
    return headers, [{key: ws.cell(i, col).value for key, col in headers.items()}
                     for i in range(2, ws.max_row + 1)]


def extra_columns(ws, names):
    headers = {str(cell.value): cell.column for cell in ws[1] if cell.value is not None}
    for name in names:
        if name not in headers:
            headers[name] = ws.max_column + 1
            cell = ws.cell(1, headers[name], name)
            cell._style = copy(ws.cell(1, 1)._style)
    return headers


def write_sheet(wb, name, headers, data):
    if name in wb.sheetnames:
        raise ValueError(f'Refusing to overwrite existing customer sheet: {name}')
    ws = wb.create_sheet(name)
    ws.append(headers)
    for row in data:
        # Do not let imported comments become executable spreadsheet formulas.
        ws.append([("'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@')) else value)
                   for value in row])
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.fill = PatternFill('solid', fgColor='165DFF')
        cell.font = Font(color='FFFFFF', bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical='top')
    for column in ws.columns:
        ws.column_dimensions[column[0].column_letter].width = min(65, max(16, max(len(str(c.value or '')) for c in column[:30]) + 2))
    return ws


def build(source, package, output, base_catalog):
    source, package, output, base_catalog = map(Path, (source, package, output, base_catalog))
    output.mkdir(parents=True, exist_ok=True)
    target = output / (source.stem + '_客户ded_public部署版_' + datetime.now().strftime('%Y%m%d') + '.xlsx')
    targets = [target, output / 'catalog.json', output / 'manifest.json', output / '适配核对报告.json', output / 'README.md']
    if any(p.exists() for p in targets):
        raise ValueError('Output already exists; choose a fresh delivery directory')
    model = parse_package(package)
    wb = load_workbook(source)
    missing, attribute_map, entities, impacts = [], {}, {}, []
    entity_sheet = wb['逻辑实体映射']
    h, records = rows(entity_sheet)
    h = extra_columns(entity_sheet, ['原关联物理表', '客户接入状态', '客户兼容视图'])
    for i, row in enumerate(records, 2):
        old = str(row['关联物理表'] or '')
        mapped = model['aliases'].get(old.split('.')[-1])
        code = row['逻辑实体编码']
        entities[code] = mapped
        entity_sheet.cell(i, h['原关联物理表']).value = old
        entity_sheet.cell(i, h['关联物理表']).value = mapped['table'] if mapped else None
        entity_sheet.cell(i, h['客户兼容视图']).value = mapped['view'] if mapped else None
        entity_sheet.cell(i, h['客户接入状态']).value = STATUS_OK if mapped else 'blocked：部署包缺少物理表'
        if not mapped:
            missing.append(dict(kind='table', entity=code, attribute='', original=old, reason='部署包未定义物理表'))
    ws = wb['业务属性映射']
    h, records = rows(ws)
    h = extra_columns(ws, ['原来源表名', '原来源字段', '客户物理类型', '客户字段非空', '客户物理主键', '客户接入状态'])
    for i, row in enumerate(records, 2):
        old, field = str(row['来源表名'] or ''), str(row['来源字段'] or '')
        mapped = entities.get(row['逻辑实体编码'])
        physical = mapped['fields'].get(field) if mapped else None
        key = f"{row['逻辑实体编码']}.{row['业务属性编码']}"
        attribute_map[key] = dict(table=mapped['table'] if mapped else None, field=physical)
        for name, value in (('原来源表名', old), ('原来源字段', field),
                            ('来源表名', mapped['table'] if mapped else None), ('来源字段', physical)):
            ws.cell(i, h[name]).value = value
        if physical:
            table = model['tables'][mapped['table']]
            ws.cell(i, h['客户物理类型']).value = table['columns'][physical]['type']
            ws.cell(i, h['客户字段非空']).value = 'Y' if table['columns'][physical]['notNull'] else 'N'
            ws.cell(i, h['客户物理主键']).value = 'Y' if physical in table['primaryKey'] else 'N'
            ws.cell(i, h['客户接入状态']).value = STATUS_OK
        else:
            reason = '部署包未定义物理表' if not mapped else ('兼容视图仅以NULL占位' if field in mapped['fields'] else '兼容视图未声明该字段')
            ws.cell(i, h['客户接入状态']).value = 'blocked：' + reason
            missing.append(dict(kind='column', entity=row['逻辑实体编码'], attribute=row['业务属性编码'], original=old+'.'+field, reason=reason))
    # Keep logical data types, business formulas and approvals unchanged. Attach the
    # governed physical type to the attribute definitions for explicit comparison.
    ws = wb['业务属性']
    h, records = rows(ws)
    h = extra_columns(ws, ['客户来源表名', '客户来源字段', '客户物理类型', '客户接入状态'])
    for i, row in enumerate(records, 2):
        mapping = attribute_map.get(f"{row['逻辑实体编码']}.{row['业务属性编码']}", {})
        physical, table = mapping.get('field'), mapping.get('table')
        for name, value in (('客户来源表名', table), ('客户来源字段', physical),
                            ('客户物理类型', model['tables'][table]['columns'][physical]['type'] if physical else None),
                            ('客户接入状态', STATUS_OK if physical else 'blocked：缺少物理映射')):
            ws.cell(i, h[name]).value = value
    ws = wb['指标']
    h, records = rows(ws)
    h = extra_columns(ws, ['客户结构状态', '客户缺失依赖', '客户验收说明'])
    missing_keys = {f"{m['entity']}.{m['attribute']}" for m in missing if m['kind'] == 'column'}
    for i, row in enumerate(records, 2):
        source_text = ' '.join(str(row.get(k) or '') for k in ('来源逻辑实体','来源业务属性','时间维度','过滤条件','计算规则'))
        refs = set(re.findall(r'LE\d+\.AT\d+', source_text))
        absent = sorted(refs & missing_keys)
        absent += sorted(code for code in set(re.findall(r'LE\d+', source_text)) if code in entities and not entities[code])
        state = 'blocked：缺少物理依赖' if absent else ('DDL依赖匹配；执行许可及实库待验收' if refs else '未声明完整属性依赖；不得据此启用')
        ws.cell(i, h['客户结构状态']).value = state
        ws.cell(i, h['客户缺失依赖']).value = '、'.join(absent)
        ws.cell(i, h['客户验收说明']).value = '仅核对DDL，不改变原执行许可、阈值与业务批准；未验证数据、单位、枚举、去重和指标SQL。'
        impacts.append(dict(code=row['指标编码'], name=row['指标名称'], status=state, missing=absent))
    ws = wb['实体关系']
    h, records = rows(ws)
    h = extra_columns(ws, ['客户外键约束', '客户关系结构状态'])
    relation_counts = Counter()
    for i, row in enumerate(records, 2):
        left = attribute_map.get(f"{row.get('源逻辑实体编码')}.{row.get('源关联属性编码')}", {})
        right = attribute_map.get(f"{row.get('目标逻辑实体编码')}.{row.get('目标关联属性编码')}", {})
        matches = [fk['name'] for fk in model['foreignKeys']
                   for c, p in zip(fk['childFields'], fk['parentFields'])
                   if ((left.get('table'), left.get('field'), right.get('table'), right.get('field')) in
                       [(fk['parentTable'], p, fk['childTable'], c), (fk['childTable'], c, fk['parentTable'], p)])]
        # The supplied package currently uses only single-column foreign keys.
        state = 'DDL已声明；实库VALIDATE未验收' if matches else '待确认：未匹配部署包外键，不代表不存在业务关系'
        ws.cell(i, h['客户外键约束']).value = '、'.join(matches)
        ws.cell(i, h['客户关系结构状态']).value = state
        relation_counts['matched' if matches else 'unmatched'] += 1
    mapped_tables = {value['table'] for value in entities.values() if value}
    unmodeled = sorted(set(model['tables']) - mapped_tables)
    for table in unmodeled:
        missing.append(dict(kind='unmodeled_table', entity='', attribute='', original=table,
            reason='运行审计表，不自动纳入经营本体' if table.split('.')[-1].startswith('audit_')
                   else '客户物理表尚无原本体逻辑实体；不猜测业务属性与指标关联'))
    missing.append(dict(kind='static_config',entity='',attribute='',original='x360_static_metric_config',
                        reason='部署包未包含静态指标配置，须另行同步'))
    table_rows, field_rows = [], []
    for table, spec in sorted(model['tables'].items()):
        assumed = table.endswith(('.p_fm_bid_project_info', '.p_fm_project_main', '.p_fm_project_detail'))
        table_rows.append([table, len(spec['columns']), ','.join(spec['primaryKey']), '假设主键；唯一性待实库验收' if assumed else 'DDL声明；实库待验收'])
        for col, info in spec['columns'].items():
            field_rows.append([table, col, info['type'], info['notNull'], col in spec['primaryKey']])
    write_sheet(wb, '客户物理表', ['物理表','字段数','主键','校验范围'], table_rows)
    write_sheet(wb, '客户物理字段', ['物理表','字段','治理后类型','非空','主键'], field_rows)
    write_sheet(wb, '客户外键', ['约束名','子表','子字段','父表','父字段','校验范围'],
                [[f['name'],f['childTable'],','.join(f['childFields']),f['parentTable'],','.join(f['parentFields']),'仅DDL；NOT VALID不代表实库验证通过'] for f in model['foreignKeys']])
    write_sheet(wb, '客户适配缺口', ['缺口类型','逻辑实体','业务属性','原来源','原因'],
                [[m[k] for k in ('kind','entity','attribute','original','reason')] for m in missing])
    write_sheet(wb, '客户指标影响', ['指标编码','指标名称','客户结构状态','客户缺失依赖'],
                [[v['code'],v['name'],v['status'],'、'.join(v['missing'])] for v in impacts])
    info = [
        ['适用范围','按部署包DDL更新物理映射；不是已完成客户数据库联调。'],
        ['源工作簿SHA256',sha(source)],['部署包SHA256',sha(package)],
        ['schema','ded_public是schema；数据库名称、端口由部署配置指定，不从schema推断。'],
        ['数据库选择','包说明建议源库之外建立治理库；不要默认把ded_public源库当成治理库。'],
        ['缺失字段','NULL占位列不是已存在的物理字段；对应来源字段留空，并列为blocked。'],
        ['原有配置','原始Excel保留；业务对象编码、逻辑属性、指标公式、阈值、审批状态不擅自改动。'],
        ['静态指标配置','x360_static_metric_config不在包内，需另行提供；不可填造目标。'],
        ['旧说明范围','使用说明、校验结果、变更清单原有记录为原版历史，不代表客户实库已验收。'],
        ['运行时','Process360消费随包catalog.json；仅替换Excel不会自动热更新服务。'],
        ['SQL限制','本文件不改写现有硬编码SQL。运行SQL若使用旧ywln_crm表名，仍需兼容视图或另行适配。'],
        ['安全','不含数据库密码、模型密钥或实际业务记录；未连接数据库或执行部署SQL。'],
    ]
    write_sheet(wb, '客户部署说明', ['项目','说明'], info)
    wb.active = wb.sheetnames.index('客户部署说明')
    wb.save(target)
    base = json.loads(base_catalog.read_text())
    payload = deepcopy(base)
    sheets = load_workbook_sheets(target)
    customer_keys = {'客户部署说明':'customer_deployment','客户物理表':'customer_tables',
                     '客户物理字段':'customer_columns','客户外键':'customer_foreign_keys',
                     '客户适配缺口':'customer_gaps','客户指标影响':'customer_metric_impacts'}
    for sheet, key in customer_keys.items():
        _, values = rows(wb[sheet])
        sheets[key] = values
    # openpyxl preserves formulas but clears their cached numeric results.
    # For untouched sheets, retain the original source's data-only values
    # (not the saved workbook's empty formula caches).
    changed_keys = {'entity_mappings','attribute_mappings','attributes','metrics','entity_relations'}
    original_sheets = load_workbook_sheets(source)
    for key, values in original_sheets.items():
        if key not in changed_keys:
            sheets[key] = values
    payload['sheets'] = sheets
    payload['summary'] = {key: len(value) for key,value in sorted(sheets.items())} | {'sops': len(base['sops'])}
    payload['catalogId'] = 'ywln-process360-customer-ded-public'
    payload['generatedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    payload['source']['model'] = dict(fileName=target.name, sha256=sha(target))
    payload['source']['deploymentPackage'] = dict(fileName=package.name,sha256=sha(package))
    payload['source']['baseCatalogSha256'] = sha(base_catalog)
    payload['source']['note'] = 'Customer DDL-aligned catalog; DDL validation is not live DB/SQL acceptance.'
    catalog_path = output / 'catalog.json'
    catalog_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    errors = [issue.to_dict() for issue in Process360Catalog.from_file(catalog_path).validate() if issue.severity == 'error']
    if errors:
        raise ValueError('Generated catalog validation failed: '+json.dumps(errors,ensure_ascii=False))
    report = dict(tables=len(model['tables']), physicalColumns=sum(len(t['columns']) for t in model['tables'].values()),
                  foreignKeys=len(model['foreignKeys']), compatibilityViews=len(model['aliases']),
                  entities=len(entities), mappedEntities=sum(bool(v) for v in entities.values()),
                  attributes=len(attribute_map), mappedAttributes=sum(bool(v['field']) for v in attribute_map.values()),
                  unmodeledPhysicalTables=unmodeled,
                  missing=missing, metricStatuses=dict(Counter(v['status'] for v in impacts)),
                  relations=dict(relation_counts), catalogErrors=errors, liveDatabaseVerified=False)
    (output/'适配核对报告.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (output/'README.md').write_text('# 客户Process360本地本体\n\n'
        'Excel是可维护交付文件，catalog.json是配套运行时文件，两者必须一起更新。\n\n'
        f'本包按客户DDL静态核对：{report["tables"]}张表、{report["foreignKeys"]}个外键；'
        f'映射{report["mappedEntities"]}/{report["entities"]}个实体、{report["mappedAttributes"]}/{report["attributes"]}个属性。\n\n'
        '先阅读Excel“客户部署说明”“客户适配缺口”“客户指标影响”。NULL占位未当作物理字段。'
        '未验证客户数据库、数据量、SQL与权限；此包不自动部署、不自动切换线上配置。\n\n'
        '后续授权部署时，将PROCESS360_CATALOG_PATH指向本包catalog.json；数据库/schema单独配置。'
        '现有SQL若使用ywln_crm兼容视图，须另外验收视图或适配SQL；更换本体不等于SQL自动改写。\n')
    manifest = dict(schema='process360.customer-ontology-delivery.v1',
                    sourceWorkbookSha256=sha(source),deploymentPackageSha256=sha(package),
                    files={p.name:sha(p) for p in targets if p.name!='manifest.json'})
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--package',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--base-catalog',type=Path,default=ROOT/'dataset/process360/ywln-v3.1/catalog.json')
    args=parser.parse_args()
    report=build(args.source,args.package,args.output,args.base_catalog)
    print(json.dumps({k:v for k,v in report.items() if k!='missing'},ensure_ascii=False))


if __name__=='__main__':
    main()
