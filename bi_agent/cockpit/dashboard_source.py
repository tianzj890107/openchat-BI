"""Server-owned replay of the exact AP requests rendered by the cockpit."""
import hashlib
import json
from pathlib import Path

SNAPSHOT = Path(__file__).parents[1] / "web/static/cockpit/metadata/pdt-release-2109836674373566465/data-snapshots.json"
RELEASE = "pdt-release-2109836674373566465"
TOOL = "Cockpit-DashboardQuery"
SCHEMA = {"name": TOOL, "description": "读取本轮看板实际展示的 AP 查询、字段口径和原始结果。只读交付快照，不是实时数据库。先读目录，再按 queryId 读取。禁止把采购字段解释为销售指标。", "input_schema": {"type": "object", "properties": {"queryId": {"type": "string"}}, "additionalProperties": False}}


def material(context):
    if context.get('chartSnapshotId') != RELEASE:
        raise ValueError('缺少或不支持的看板快照标识，请从当前看板重新发起')
    queries = context.get('chartQueries') or []
    if not queries or len(queries) > 80:
        raise ValueError('必须指定当前看板已经展示的 AP 查询')
    snapshot = json.loads(SNAPSHOT.read_text())
    selected = {}
    for key in sorted(set(queries)):
        request = json.loads(key)
        canonical = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        section = 'batch' if isinstance(request, list) else 'analysis'
        hit = next((value for raw, value in snapshot[section].items()
                    if json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, separators=(',', ':')) == canonical), None)
        if not hit or not hit.get('success') or not hit.get('data'):
            raise ValueError('查询没有对应的成功看板快照，不能换源补数')
        entries = list(zip(request,hit['data'])) if section=='batch' else [(request,hit)]
        if section=='batch' and len(request)!=len(hit['data']):raise ValueError('批量AP结果不完整')
        for index,(query,response) in enumerate(entries):
            if not response.get('success') or not response.get('data'):raise ValueError('批量AP子查询失败')
            query_id=hashlib.sha256((canonical+':'+str(index)).encode()).hexdigest()[:20]
            selected[query_id] = {'request': query, 'response': response['data']}
    fingerprint = hashlib.sha256(json.dumps(selected, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    return fingerprint, selected


def executor(selected):
    def read(params, cwd):
        query_id = params.get('queryId')
        if query_id:
            if query_id not in selected:
                raise ValueError('queryId不属于当前看板分析范围')
            entry = selected[query_id]
            result = entry['response'].get('result', {})
            labels = {col['identifierCode']: col.get('label', col['identifierCode'])
                      for col in result.get('columns', []) if 'identifierCode' in col}
            rows = [{labels.get(code, code) + '[' + code + ']': cell.get('value') if isinstance(cell, dict) else cell
                     for code, cell in row.items()} for row in result.get('rows', []) if isinstance(row, dict)]
            return json.dumps({'source': RELEASE, 'queryId': query_id, **entry,
                'data': {'rows': rows}, 'scope': {'snapshot': RELEASE, 'request': entry['request']},
                'semantic': {'metric': query_id, 'definition': labels, 'live': False},
                'provenance': {'source': RELEASE, 'query': json.dumps(entry['request'], ensure_ascii=False)}}, ensure_ascii=False)
        return json.dumps({'source': RELEASE, 'live': False, 'queries': [
            {'queryId': key, 'request': value['request'], 'columns': value['response'].get('result', {}).get('columns', [])}
            for key, value in selected.items()], 'limitations': '原始AP请求决定实际时间和部门口径；页面标题不构成字段定义。没有同源明细补查接口，不能认定根因。'}, ensure_ascii=False)
    return read
