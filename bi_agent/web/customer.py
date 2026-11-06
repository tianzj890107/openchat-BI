"""Cockpit and Process360-only entrypoint. Customer values come from env only."""
from pathlib import Path
import json
import os


class CustomerSurface:
    def __init__(self, app, prefix=''):
        self.app, self.prefix = app, prefix.rstrip('/')

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope['path']
        if self.prefix and (path == self.prefix or path.startswith(self.prefix+'/')):
            path = path[len(self.prefix):] or '/'
        if path in {'/','/cockpit','/cockpit/'}:
            from starlette.responses import RedirectResponse
            return await RedirectResponse(self.prefix+'/cockpit/overview',status_code=307)(scope,receive,send)
        allowed = (path in {'/','/health','/healthz','/api/mcp','/api/mcp/health','/api/mcp/process360'}
                   or path.startswith(('/cockpit/','/api/cockpit/','/api/process360/','/api/mcp/artifacts/',
                                       '/static/cockpit/','/static/vendor/echarts/','/charts/')))
        if not allowed:
            from starlette.responses import JSONResponse
            return await JSONResponse({'detail':'此交付仅提供驾驶舱与Process360 MCP'},status_code=404)(scope,receive,send)
        return await self.app(scope,receive,send)


def prepare():
    from dotenv import load_dotenv
    load_dotenv(override=False)
    required=('TEAM_BASE_URL','TEAM_MODEL','PROCESS360_PG_HOST','PROCESS360_PG_DATABASE',
              'PROCESS360_PG_USER','COCKPIT_AP_BASE_URL','FUXI_CONTROL_BASE_URL')
    missing=[name for name in required if not os.environ.get(name,'').strip()]
    if missing:raise RuntimeError('客户.env缺少必填配置：'+','.join(missing))
    os.environ['ONTOLOGY_BACKEND']='local'
    os.environ['ONTOLOGY_MCP_TOOL_PROFILE']='process360'
    # A wider override must never defeat the dedicated customer whitelist.
    os.environ.pop('ONTOLOGY_MCP_EXPOSED_TOOLS',None)
    for name in ('ONTOLOGY_BASE_URL','DORIS_API_URL','CONVERSATION_SYNC_URL','TASK_ALERT_API_URL'):
        os.environ[name]=''
    if not Path(os.environ.get('PROCESS360_CATALOG_PATH','')).is_file():
        raise RuntimeError('PROCESS360_CATALOG_PATH缺少客户catalog.json')
    target=Path(os.environ.get('COCKPIT_AP_HEADERS_FILE','dataset/customer/ap-headers.json'))
    target.parent.mkdir(parents=True,exist_ok=True)
    headers={}
    for name,header in [('COCKPIT_AP_APP_ID','X-App-Id'),('COCKPIT_AP_AUTHORIZATION','Authorization'),
                        ('COCKPIT_AP_COOKIE','Cookie'),('COCKPIT_AP_APIFOX_TOKEN','apifoxToken'),
                        ('COCKPIT_AP_REFERER','Referer')]:
        if os.environ.get(name):headers[header]=os.environ[name]
    if any('\r' in value or '\n' in value for value in headers.values()):
        raise RuntimeError('AP认证配置包含非法换行')
    target.write_text(json.dumps(headers,ensure_ascii=False));target.chmod(0o600)
    os.environ['COCKPIT_AP_HEADERS_FILE']=str(target.resolve())


def main():
    prepare()
    from .app import app, configure, set_runtime_port
    cwd=Path.cwd()
    configure(str(cwd),'','',use_doris=False,process360_only=True)
    port=int(os.environ.get('APP_PORT','8080'))
    set_runtime_port(port)
    import uvicorn
    uvicorn.run(CustomerSurface(app,os.environ.get('APP_ROOT_PATH','')),
                host=os.environ.get('APP_HOST','0.0.0.0'),port=port)


if __name__=='__main__':main()
