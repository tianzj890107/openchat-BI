from pathlib import Path
import json
import os
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from bi_agent.web.customer import CustomerSurface, prepare


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
    catalog=tmp_path/'catalog.json';catalog.write_text('{}')
    target=tmp_path/'headers.json'
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
