"""Append-preserving SQLite history, isolated from conversation storage."""
from __future__ import annotations
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS analyses (
              id TEXT PRIMARY KEY, scope TEXT NOT NULL, body TEXT NOT NULL,
              status TEXT NOT NULL, updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS analysis_scope ON analyses(scope,updated);
            CREATE TABLE IF NOT EXISTS publications (
              scope TEXT PRIMARY KEY, analysis_id TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS publication_views (
              view_key TEXT NOT NULL, stage TEXT NOT NULL, scope TEXT NOT NULL,
              PRIMARY KEY(view_key,stage));
            CREATE TABLE IF NOT EXISTS ap_results (
              id TEXT PRIMARY KEY, identity INTEGER NOT NULL, body TEXT NOT NULL,
              created REAL NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL,
              body TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS page_snapshots (
              id TEXT PRIMARY KEY, scope TEXT NOT NULL, body TEXT NOT NULL, source_time REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS page_snapshot_views (
              scope TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS page_refresh (
              scope TEXT PRIMARY KEY, status TEXT NOT NULL,
              attempt INTEGER NOT NULL DEFAULT 0, next_check REAL NOT NULL,
              lease_until REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
              last_success REAL NOT NULL DEFAULT 0, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS refresh_plans (
              scope TEXT PRIMARY KEY, body TEXT NOT NULL, updated REAL NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def save_ap_result(self, identity, kind, request, response, ttl, connection_id="", auth_scope="", transport=""):
        now = time.time()
        item = dict(id=uuid.uuid4().hex, identity=identity, kind=kind, request=request,
            response=response, createdAt=now, expiresAt=now+ttl, connectionId=connection_id, authScope=auth_scope, transport=transport)
        with self.db() as db:
            db.execute("INSERT INTO ap_results VALUES(?,?,?,?,?)", (item['id'],identity,
                json.dumps(item,ensure_ascii=False),now,now+ttl))
        return item

    def get_ap_result(self, receipt_id, identity, *, allow_expired=False):
        with self.db() as db:
            row = db.execute("SELECT body,expires FROM ap_results WHERE id=? AND identity=?",
                (receipt_id,identity)).fetchone()
        if not row or (not allow_expired and row['expires'] < time.time()):
            return None
        return json.loads(row['body'])

    def publish_page(self, scope, page):
        """Append a complete version and atomically move its pointer; never erase history."""
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT p.source_time FROM page_snapshot_views v JOIN page_snapshots p '
                                 'ON p.id=v.snapshot_id WHERE v.scope=?', (scope,)).fetchone()
            if current and current[0] > page['dataAsOf']:
                return False
            sid = uuid.uuid4().hex
            db.execute('INSERT INTO page_snapshots VALUES(?,?,?,?)',
                       (sid, scope, json.dumps(page, ensure_ascii=False), page['dataAsOf']))
            db.execute('INSERT INTO page_snapshot_views VALUES(?,?) ON CONFLICT(scope) '
                       'DO UPDATE SET snapshot_id=excluded.snapshot_id', (scope, sid))
            if page.get('uiScope') == 'default':
                # A page version carries delivered cards for its stages.  Bind
                # them as view targets in the same transaction so they survive
                # a restart and keep being refreshed without a browser.
                from .publications import view_scope
                for stage, item in (page.get('items') or {}).items():
                    context = (item or {}).get('context') or {}
                    if context.get('engine') != 'main' or context.get('sourceMode') != 'service':
                        continue
                    row = db.execute('SELECT scope FROM analyses WHERE id=?',
                                     (item.get('id'),)).fetchone()
                    if not row:
                        continue
                    db.execute('INSERT INTO publication_views VALUES(?,?,?) '
                               'ON CONFLICT(view_key,stage) DO UPDATE SET scope=excluded.scope',
                               (view_scope(context), stage, row[0]))
        return True

    def published_page(self, scope):
        with self.db() as db:
            row = db.execute('SELECT p.body FROM page_snapshot_views v JOIN page_snapshots p '
                             'ON p.id=v.snapshot_id WHERE v.scope=?', (scope,)).fetchone()
        return json.loads(row[0]) if row else None

    def page_publications(self, limit=500):
        """Current published page body per scope, newest first (append-only history)."""
        with self.db() as db:
            rows = db.execute('SELECT v.scope, p.body, p.source_time FROM page_snapshot_views v '
                              'JOIN page_snapshots p ON p.id=v.snapshot_id '
                              'ORDER BY p.source_time DESC LIMIT ?', (limit,)).fetchall()
        return [(r[0], json.loads(r[1]), r[2]) for r in rows]

    def latest_page(self, identity, page, ui_scope, *, data_identity=None):
        """Newest displayable page for a role/page/filter, even if its config key rotated.

        This is display-only history.  It is never used as fresh evidence: the
        caller must still publish a matching analysis/page before replacing it.
        """
        with self.db() as db:
            row = db.execute("SELECT p.body FROM page_snapshot_views v "
                             "JOIN page_snapshots p ON p.id=v.snapshot_id "
                             "WHERE json_extract(p.body,'$.id')=? AND json_extract(p.body,'$.page')=? "
                             "AND json_extract(p.body,'$.uiScope')=? "
                             "AND (? IS NULL OR json_extract(p.body,'$.dataIdentity')=?) "
                             "ORDER BY p.source_time DESC LIMIT 1",
                             (identity, page, ui_scope, data_identity, data_identity)).fetchone()
        return json.loads(row[0]) if row else None

    def default_publications(self, limit=2000):
        """Scope and version of default-scope publications; bodies load on demand."""
        with self.db() as db:
            rows = db.execute("SELECT v.scope, json_extract(p.body,'$.version'), p.source_time "
                              "FROM page_snapshot_views v JOIN page_snapshots p ON p.id=v.snapshot_id "
                              "WHERE json_extract(p.body,'$.uiScope')='default' "
                              "ORDER BY p.source_time DESC LIMIT ?", (limit,)).fetchall()
        return [(r[0], r[1] or '', r[2]) for r in rows]

    def refresh_state(self, scope):
        with self.db() as db:
            row = db.execute('SELECT scope,status,attempt,next_check,lease_until,last_error,last_success,updated '
                             'FROM page_refresh WHERE scope=?', (scope,)).fetchone()
        return dict(row) if row else None

    def ensure_refresh_state(self, scope, *, next_check=None):
        now = time.time()
        with self.db() as db:
            db.execute('INSERT INTO page_refresh(scope,status,attempt,next_check,lease_until,last_error,last_success,updated) '
                       'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(scope) DO NOTHING',
                       (scope, 'waiting', 0, next_check if next_check is not None else now, 0, '', 0, now))
        return self.refresh_state(scope)

    def set_refresh_state(self, scope, status, *, next_check=None, error=None,
                          attempt=None, last_success=None, lease_until=0):
        now = time.time()
        self.ensure_refresh_state(scope, next_check=now)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT attempt,next_check,last_success FROM page_refresh WHERE scope=?', (scope,)).fetchone()
            attempt = row['attempt'] if attempt is None else int(attempt)
            next_check = row['next_check'] if next_check is None else float(next_check)
            last_success = row['last_success'] if last_success is None else float(last_success)
            db.execute('UPDATE page_refresh SET status=?,attempt=?,next_check=?,lease_until=?,last_error=?,'
                       'last_success=?,updated=? WHERE scope=?',
                       (status, attempt, next_check, float(lease_until or 0), str(error or ''),
                        last_success, now, scope))
        return self.refresh_state(scope)

    def claim_refresh(self, scope, *, now=None, lease=120):
        """Atomically claim one scope; a live lease prevents duplicate workers."""
        now = time.time() if now is None else float(now)
        self.ensure_refresh_state(scope, next_check=now)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,lease_until,attempt,next_check FROM page_refresh WHERE scope=?',
                             (scope,)).fetchone()
            if not row or (row['status'] == 'running' and row['lease_until'] > now):
                return False
            if row['next_check'] > now and row['status'] != 'retry_wait':
                return False
            db.execute('UPDATE page_refresh SET status=?,attempt=?,next_check=?,lease_until=?,updated=? WHERE scope=?',
                       ('running', int(row['attempt']) + 1, now, now + lease, now, scope))
        return True

    def request_refresh(self, scope, *, now=None):
        """Queue a refresh without stealing a running worker's lease."""
        now = time.time() if now is None else float(now)
        self.ensure_refresh_state(scope, next_check=now)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,lease_until,attempt FROM page_refresh WHERE scope=?',
                             (scope,)).fetchone()
            if not row:
                return False
            if row['status'] == 'running' and row['lease_until'] > now:
                # A manual click must not hand the same scope to a second
                # worker; the in-flight run finishes and reschedules itself.
                return False
            db.execute("UPDATE page_refresh SET status='waiting',next_check=?,lease_until=0,updated=? WHERE scope=?",
                       (now, now, scope))
        return True

    def set_refresh_plan(self, scope, body):
        now = time.time()
        with self.db() as db:
            db.execute('INSERT INTO refresh_plans VALUES(?,?,?) ON CONFLICT(scope) '
                       'DO UPDATE SET body=excluded.body,updated=excluded.updated',
                       (scope, json.dumps(body, ensure_ascii=False), now))
        return body

    def refresh_plan(self, scope):
        with self.db() as db:
            row = db.execute('SELECT body FROM refresh_plans WHERE scope=?', (scope,)).fetchone()
        return json.loads(row[0]) if row else None

    def default_views(self, limit=2000):
        """Published default-scope AI cards that need scheduled maintenance.

        Operations and penetration pages are opened as independent AI slots,
        so they may never have a whole-page snapshot.  Their published stage
        cards are still a durable maintenance target.  A component/config
        rotation creates a new view key while the previous key remains as
        append-only history; only the newest card for each business stage is a
        live maintenance target, otherwise the old key would re-run the model
        forever under the rotated key.
        """
        with self.db() as db:
            rows = db.execute('SELECT v.view_key, v.stage, a.body FROM publication_views v '
                              'JOIN publications p ON p.scope=v.scope '
                              'JOIN analyses a ON a.id=p.analysis_id '
                              'ORDER BY a.updated DESC LIMIT ?', (limit,)).fetchall()
        latest = {}
        for row in rows:
            body = json.loads(row[2])
            context = body.get('context') or {}
            key = (context.get('id') or 0, context.get('page') or '', row[1])
            latest.setdefault(key, (row[0], row[1], body))
        return list(latest.values())

    def due_refresh_scopes(self, now=None, limit=20):
        now = time.time() if now is None else float(now)
        with self.db() as db:
            rows = db.execute('SELECT scope FROM page_refresh WHERE next_check<=? AND '
                              '(status!=\'running\' OR lease_until<=?) ORDER BY next_check LIMIT ?',
                              (now, now, limit)).fetchall()
        return [r[0] for r in rows]

    def create_analysis(self, scope, context):
        now=time.time()
        item=dict(id=uuid.uuid4().hex, scope=scope, context=context, status="queued", createdAt=now, updatedAt=now,
            progress="等待分析", result=None, error=None, evidence=None, events=[])
        with self.db() as db:
            db.execute("INSERT INTO analyses VALUES(?,?,?,?,?)",(item["id"],scope,json.dumps(item,ensure_ascii=False),item["status"],now))
        return item

    def get_analysis(self, aid):
        with self.db() as db:
            row=db.execute("SELECT body FROM analyses WHERE id=?",(aid,)).fetchone()
        return json.loads(row[0]) if row else None

    def update_analysis(self, aid, **changes):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT body FROM analyses WHERE id=?",(aid,)).fetchone()
            if not row: raise KeyError(aid)
            item=json.loads(row[0])
            # A late model response can never overwrite cancellation or a terminal result.
            if item["status"] in {"completed","limited","needs_input","cancelled","failed","interrupted"}: return item
            item.update(changes,updatedAt=time.time())
            db.execute("UPDATE analyses SET body=?,status=?,updated=? WHERE id=?",(json.dumps(item,ensure_ascii=False),item["status"],item["updatedAt"],aid))
        return item

    def list_analyses(self, scope=None, limit=50):
        with self.db() as db:
            rows=db.execute("SELECT body FROM analyses "+("WHERE scope=? " if scope else "")+"ORDER BY updated DESC LIMIT ?",(scope,limit) if scope else (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def publish(self, aid):
        from .cards import CONTRACT
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT body FROM analyses WHERE id=?',(aid,)).fetchone()
            if not row:return False
            item=json.loads(row[0])
            if item['status'] not in {'completed','limited'} or (item.get('result') or {}).get('cardContract')!=CONTRACT:return False
            db.execute('INSERT INTO publications VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET analysis_id=excluded.analysis_id,created=excluded.created WHERE excluded.created>=publications.created',
                (item['scope'],aid,item['createdAt']))
            return True

    def published(self, scope):
        with self.db() as db:
            row=db.execute('SELECT a.body FROM publications p JOIN analyses a ON a.id=p.analysis_id WHERE p.scope=?',(scope,)).fetchone()
        return json.loads(row[0]) if row else None

    def bind_view(self, view_key, stage, scope):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT created FROM publications WHERE scope=?',(scope,)).fetchone()
            previous=db.execute('SELECT p.created FROM publication_views v JOIN publications p ON p.scope=v.scope WHERE v.view_key=? AND v.stage=?',(view_key,stage)).fetchone()
            if not current or (previous and previous[0]>current[0]):return False
            db.execute('INSERT INTO publication_views VALUES(?,?,?) ON CONFLICT(view_key,stage) DO UPDATE SET scope=excluded.scope',(view_key,stage,scope))
            return True

    def published_view(self, view_key):
        with self.db() as db:
            rows=db.execute('SELECT v.stage,a.body FROM publication_views v JOIN publications p ON p.scope=v.scope JOIN analyses a ON a.id=p.analysis_id WHERE v.view_key=?',(view_key,)).fetchall()
        return {r[0]:json.loads(r[1]) for r in rows}

    def latest_views(self, identity, engine, page, *, data_identity=None):
        """Newest published card per stage, even if the config key rotated.

        Display-only history: the card keeps its original analysis timestamp and
        is replaced by the scheduler once a card for the current contract is
        published.
        """
        with self.db() as db:
            rows = db.execute(
                "SELECT v.stage, a.body FROM publication_views v "
                "JOIN publications p ON p.scope=v.scope "
                "JOIN analyses a ON a.id=p.analysis_id "
                "WHERE json_extract(a.body,'$.context.id')=? "
                "AND json_extract(a.body,'$.context.engine')=? "
                "AND json_extract(a.body,'$.context.page')=? "
                "AND (? IS NULL OR json_extract(a.body,'$.context.dataIdentity')=?) "
                "ORDER BY a.updated DESC",
                (identity, engine, page, data_identity, data_identity)).fetchall()
        result = {}
        for row in rows:
            result.setdefault(row[0], json.loads(row[1]))
        return result

    def recover(self):
        # Called once when this process opens a store. Preserve records; never delete history.
        for item in self.list_analyses(limit=10000):
            if item["status"] in {"queued","running"}:
                self.update_analysis(item["id"], status="interrupted",progress="服务重新启动，分析已中断，可重试")

    def draft(self, analysis):
        aid=analysis["id"]
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT body FROM tasks WHERE analysis_id=?",(aid,)).fetchone()
            if row:return json.loads(row[0])
            actions=analysis["result"]["recommendations"]
            item=dict(id="POC-"+uuid.uuid4().hex[:10].upper(),analysisId=aid, revision=1,status="draft",simulated=True,
                title=analysis["context"]["stageName"]+"风险改善任务令", context=analysis["context"],
                measures=[dict(id=x["id"], action=x["action"],owner=x["ownerRole"],deadline=f"{x.get('deadlineDays') or 10} 个工作日", acceptance=x["acceptance"]) for x in actions],
                goal="逐项核实并处理当前分析识别的卡点，按证据复核改善情况",feedback="",audit=[dict(action="draft",at=time.time())])
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?)",(item["id"],aid,1,json.dumps(item,ensure_ascii=False),time.time()))
        return item

    def get_task(self, tid):
        with self.db() as db:row=db.execute("SELECT body FROM tasks WHERE id=?",(tid,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_tasks(self):
        with self.db() as db:rows=db.execute("SELECT body FROM tasks ORDER BY updated DESC LIMIT 100").fetchall()
        return [json.loads(r[0]) for r in rows]

    def mutate_task(self, tid, revision, action, payload):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT body FROM tasks WHERE id=?",(tid,)).fetchone()
            if not row: raise KeyError(tid)
            item=json.loads(row[0])
            if item["revision"] != revision:raise ValueError("草稿已更新，请刷新后重试")
            transitions={"issue":("draft","issued"),"accept":("issued","accepted"),"feedback":("accepted","review"),"close":("review","closed")}
            if action=="save":
                if item["status"]!="draft":raise ValueError("仅草稿可编辑")
                item.update(payload)
            else:
                before,after=transitions[action]
                if item["status"]!=before:raise ValueError("当前任务状态不允许此操作")
                if action=="feedback":
                    if not payload.get("feedback","").strip():raise ValueError("请填写处理反馈与证据说明")
                    item["feedback"]=payload["feedback"]
                if action=="close":
                    if not payload.get("feedback","").strip():raise ValueError("请填写验收结论")
                    item["acceptanceResult"]=payload["feedback"]
                item["status"]=after
            item["revision"]+=1
            item["audit"].append(dict(action=action,at=time.time()))
            db.execute("UPDATE tasks SET revision=?,body=?,updated=? WHERE id=?",(item["revision"],json.dumps(item,ensure_ascii=False),time.time(),tid))
        return item
