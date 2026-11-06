import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from openpyxl import Workbook
from bi_agent.workbench_pg import SOURCE_VALUE, config, preset, make_executor, normalize_store
from bi_agent.process360.db import QueryResult, ensure_read_only
from bi_agent.ontology.store import OntologyStore


@pytest.fixture
def configured(tmp_path,monkeypatch):
    env={'HOST':'pg.test','PORT':'5432','DATABASE':'db_test','SCHEMA':'ywln_crm',
         'USER':'readonly_test','PASSWORD':'secret_test','ONTOLOGY_SCHEMA_ALIAS':'ywln'}
    for key,value in env.items():monkeypatch.setenv('WORKBENCH_PG_'+key,value)
    wb=Workbook();wb.remove(wb.active)
    sheets={'术语':[['术语编码','术语名称']], '业务对象':[['业务对象编码','业务对象名称'],['BO1','订单']],
            '逻辑实体':[['业务对象编码','逻辑实体编码','逻辑实体名称'],['BO1','LE1','订单']],
            '业务属性':[['逻辑实体编码','业务属性编码','业务属性名称','业务属性英文名称'],['LE1','AT1','主键','old_id']],
            '实体关系':[['关系编码','源逻辑实体编码','目标逻辑实体编码','源关联属性英文名','目标关联属性英文名'],['REL1','LE1','LE1','id','parent_id']],
            '指标':[['指标编码','指标名称']], '活动':[['活动编码','活动名称']], '业务规则':[['规则编码']],
            '指标维度矩阵':[['指标编码']], '逻辑实体映射':[['逻辑实体编码','关联物理表'],['LE1','ywln.orders']],
            '业务属性映射':[['业务属性编码','来源字段'],['AT1','id']]}
    for name,data in sheets.items():
        ws=wb.create_sheet(name)
        for row in data:ws.append(row)
    path=tmp_path/'local.xlsx';wb.save(path)
    monkeypatch.setenv('WORKBENCH_LOCAL_ONTOLOGY_PATH',str(path))
    return tmp_path,path


def test_independent_config_never_inherits_customer_process360(configured,monkeypatch):
    monkeypatch.setenv('PROCESS360_PG_HOST','customer.invalid')
    assert config().host=='pg.test'
    monkeypatch.delenv('WORKBENCH_PG_HOST')
    with pytest.raises(ValueError,match='未配置完整'):preset(configured[0])


def test_workbook_mappings_relations_and_runtime_schema_alias(configured):
    root,path=configured
    before=path.read_bytes()
    store=OntologyStore.from_xlsx(path)
    assert store.logical_entities['LE1'].physical_table=='ywln.orders'
    assert store.attributes['AT1'].english=='id'
    assert store.relations['REL1'].source_code=='LE1'
    assert store.relations['REL1'].foreign_key=='id = parent_id'
    normalized=normalize_store(store,'ywln_crm')
    assert normalized.logical_entities['LE1'].physical_table=='ywln_crm.orders'
    assert store.logical_entities['LE1'].physical_table=='ywln.orders'
    assert path.read_bytes()==before


class FakeDB:
    def __init__(self):
        self.config=SimpleNamespace(schema='ywln_crm',password='secret_test')
        self.calls=[]
    def run(self,sql,params=None,**kw):
        ensure_read_only(sql);self.calls.append((sql,params,kw))
        return QueryResult(['amount'],[{'amount':42}],1,False)


def test_all_sql_executors_use_pg_without_sqlite_or_doris(configured):
    from bi_agent.tools import build_source_executors
    db=FakeDB()
    with patch('bi_agent.workbench_pg.database',return_value=db),patch('sqlite3.connect',side_effect=AssertionError('SQLite forbidden')):
        executors=build_source_executors(OntologyStore(),SOURCE_VALUE)
        assert 'PostgreSQL' in executors['Ontology-FactQuery']({'sql':'SELECT 42 AS amount'},'')
        executors['ListTables']({},'')
        executors['DescribeTable']({'table':'orders'},'')
    assert len(db.calls)==3
    assert db.calls[1][1]==('ywln_crm',)
    assert db.calls[2][1]==('ywln_crm','orders')


@pytest.mark.parametrize('sql',['DELETE FROM orders','SELECT 1; SELECT 2','SELECT pg_read_file(\'/etc/passwd\')','PRAGMA table_info(orders)'])
def test_pg_rejects_writes_multi_statement_and_server_file_reads(sql):
    assert '失败' in make_executor('fact',FakeDB())({'sql':sql},'')


def test_describe_rejects_untrusted_identifier_and_other_schema():
    db=FakeDB()
    for table in ('orders;DROP TABLE orders','other.orders'):
        assert '失败' in make_executor('describe',db)({'table':table},'')
    assert not db.calls


def test_source_option_and_atomic_local_excel_pair(configured,monkeypatch):
    from bi_agent.web import app as web
    root,path=configured
    monkeypatch.setattr(web.STATE,'cwd',str(root))
    source=web._snapshot_source()
    source.remote_ontology=None;source.ontology_backend='local';source.ontology_path=''
    source.ontology_store=OntologyStore();source.use_doris=False
    monkeypatch.setattr(web,'_source_for_session',lambda sid:source)
    payload=json.loads(web.get_sources_endpoint().body)
    assert SOURCE_VALUE in payload['database']['options']
    assert path.name in payload['ontology']['options']
    with patch.object(web,'_remote_repository_catalog',side_effect=AssertionError('remote ontology forbidden')):
        result=web._put_sources_endpoint_impl(web.SourcesUpdate(database=SOURCE_VALUE),source,register_global=False)
    assert json.loads(result.body)['database']==SOURCE_VALUE
    assert source.remote_ontology is None and source.ontology_backend=='local'
    assert source.ontology_store.logical_entities['LE1'].physical_table=='ywln_crm.orders'
    assert not source.use_doris


def test_switch_does_not_mutate_other_sessions_ontology(configured,monkeypatch):
    from bi_agent.web import app as web
    root,path=configured
    monkeypatch.setattr(web.STATE,'cwd',str(root))
    shared=OntologyStore.from_xlsx(path)
    first=web._snapshot_source();second=web._snapshot_source()
    for source in (first,second):
        source.remote_ontology=None;source.ontology_backend='local';source.ontology_path=str(path)
        source.ontology_store=shared;source.use_doris=False;source.db_path='old.db'
    web._put_sources_endpoint_impl(web.SourcesUpdate(database=SOURCE_VALUE),first,register_global=False)
    assert first.ontology_store is not second.ontology_store
    assert first.ontology_store.logical_entities['LE1'].physical_table=='ywln_crm.orders'
    assert second.ontology_store.logical_entities['LE1'].physical_table=='ywln.orders'
    assert second.db_path=='old.db'


def test_cli_can_boot_local_excel_pg_without_platform(configured,monkeypatch):
    from bi_agent.web import app as web
    from bi_agent.web import __main__ as cli
    import sys,os,uvicorn
    root,path=configured
    monkeypatch.setenv('ONTOLOGY_BACKEND','production')
    monkeypatch.setattr(sys,'argv',['bi-agent-web','--cwd',str(root),'--db','postgres'])
    with patch.object(web,'configure') as configure,patch.object(web,'set_runtime_port'),patch.object(uvicorn,'run'):
        cli.main()
    assert os.environ['ONTOLOGY_BACKEND']=='local'
    assert configure.call_args.kwargs['db_path']==SOURCE_VALUE
    assert configure.call_args.kwargs['ontology_path']==str(path)
    assert configure.call_args.kwargs['use_doris'] is False
