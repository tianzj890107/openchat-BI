from pathlib import Path
import json
import zipfile
import pytest
from openpyxl import Workbook, load_workbook
from scripts.build_customer_process360_ontology import parse_package, build, sha


def package(path, *, view='id, amount, NULL::text AS missing', ddl=None):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('部署包/02_建表_主键_注释.sql', ddl or '''CREATE TABLE ded_public.source (
 id text NOT NULL,
 amount numeric(20,6) NULL,
 CONSTRAINT source_pk PRIMARY KEY (id)
);
''')
        z.writestr('部署包/06_兼容视图.sql', f'CREATE VIEW ywln_crm.old AS SELECT {view} FROM ded_public.source;')
        z.writestr('部署包/04_外键.sql', '')
    return path


def inputs(tmp_path):
    wb=Workbook();wb.remove(wb.active)
    data={
        '逻辑实体映射':[['逻辑实体编码','逻辑实体名称','关联物理表'],['LE000001','测试','ywln.old']],
        '业务属性映射':[['逻辑实体编码','业务属性编码','来源表名','来源字段'],
                       ['LE000001','AT0000001','ywln.old','id'],
                       ['LE000001','AT0000002','ywln.old','missing']],
        '业务属性':[['逻辑实体编码','业务属性编码','业务属性名称','数据类型'],
                    ['LE000001','AT0000001','ID','字符串'],['LE000001','AT0000002','缺少字段','字符串']],
        '指标':[['指标编码','指标名称','来源业务属性','计算公式','执行许可'],
                ['M0001','受影响指标','LE000001.AT0000002','COUNT(ID)','原许可不变']],
        '实体关系':[['关系编码','源逻辑实体编码','源关联属性编码','目标逻辑实体编码','目标关联属性编码']],
        '闭环演算':[['场景编码','样例公式'],['SC01','=1+1']],
    }
    for name, values in data.items():
        ws=wb.create_sheet(name)
        for row in values:ws.append(row)
    source=tmp_path/'source.xlsx';wb.save(source)
    base=tmp_path/'base.json';base.write_text(json.dumps(dict(schema='process360.catalog.v1',catalogId='base',
        version='V3.1',sops=[],sheets={},summary={},source=dict(model={},design={}))))
    return source,base


def test_parse_types_pk_and_null_placeholder(tmp_path):
    model=parse_package(package(tmp_path/'input.zip'))
    assert model['tables']['ded_public.source']['columns']['amount']['type']=='numeric(20,6)'
    assert model['tables']['ded_public.source']['primaryKey']==['id']
    assert model['aliases']['old']['fields']['missing'] is None


def test_unsupported_expression_is_not_guessed(tmp_path):
    with pytest.raises(ValueError,match='Unsupported compatibility expression'):
        parse_package(package(tmp_path/'input.zip',view='id, amount * 100 AS total'))


def test_unknown_physical_column_rejected(tmp_path):
    with pytest.raises(ValueError,match='View column absent'):
        parse_package(package(tmp_path/'input.zip',view='id, nonexistent AS amount'))


def test_customer_build_preserves_original_and_does_not_treat_null_as_physical(tmp_path):
    source,base=inputs(tmp_path); original=sha(source)
    output=tmp_path/'delivery'
    report=build(source,package(tmp_path/'input.zip'),output,base)
    assert sha(source)==original
    assert report['mappedAttributes']==1
    assert report['liveDatabaseVerified'] is False
    wb=load_workbook(next(output.glob('*.xlsx')),data_only=False)
    ws=wb['业务属性映射'];headers={c.value:c.column for c in ws[1]}
    assert ws.cell(2,headers['来源表名']).value=='ded_public.source'
    assert ws.cell(3,headers['来源字段']).value is None
    assert 'blocked' in ws.cell(3,headers['客户接入状态']).value
    assert wb['闭环演算']['B2'].value=='=1+1'
    metrics=wb['指标'];headers={c.value:c.column for c in metrics[1]}
    assert metrics.cell(2,headers['计算公式']).value=='COUNT(ID)'
    assert metrics.cell(2,headers['执行许可']).value=='原许可不变'
    assert 'blocked' in metrics.cell(2,headers['客户结构状态']).value
    manifest=json.loads((output/'manifest.json').read_text())
    for name,digest in manifest['files'].items():assert sha(output/name)==digest
    with pytest.raises(ValueError,match='Output already exists'):
        build(source,tmp_path/'input.zip',output,base)


def test_untouched_formula_cache_is_retained_in_runtime_catalog(tmp_path):
    import io
    source,base=inputs(tmp_path)
    content=io.BytesIO()
    replaced=False
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(content,'w') as updated:
        for item in original.infolist():
            value=original.read(item.filename)
            if item.filename.startswith('xl/worksheets/') and b'<f>1+1</f><v></v>' in value:
                value=value.replace(b'<f>1+1</f><v></v>',b'<f>1+1</f><v>2</v>')
                replaced=True
            updated.writestr(item,value)
    assert replaced
    source.write_bytes(content.getvalue())
    output=tmp_path/'delivery'
    build(source,package(tmp_path/'input.zip'),output,base)
    result=json.loads((output/'catalog.json').read_text())
    assert result['sheets']['closure_calculation'][0]['样例公式']==2
    assert load_workbook(next(output.glob('*.xlsx')),data_only=False)['闭环演算']['B2'].value=='=1+1'


def test_foreign_key_columns_must_exist(tmp_path):
    path=package(tmp_path/'input.zip')
    with zipfile.ZipFile(path) as z:
        values={name:z.read(name) for name in z.namelist()}
    values['部署包/04_外键.sql']=b'ALTER TABLE ded_public.source ADD CONSTRAINT bad FOREIGN KEY (missing) REFERENCES ded_public.source (id) NOT VALID;'
    with zipfile.ZipFile(path,'w') as z:
        for name,value in values.items():z.writestr(name,value)
    with pytest.raises(ValueError,match='Invalid foreign key'):
        parse_package(path)
