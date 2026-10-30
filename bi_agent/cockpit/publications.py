"""Stable filter identities and persistent last-successful card publications."""
import hashlib
import json
from pathlib import Path
from .cards import CONTRACT


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def config_version():
    path=Path(__file__).parents[1]/'web/static/cockpit/metadata/runtime.json'
    return hashlib.sha256(path.read_bytes()).hexdigest()[:20]


def view_scope(context):
    return digest({k:context.get(k) for k in ('id','engine','page','chartSnapshotId','dataSource','dataIdentity')} | {'config':config_version(),'contract':CONTRACT})


def legacy_view_scope(context):
    """Read-only key for AP cards written before dataSource entered the scope."""
    return digest({k:context.get(k) for k in ('id','engine','page','chartSnapshotId','dataIdentity')} | {'config':config_version(),'contract':CONTRACT})


def publication_scope(context):
    # Receipt IDs and response values change on every fetch. Neither is a filter.
    value={k:context.get(k) for k in ('id','engine','page','stage','source','period','department','filters','repositoryId','chartSnapshotId','dataSource','dataIdentity','clarifications','baselineAnalysisId')}
    value['chartQueries']=sorted({json.dumps(json.loads(q),sort_keys=True,ensure_ascii=False,separators=(',',':')) for q in context.get('chartQueries',[])})
    # A fallback registry change (new metric, fixed口径) must never reuse a card
    # computed from the previous mapping.
    value['fallback']=context.get('fallbackVersion','') or ''
    value.update(config=config_version(),contract=CONTRACT)
    return digest(value)


def legacy_publication_scope(context):
    """Read-only AP publication key used before dataSource entered the scope."""
    value={k:context.get(k) for k in ('id','engine','page','stage','source','period','department','filters','repositoryId','chartSnapshotId','dataIdentity','clarifications','baselineAnalysisId')}
    value['chartQueries']=sorted({json.dumps(json.loads(q),sort_keys=True,ensure_ascii=False,separators=(',',':')) for q in context.get('chartQueries',[])})
    value.update(config=config_version(),contract=CONTRACT)
    return digest(value)
