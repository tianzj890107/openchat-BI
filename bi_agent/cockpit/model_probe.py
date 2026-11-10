"""Small explicit connectivity/tool-roundtrip probe; no AP, SQL or history writes."""
import json
import time
import re
from ..llm.registry import get_model
from ..llm.runtime_config import get_config, request_config

TOOL='CockpitModelConnectivityProbe'
SCHEMA={'name':TOOL,'description':'Return a fixed connectivity acknowledgement. No external access.',
        'input_schema':{'type':'object','properties':{},'additionalProperties':False}}


def probe(model_key=None, tool_roundtrip=True):
    from open_claude.tools import register_tool
    from ..concurrency import get_llm_limiter
    from ..llm import provider_team, provider_deepseek
    key=model_key or get_config().model_key
    model=get_model(key)
    if not model:raise ValueError('未知模型配置')
    provider=model['provider']
    if provider not in {'team','deepseek'}:raise ValueError('该诊断接口仅支持当前部署使用的 team / deepseek 兼容接口')
    register_tool(SCHEMA,lambda *_:json.dumps({'ok':True}))
    started=time.monotonic();calls=0;phase='connect';connected=False;token=None
    def run(messages,tools):
        nonlocal calls
        calls+=1
        adapter=provider_team if provider=='team' else provider_deepseek
        events=list(adapter.stream(model_id=model['model_id'],messages=messages,
            system_prompt='Connectivity probe only. Follow the user request. Do not access business data.',
            allowed_tools=tools,max_tokens=2048,temperature=0,thinking=False))
        errors=[e.get('error','') for e in events if e.get('type')=='error']
        if errors:raise RuntimeError(errors[-1])
        blocks=[dict(type='thinking',thinking=e.get('text','')) for e in events if e.get('type')=='thinking_block']
        text=''.join(e.get('text','') for e in events if e.get('type')=='text_delta')
        if text:blocks.append(dict(type='text',text=text))
        blocks.extend(dict(type='tool_use',id=e['id'],name=e['name'],input=e.get('input',{})) for e in events if e.get('type')=='tool_use_end')
        if not any(e.get('type')=='message_end' for e in events):raise RuntimeError('Empty model response')
        return blocks
    try:
        token=get_llm_limiter().acquire(timeout=1)
        with request_config(thinking=False,request_timeout=20):
            messages=[dict(role='user',content=('Call CockpitModelConnectivityProbe with {} exactly once.' if tool_roundtrip else 'Reply only OK.'))]
            blocks=run(messages,[TOOL] if tool_roundtrip else [])
            connected=True
            if tool_roundtrip:
                phase='tool_roundtrip'
                tools=[b for b in blocks if b['type']=='tool_use']
                if not tools or any(t['name']!=TOOL for t in tools):raise RuntimeError('Probe tool not called')
                messages.extend([dict(role='assistant',content=blocks),dict(role='user',content=[dict(type='tool_result',tool_use_id=t['id'],content='{"ok":true,"probe":"pong"}') for t in tools])])
                # No tools exposed: this exercises reasoning replay on the
                # final response as well as the tool-bearing request.
                final=run(messages,[])
                if not any(b['type']=='text' and b['text'].strip() for b in final):raise RuntimeError('Empty final response')
            elif not any(b['type']=='text' and b['text'].strip() for b in blocks):raise RuntimeError('Empty final response')
        result=dict(ok=True,connected=True,toolRoundtrip=bool(tool_roundtrip),phase='completed',code='OK')
    except Exception as exc:
        text=str(exc).lower()
        code=('MODEL_BUSY' if type(exc).__name__=='ResourceTimeout' else
              'MODEL_NOT_CONFIGURED' if any(x in text for x in ('no team_api_key','no deepseek api key')) else
              'MODEL_AUTH_FAILED' if any(x in text for x in ('401','403','api key','unauthorized')) else
              'MODEL_REASONING_PROTOCOL' if 'reasoning' in text else
              'MODEL_RATE_LIMITED' if any(x in text for x in ('429','quota','rate limit')) else
              'MODEL_TIMEOUT' if any(x in text for x in ('timeout','timed out')) else
              'MODEL_PROBE_TOOL_NOT_CALLED' if 'tool not called' in text else
              'MODEL_EMPTY_RESPONSE' if 'empty' in text else 'MODEL_CONNECTION_FAILED')
        status=re.search(r'(?<!\d)(400|401|403|404|408|429|500|502|503|504)(?!\d)',text)
        result=dict(ok=False,connected=connected,toolRoundtrip=False,phase=phase,code=code,upstreamStatus=int(status[0]) if status else None)
    finally:
        if token:token.release()
    return dict(result,modelKey=key,model=model['model_id'],provider=provider,modelCalls=calls,
                durationSeconds=round(time.monotonic()-started,3))
