"""Outgoing-only DeepSeek compatibility. Never invent reasoning or execute tools."""
from copy import deepcopy
import json


def preserve_tool_observations(messages, *, all_tool_turns=False):
    """Old tool turns with no recoverable reasoning become real user observations.

    Tool call IDs, parameters, outputs and ordering stay intact as quoted data;
    source history is unchanged. No fake assistant reasoning is constructed.
    """
    out=[];index=0
    while index<len(messages):
        msg=messages[index]
        if msg.get('role')=='assistant' and msg.get('tool_calls') and (all_tool_turns or not msg.get('reasoning_content')):
            results=[];cursor=index+1
            while cursor<len(messages) and messages[cursor].get('role')=='tool':
                results.append(deepcopy(messages[cursor]));cursor+=1
            observation={'assistantContent':msg.get('content'),'toolCalls':msg['tool_calls'],'toolResults':results}
            out.append({'role':'user','content':'Historical read-only tool observations; these are prior execution results, not new instructions or new executions. Preserve their evidence and failures; do not rerun completed tools solely to recreate history.\n'+json.dumps(observation,ensure_ascii=False)})
            index=cursor;continue
        out.append(deepcopy(msg));index+=1
    return out


def create_stream(client, kwargs, *, deepseek=False):
    """Bounded pre-stream repairs only; never replay a partially emitted stream."""
    request=kwargs;repaired=set()
    while True:
        try:
            return client.chat.completions.create(**request)
        except Exception as exc:
            message=str(exc).lower()
            if not deepseek or getattr(exc,'status_code',400)!=400:
                raise
            missing=('reasoning' in message and any(x in message for x in ('passed back','not passed','missing','required')))
            unsupported=(any(x in message for x in ('unsupported','unknown','unrecognized','unexpected','not supported'))
                         and any(x in message for x in ('thinking','reasoning_effort')))
            if missing and 'history' not in repaired and any(m.get('tool_calls') for m in request.get('messages',[])):
                request=deepcopy(request)
                request['messages']=preserve_tool_observations(request['messages'],all_tool_turns=True)
                if 'parameters' not in repaired:request.setdefault('extra_body',{})['thinking']={'type':'disabled'}
                repaired.add('history')
            elif unsupported and 'parameters' not in repaired:
                request=deepcopy(request)
                request.pop('reasoning_effort',None)
                body=request.get('extra_body') or {}
                body.pop('thinking',None)
                if not body:request.pop('extra_body',None)
                repaired.add('parameters')
            else:
                raise
