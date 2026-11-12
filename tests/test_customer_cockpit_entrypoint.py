from pathlib import Path
from hashlib import sha256
import json
import os
import shutil
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from bi_agent.web.customer import CustomerSurface, prepare


CATALOG=Path(__file__).resolve().parents[1]/'dataset/process360/ywln-v3.1/catalog.json'


def test_customer_surface_blocks_other_tool_profiles_and_workbench():
    async def ready(request):return JSONResponse({'ok':True})
    app=Starlette(routes=[Route('/healthz',ready),Route('/api/mcp/process360',ready),Route('/api/mcp/general',ready),Route('/workbench',ready)])
    client=TestClient(CustomerSurface(app))
    assert client.get('/healthz').status_code==200
    assert client.get('/api/mcp/process360').status_code==200
    assert client.get('/api/mcp/general').status_code==404
    assert client.get('/api/mcp/tasks').status_code==404
    assert client.get('/workbench').status_code==404
    assert client.get('/',follow_redirects=False).headers['location']=='/cockpit/overview'
    assert TestClient(CustomerSurface(app,'/api/ontology-agentic-analytics')).get('/api/ontology-agentic-analytics/api/mcp/general').status_code==404


def test_customer_prepare_uses_env_and_prevents_remote_fallback(tmp_path,monkeypatch):
    for name in ('TEAM_BASE_URL','TEAM_MODEL','PROCESS360_PG_HOST','PROCESS360_PG_DATABASE','PROCESS360_PG_USER','COCKPIT_AP_BASE_URL','FUXI_CONTROL_BASE_URL'):
        monkeypatch.setenv(name,'test-only')
    catalog=tmp_path/'catalog.json';shutil.copyfile(CATALOG,catalog)
    target=tmp_path/'headers.json'
    monkeypatch.setenv('PROCESS360_BUILTIN_CATALOG_PATH',str(tmp_path/'missing'/'catalog.json'))
    monkeypatch.setenv('PROCESS360_CATALOG_PATH',str(catalog))
    monkeypatch.setenv('COCKPIT_AP_HEADERS_FILE',str(target))
    monkeypatch.setenv('COCKPIT_AP_APP_ID','app-test')
    monkeypatch.setenv('ONTOLOGY_MCP_EXPOSED_TOOLS','MetricFactQuery')
    monkeypatch.setenv('ONTOLOGY_BASE_URL','http://forbidden.invalid')
    monkeypatch.setenv('DORIS_API_URL','http://forbidden.invalid')
    monkeypatch.chdir(tmp_path)
    prepare()
    assert os.environ['ONTOLOGY_MCP_TOOL_PROFILE']=='process360'
    assert 'ONTOLOGY_MCP_EXPOSED_TOOLS' not in os.environ
    assert os.environ['ONTOLOGY_BASE_URL']==os.environ['DORIS_API_URL']==''
    assert json.loads(target.read_text())['X-App-Id']=='app-test'
    assert target.stat().st_mode & 0o777==0o600
    assert os.environ['PROCESS360_CATALOG_SOURCE']=='env'


def test_customer_prepare_prefers_builtin_ontology_and_verifies_manifest(tmp_path,monkeypatch):
    for name in ('TEAM_BASE_URL','TEAM_MODEL','PROCESS360_PG_HOST','PROCESS360_PG_DATABASE','PROCESS360_PG_USER','COCKPIT_AP_BASE_URL','FUXI_CONTROL_BASE_URL'):
        monkeypatch.setenv(name,'test-only')
    builtin=tmp_path/'builtin';builtin.mkdir()
    catalog=builtin/'catalog.json';shutil.copyfile(CATALOG,catalog)
    digest=sha256(catalog.read_bytes()).hexdigest()
    (builtin/'manifest.json').write_text(json.dumps({'files':{'catalog.json':digest}}))
    external=tmp_path/'external.json';shutil.copyfile(CATALOG,external)
    target=tmp_path/'headers.json'
    monkeypatch.setenv('PROCESS360_BUILTIN_CATALOG_PATH',str(catalog))
    monkeypatch.setenv('PROCESS360_CATALOG_PATH',str(external))
    monkeypatch.setenv('COCKPIT_AP_HEADERS_FILE',str(target))
    monkeypatch.chdir(tmp_path)
    prepare()
    assert os.environ['PROCESS360_CATALOG_PATH']==str(catalog.resolve())
    assert os.environ['PROCESS360_CATALOG_SOURCE']=='builtin'
    assert os.environ['PROCESS360_CATALOG_SHA256']==digest


def test_customer_prepare_rejects_builtin_ontology_without_manifest(tmp_path,monkeypatch):
    for name in ('TEAM_BASE_URL','TEAM_MODEL','PROCESS360_PG_HOST','PROCESS360_PG_DATABASE','PROCESS360_PG_USER','COCKPIT_AP_BASE_URL','FUXI_CONTROL_BASE_URL'):
        monkeypatch.setenv(name,'test-only')
    builtin=tmp_path/'builtin';builtin.mkdir()
    catalog=builtin/'catalog.json';shutil.copyfile(CATALOG,catalog)
    monkeypatch.setenv('PROCESS360_BUILTIN_CATALOG_PATH',str(catalog))
    monkeypatch.setenv('PROCESS360_CATALOG_PATH','')
    monkeypatch.setenv('COCKPIT_AP_HEADERS_FILE',str(tmp_path/'headers.json'))
    monkeypatch.chdir(tmp_path)
    try:
        prepare()
    except RuntimeError as exc:
        assert 'manifest.json' in str(exc)
    else:
        raise AssertionError('builtin ontology without manifest must fail')


def test_customer_prepare_rejects_builtin_ontology_hash_mismatch(tmp_path,monkeypatch):
    for name in ('TEAM_BASE_URL','TEAM_MODEL','PROCESS360_PG_HOST','PROCESS360_PG_DATABASE','PROCESS360_PG_USER','COCKPIT_AP_BASE_URL','FUXI_CONTROL_BASE_URL'):
        monkeypatch.setenv(name,'test-only')
    builtin=tmp_path/'builtin';builtin.mkdir()
    catalog=builtin/'catalog.json';shutil.copyfile(CATALOG,catalog)
    (builtin/'manifest.json').write_text(json.dumps({'files':{'catalog.json':'0'*64}}))
    monkeypatch.setenv('PROCESS360_BUILTIN_CATALOG_PATH',str(catalog))
    monkeypatch.setenv('PROCESS360_CATALOG_PATH','')
    monkeypatch.setenv('COCKPIT_AP_HEADERS_FILE',str(tmp_path/'headers.json'))
    monkeypatch.chdir(tmp_path)
    try:
        prepare()
    except RuntimeError as exc:
        assert 'manifest哈希不一致' in str(exc)
    else:
        raise AssertionError('builtin ontology hash mismatch must fail')
