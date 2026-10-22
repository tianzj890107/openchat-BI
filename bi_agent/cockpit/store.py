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
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL,
              body TEXT NOT NULL, updated REAL NOT NULL);
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
            if item["status"] in {"completed","cancelled","failed","interrupted"}: return item
            item.update(changes,updatedAt=time.time())
            db.execute("UPDATE analyses SET body=?,status=?,updated=? WHERE id=?",(json.dumps(item,ensure_ascii=False),item["status"],item["updatedAt"],aid))
        return item

    def list_analyses(self, scope=None, limit=50):
        with self.db() as db:
            rows=db.execute("SELECT body FROM analyses "+("WHERE scope=? " if scope else "")+"ORDER BY updated DESC LIMIT ?",(scope,limit) if scope else (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

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
