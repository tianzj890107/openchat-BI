"""MCP protocol adapter for delegated tasks, separate from basic tool profiles."""
import json
from .mcp_endpoint import McpRuntime, _with_artifact_url


class TaskMcpRuntime(McpRuntime):
    def __init__(self, service_factory):
        # Reuse protocol session handling, not the source/tool runtime.
        import threading
        self.service_factory = service_factory
        self._sessions = {}
        self._lock = threading.RLock()

    def list_tools(self):
        def tool(name, description, properties, required):
            return dict(name=name, description=description, inputSchema=dict(
                type='object',properties=properties,required=required,additionalProperties=False))
        refs = dict(task_id=dict(type='string'),task_token=dict(type='string'))
        return [
            tool('AnalysisTaskSubmit','委托 Analytics 按工作台相同执行链完成分析；不自动派发业务动作。',dict(question=dict(type='string',minLength=1,maxLength=32000)),['question']),
            tool('AnalysisTaskGet','查询任务状态及分页事件；task_token 是私有访问凭据，不放入报告或链接。',dict(**refs,after=dict(type='integer',minimum=0),limit=dict(type='integer',minimum=1,maximum=200)),list(refs)),
            tool('AnalysisTaskCancel','请求协作取消，不删除任务与结果。',refs,list(refs)),
        ]

    def call_tool(self, name, arguments, base_url='', **kwargs):
        allowed = {tool['name']:tool['inputSchema'] for tool in self.list_tools()}
        if name not in allowed:
            raise PermissionError('tool_not_allowed')
        schema = allowed[name]
        if set(arguments)-set(schema['properties']) or any(k not in arguments for k in schema['required']):
            raise ValueError('invalid task arguments')
        service = self.service_factory()
        if name == 'AnalysisTaskSubmit':
            result = service.submit(arguments['question'])
        elif name == 'AnalysisTaskCancel':
            result = service.cancel(arguments['task_id'],arguments['task_token'])
        else:
            result = service.get(arguments['task_id'],arguments['task_token'],after=arguments.get('after',0),limit=arguments.get('limit',100))
        if name == 'AnalysisTaskGet':
            for item in result['events']:
                event = item['event']
                if event.get('type') == 'tool_result' and event.get('name') == 'CanvasGenerate' and isinstance(event.get('output'), str):
                    event['output'] = _with_artifact_url(event['output'], service.cwd, base_url) if hasattr(service, 'cwd') else event['output']
        return json.dumps(result,ensure_ascii=False)

    def handle(self, payload, session_id, base_url):
        sid, response = super().handle(payload,session_id,base_url)
        if payload.get('method')=='initialize' and response and 'result' in response:
            response['result']['instructions']='使用 AnalysisTaskSubmit 委托分析，保存私有 task_token；使用 AnalysisTaskGet 分页读取结果，遇 needs_input 向用户披露缺口。AnalysisTaskCancel 只取消执行，不删除数据。'
        return sid,response
