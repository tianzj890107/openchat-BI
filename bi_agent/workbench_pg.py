"""One explicit Workbench preset: local Excel + read-only PostgreSQL.

Independent WORKBENCH_PG_* credentials intentionally never inherit customer
Process360 settings. Each executor freezes its connection at construction.
"""
from pathlib import Path
from copy import deepcopy
import os
import re
import json

from .process360.db import DatabaseConfig, PostgresDatabase, DatabaseQueryError, DatabaseUnavailable

SOURCE_VALUE = 'PostgreSQL · ywln_crm'


def config():
    def number(key, default, low, high):
        try:value=int(os.environ.get('WORKBENCH_PG_'+key,str(default)))
        except ValueError:raise ValueError('WORKBENCH_PG_'+key+'不是有效整数') from None
        if not low<=value<=high:raise ValueError('WORKBENCH_PG_'+key+'超出范围')
        return value
    schema=os.environ.get('WORKBENCH_PG_SCHEMA','').strip()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',schema):raise ValueError('缺少或无效WORKBENCH_PG_SCHEMA')
    return DatabaseConfig(host=os.environ.get('WORKBENCH_PG_HOST','').strip(),
        port=number('PORT',5432,1,65535),database=os.environ.get('WORKBENCH_PG_DATABASE','').strip(),
        user=os.environ.get('WORKBENCH_PG_USER','').strip(),password=os.environ.get('WORKBENCH_PG_PASSWORD',''),
        schema=schema,connect_timeout=number('CONNECT_TIMEOUT',5,1,30),
        statement_timeout_ms=number('STATEMENT_TIMEOUT_MS',15000,1000,120000))


def preset(cwd):
    cfg=config()
    if not cfg.ready()[0]:raise ValueError('未配置完整WORKBENCH_PG_HOST/DATABASE/USER')
    raw=os.environ.get('WORKBENCH_LOCAL_ONTOLOGY_PATH','').strip()
    if not raw:raise ValueError('缺少WORKBENCH_LOCAL_ONTOLOGY_PATH')
    root=Path(cwd).resolve();path=Path(raw)
    path=(path if path.is_absolute() else root/path).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower()!='.xlsx':
        raise ValueError('本地Excel本体必须是项目内已存在的.xlsx文件')
    return cfg,path


def normalize_store(store,schema):
    """Resolve an explicit workbook schema alias without editing the workbook."""
    alias=os.environ.get('WORKBENCH_PG_ONTOLOGY_SCHEMA_ALIAS','').strip()
    if not alias or alias==schema:return store
    result=deepcopy(store)
    for group in (result.logical_entities,result.business_objects):
        for entity in group.values():
            if entity.physical_table.startswith(alias+'.'):
                entity.physical_table=schema+entity.physical_table[len(alias):]
    result._le_by_table={le.physical_table:le.code for le in result.logical_entities.values() if le.physical_table}
    return result


class WorkbenchDatabase(PostgresDatabase):
    def _connect(self):
        connection=super()._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("select set_config('search_path', %s, true)",
                               ('"'+self.config.schema+'",pg_catalog',))
        except Exception:
            connection.close()
            raise DatabaseUnavailable('无法设置PostgreSQL只读schema') from None
        return connection


def database():
    return WorkbenchDatabase(config())


def make_executor(kind, db=None):
    db=db or database()
    schema=db.config.schema
    def run(params,cwd):
        from .tools.sql_tools import _format_rows, MAX_RESULT_ROWS
        from .reliability import Provenance, normalize_query_result
        try:
            limit=max(1,min(int(params.get('limit') or 100),MAX_RESULT_ROWS))
            if kind=='fact':
                sql=str(params.get('sql') or '').strip()
                if re.search(r'\b(pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|pg_sleep|pg_terminate_backend|pg_cancel_backend|set_config|nextval|setval|lo_export|lo_import|dblink)"?\s*\(',sql,re.I):
                    raise ValueError('不允许带副作用或读取服务器文件的函数')
                result=db.run(sql,max_rows=limit)
            elif kind=='tables':
                sql='SELECT table_schema,table_name,table_type FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name'
                result=db.run(sql,(schema,),max_rows=1000)
            else:
                raw=str(params.get('table') or '').strip()
                match=re.fullmatch(r'(?:("?[A-Za-z_][A-Za-z0-9_]*"?)\.)?("?[A-Za-z_][A-Za-z0-9_]*"?)',raw)
                if not match:raise ValueError('表名格式无效')
                selected=(match[1] or schema).strip('"');table=match[2].strip('"')
                if selected!=schema:raise ValueError('只能查看当前配置schema的表结构')
                sql='SELECT column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position'
                result=db.run(sql,(schema,table),max_rows=1000)
            columns=result.columns;values=[tuple(row.get(col) for col in columns) for row in result.rows]
            if kind!='fact':return f'PostgreSQL schema: {schema}\n'+_format_rows(columns,values,1000)+ ('\n结果已截断' if result.truncated else '')
            metadata=normalize_query_result({'columns':columns,'rows':values},scope={'query':sql},
                semantic={'columns':columns},provenance=Provenance(source='PostgreSQL',query=sql))
            return 'SQL: '+sql+'\n\n'+_format_rows(columns,values,limit)+'\n\n[RESULT_METADATA]\n'+json.dumps(metadata.to_dict(),ensure_ascii=False,default=str)
        except (ValueError,DatabaseQueryError,DatabaseUnavailable) as exc:
            message=str(exc)
            if db.config.password:message=message.replace(db.config.password,'<redacted>')
            return 'PostgreSQL只读查询失败：'+message[:400]
    return run
