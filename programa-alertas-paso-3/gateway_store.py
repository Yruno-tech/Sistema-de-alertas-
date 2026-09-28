"""Durable, single-gateway queue. Ambiguous sends are never automatically retried."""
from __future__ import annotations

import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from database import mask_phone

SAFE_TEXT = re.compile(r"^PRUEBA - [A-Za-z0-9 .,;:()/_-]+$")
SMS_INTERVAL = 30
CLAIM_TTL = 60
START_TTL = 120
BATCH_TTL = 600


class QueueError(ValueError):
    pass


class GatewayStore:
    def __init__(self, path: Path, allowed_numbers: list[str], clock=time.time):
        self.path = Path(path)
        self.allowed = frozenset(allowed_numbers)
        self.clock = clock

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS gateway_control (
              id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
              device_id TEXT NOT NULL DEFAULT '', last_seen REAL NOT NULL DEFAULT 0,
              active INTEGER NOT NULL DEFAULT 0, sim_label TEXT NOT NULL DEFAULT '',
              last_start REAL NOT NULL DEFAULT 0);
            INSERT OR IGNORE INTO gateway_control(id) VALUES(1);
            CREATE TABLE IF NOT EXISTS gateway_batches (
              id TEXT PRIMARY KEY, building_id TEXT NOT NULL, office TEXT,
              message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
              created_at REAL NOT NULL, expires_at REAL NOT NULL,
              confirmed_at REAL, preview_sync_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS gateway_jobs (
              id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES gateway_batches(id),
              recipient_id INTEGER NOT NULL, recipient_name TEXT NOT NULL,
              phone TEXT NOT NULL, office TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'DRAFT', device_id TEXT NOT NULL DEFAULT '',
              ticket TEXT NOT NULL DEFAULT '', claimed_at REAL, started_at REAL,
              updated_at REAL NOT NULL, report_revision INTEGER NOT NULL DEFAULT 0,
              delivery_status TEXT NOT NULL DEFAULT 'WAITING', detail TEXT NOT NULL DEFAULT '',
              UNIQUE(batch_id,phone));
            CREATE INDEX IF NOT EXISTS gateway_jobs_status ON gateway_jobs(status,updated_at);
            CREATE TABLE IF NOT EXISTS gateway_audit (
              id INTEGER PRIMARY KEY, at REAL NOT NULL, job_id TEXT, batch_id TEXT,
              action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
            """)

    def _audit(self, db, action, *, job_id=None, batch_id=None, detail=""):
        db.execute("INSERT INTO gateway_audit(at,job_id,batch_id,action,detail) VALUES(?,?,?,?,?)",
                   (self.clock(), job_id, batch_id, action, detail[:250]))

    def _housekeeping(self, db):
        now = self.clock()
        db.execute("""UPDATE gateway_jobs SET status='CANCELLED',detail='Venció la ventana de envío',updated_at=?
          WHERE status IN ('DRAFT','QUEUED','CLAIMED') AND batch_id IN
          (SELECT id FROM gateway_batches WHERE expires_at<?)""", (now, now))
        db.execute("""UPDATE gateway_jobs SET status='CANCELLED',detail='Reserva sin iniciar vencida',updated_at=?
          WHERE status='CLAIMED' AND claimed_at<?""", (now, now-CLAIM_TTL))
        changed = db.execute("""UPDATE gateway_jobs SET status='UNKNOWN',detail='Sin resultado: revisar sin reenviar',updated_at=?
          WHERE status='STARTED' AND started_at<?""", (now, now-START_TTL)).rowcount
        if changed:
            db.execute("UPDATE gateway_control SET enabled=0 WHERE id=1")
            self._audit(db, "PAUSED_UNKNOWN", detail="Sin resultado de envío")
        db.execute("UPDATE gateway_batches SET status='EXPIRED' WHERE status='DRAFT' AND expires_at<?", (now,))
        db.execute("""UPDATE gateway_batches SET status='COMPLETE' WHERE status='QUEUED' AND NOT EXISTS
          (SELECT 1 FROM gateway_jobs j WHERE j.batch_id=gateway_batches.id AND j.status IN ('QUEUED','CLAIMED','STARTED'))""")

    def _bind_device(self, db, device_id):
        if not re.fullmatch(r"[a-f0-9-]{36}", device_id):
            raise QueueError("Identificador del dispositivo inválido")
        control = db.execute("SELECT * FROM gateway_control WHERE id=1").fetchone()
        if control["device_id"] and control["device_id"] != device_id:
            raise QueueError("La credencial ya está vinculada a otro teléfono")
        if not control["device_id"]:
            db.execute("UPDATE gateway_control SET device_id=? WHERE id=1", (device_id,))

    def heartbeat(self, device_id, active, sim_label):
        with self.transaction() as db:
            self._housekeeping(db)
            self._bind_device(db, device_id)
            db.execute("UPDATE gateway_control SET last_seen=?,active=?,sim_label=? WHERE id=1",
                       (self.clock(), int(active), sim_label[:100]))
            enabled = bool(db.execute("SELECT enabled FROM gateway_control WHERE id=1").fetchone()[0])
        return {"enabled": enabled, "mode": "test", "max_recipients": 3, "interval_seconds": SMS_INTERVAL}

    def set_enabled(self, enabled):
        with self.transaction() as db:
            self._housekeeping(db)
            db.execute("UPDATE gateway_control SET enabled=? WHERE id=1", (int(enabled),))
            self._audit(db, "ENABLE" if enabled else "PAUSE")

    def preview(self, building_id, office, message):
        if not SAFE_TEXT.fullmatch(message) or len(message) > 160:
            raise QueueError("El mensaje debe ser de prueba y ocupar un segmento")
        with self.transaction() as db:
            sync = db.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not sync or sync["status"] != "success":
                raise QueueError("Sincronizá la planilla sin errores antes de preparar SMS reales de prueba")
            sql = "SELECT * FROM recipients WHERE active=1 AND sms_enabled=1 AND building_id=?"
            args = [building_id]
            if office is not None:
                sql += " AND office=?"
                args.append(office)
            recipients = db.execute(sql + " ORDER BY id", args).fetchall()
            if not 1 <= len(recipients) <= 3:
                raise QueueError("Seleccioná entre 1 y 3 destinatarios; no se recorta la lista automáticamente")
            if any(r["phone"] not in self.allowed for r in recipients):
                raise QueueError("Hay destinatarios fuera de los números autorizados al configurar el gateway")
            if len({r["phone"] for r in recipients}) != len(recipients):
                raise QueueError("Se detectaron teléfonos repetidos")
            batch_id, now = str(uuid.uuid4()), self.clock()
            db.execute("""INSERT INTO gateway_batches
              (id,building_id,office,message,created_at,expires_at,preview_sync_id) VALUES(?,?,?,?,?,?,?)""",
                       (batch_id, building_id, office, message, now, now+300, sync["id"]))
            for recipient in recipients:
                db.execute("""INSERT INTO gateway_jobs
                  (id,batch_id,recipient_id,recipient_name,phone,office,updated_at) VALUES(?,?,?,?,?,?,?)""",
                           (str(uuid.uuid4()), batch_id, recipient["id"], recipient["name"],
                            recipient["phone"], recipient["office"], now))
            self._audit(db, "PREVIEW", batch_id=batch_id)
        return batch_id

    def _current_recipient_valid(self, db, job, building_id):
        row = db.execute("SELECT * FROM recipients WHERE id=?", (job["recipient_id"],)).fetchone()
        return bool(row and row["active"] and row["sms_enabled"] and
                    row["phone"] == job["phone"] and row["phone"] in self.allowed and
                    row["building_id"] == building_id and row["office"] == job["office"])

    def confirm(self, batch_id):
        with self.transaction() as db:
            self._housekeeping(db)
            batch = db.execute("SELECT * FROM gateway_batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                raise QueueError("No existe la vista previa")
            if batch["confirmed_at"] is not None:
                return  # Browser retry of the SAME draft never creates a second batch.
            if batch["status"] != "DRAFT" or batch["expires_at"] < self.clock():
                raise QueueError("La vista previa venció; prepará una nueva")
            control = db.execute("SELECT * FROM gateway_control WHERE id=1").fetchone()
            if not control["enabled"] or not control["active"] or control["last_seen"] < self.clock()-15:
                raise QueueError("Activá el gateway en el teléfono y habilitá los envíos en la PC")
            sync = db.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not sync or sync["status"] != "success" or sync["id"] != batch["preview_sync_id"]:
                raise QueueError("La sincronización cambió: revisá una nueva vista previa")
            jobs = db.execute("SELECT * FROM gateway_jobs WHERE batch_id=?", (batch_id,)).fetchall()
            if not 1 <= len(jobs) <= 3 or any(not self._current_recipient_valid(db,j,batch["building_id"]) for j in jobs):
                raise QueueError("Los destinatarios cambiaron: generá otra vista previa")
            # Distinct simultaneous batches are unnecessary in the three-person pilot.
            if db.execute("SELECT 1 FROM gateway_jobs WHERE status IN ('QUEUED','CLAIMED','STARTED') LIMIT 1").fetchone():
                raise QueueError("Ya hay una prueba en curso; terminá o detené esa cola")
            now = self.clock()
            db.execute("UPDATE gateway_batches SET status='QUEUED',confirmed_at=?,expires_at=? WHERE id=?",
                       (now, now+BATCH_TTL, batch_id))
            db.execute("UPDATE gateway_jobs SET status='QUEUED',updated_at=? WHERE batch_id=?", (now,batch_id))
            self._audit(db, "CONFIRM", batch_id=batch_id)

    def stop(self, batch_id):
        with self.transaction() as db:
            db.execute("UPDATE gateway_batches SET status='STOPPED' WHERE id=?", (batch_id,))
            db.execute("""UPDATE gateway_jobs SET status='CANCELLED',detail='Detenido desde la PC',updated_at=?
              WHERE batch_id=? AND status IN ('DRAFT','QUEUED','CLAIMED')""", (self.clock(),batch_id))
            self._audit(db, "STOP", batch_id=batch_id)

    def next_job(self, device_id):
        with self.transaction() as db:
            self._housekeeping(db)
            self._bind_device(db, device_id)
            control = db.execute("SELECT * FROM gateway_control WHERE id=1").fetchone()
            if not control["enabled"] or control["last_start"] > self.clock()-SMS_INTERVAL:
                return None
            if db.execute("SELECT 1 FROM gateway_jobs WHERE status='STARTED' LIMIT 1").fetchone():
                return None
            # A lost claim response reuses the same reservation instead of consuming another job.
            row = db.execute("SELECT * FROM gateway_jobs WHERE status='CLAIMED' AND device_id=? LIMIT 1", (device_id,)).fetchone()
            if row is None:
                row = db.execute("SELECT * FROM gateway_jobs WHERE status='QUEUED' ORDER BY updated_at,id LIMIT 1").fetchone()
                if row is None:
                    return None
                db.execute("UPDATE gateway_jobs SET status='CLAIMED',ticket=?,device_id=?,claimed_at=?,updated_at=? WHERE id=?",
                           (str(uuid.uuid4()),device_id,self.clock(),self.clock(),row["id"]))
                row = db.execute("SELECT * FROM gateway_jobs WHERE id=?",(row["id"],)).fetchone()
                self._audit(db, "CLAIM", job_id=row["id"])
            batch = db.execute("SELECT * FROM gateway_batches WHERE id=?",(row["batch_id"],)).fetchone()
            return {"id":row["id"], "batch_id":row["batch_id"], "phone":row["phone"],
                    "message":batch["message"], "ticket":row["ticket"], "mode":"test",
                    "expires_at":batch["expires_at"]}

    def start(self, device_id, job_id, ticket):
        with self.transaction() as db:
            self._housekeeping(db)
            job = db.execute("SELECT * FROM gateway_jobs WHERE id=?",(job_id,)).fetchone()
            if not job or job["device_id"] != device_id or job["ticket"] != ticket:
                raise QueueError("Reserva inválida")
            batch = db.execute("SELECT * FROM gateway_batches WHERE id=?",(job["batch_id"],)).fetchone()
            control = db.execute("SELECT * FROM gateway_control WHERE id=1").fetchone()
            if (not control["enabled"] or batch["status"] != "QUEUED" or
                batch["expires_at"] < self.clock() or job["status"] not in ("CLAIMED","STARTED")):
                return {"allowed":False, "status":job["status"]}
            if not self._current_recipient_valid(db, job, batch["building_id"]):
                db.execute("UPDATE gateway_jobs SET status='CANCELLED',detail='Destinatario cambió' WHERE id=?",(job_id,))
                return {"allowed":False, "status":"CANCELLED"}
            sync = db.execute("SELECT status FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not sync or sync["status"] != "success":
                return {"allowed":False, "status":"SYNC_ERROR"}
            if job["status"] == "CLAIMED":
                now=self.clock()
                db.execute("UPDATE gateway_jobs SET status='STARTED',started_at=?,updated_at=? WHERE id=?",(now,now,job_id))
                db.execute("UPDATE gateway_control SET last_start=? WHERE id=1",(now,))
                self._audit(db,"START",job_id=job_id)
            return {"allowed":True, "status":"STARTED"}

    def report(self, device_id, job_id, ticket, revision, state, delivery, detail):
        if state not in ("UNKNOWN","SUBMITTED","SENT","FAILED") or delivery not in ("WAITING","DELIVERED","FAILED","UNKNOWN"):
            raise QueueError("Estado inválido")
        with self.transaction() as db:
            job=db.execute("SELECT * FROM gateway_jobs WHERE id=?",(job_id,)).fetchone()
            if not job or job["device_id"] != device_id or job["ticket"] != ticket:
                raise QueueError("Trabajo ajeno o reserva inválida")
            if revision <= job["report_revision"]:
                return {"ack":revision}
            if job["started_at"] is None:
                raise QueueError("El servidor no autorizó el inicio de este trabajo")
            target = "STARTED" if state == "SUBMITTED" else state
            if delivery == "DELIVERED":
                target = "DELIVERED"
            if job["status"] == "DELIVERED":
                target = "DELIVERED"
            elif job["status"] == "SENT" and target in ("UNKNOWN","STARTED"):
                target = "SENT"
            db.execute("UPDATE gateway_jobs SET status=?,delivery_status=?,detail=?,report_revision=?,updated_at=? WHERE id=?",
                       (target,delivery,detail[:250],revision,self.clock(),job_id))
            if target in ("FAILED","UNKNOWN"):
                db.execute("UPDATE gateway_control SET enabled=0 WHERE id=1")
            self._audit(db,"REPORT_"+target,job_id=job_id,detail=detail)
            return {"ack":revision}

    def dashboard(self):
        with self.transaction() as db:
            self._housekeeping(db)
            control=dict(db.execute("SELECT * FROM gateway_control WHERE id=1").fetchone())
            batches=[dict(row) for row in db.execute("SELECT * FROM gateway_batches ORDER BY created_at DESC LIMIT 30")]
            for batch in batches:
                jobs=[dict(row) for row in db.execute("SELECT * FROM gateway_jobs WHERE batch_id=? ORDER BY recipient_name",(batch["id"],))]
                for job in jobs:
                    job["phone_masked"]=mask_phone(job.pop("phone"))
                    job.pop("ticket")
                batch["jobs"]=jobs
                batch["counts"]={status:sum(j["status"]==status for j in jobs) for status in
                                 ("DRAFT","QUEUED","CLAIMED","STARTED","SENT","DELIVERED","FAILED","UNKNOWN","CANCELLED")}
            control["connected"]=control["last_seen"] >= self.clock()-15 and bool(control["active"])
            return {"control":control, "batches":batches}

    def batch(self, batch_id):
        return next((b for b in self.dashboard()["batches"] if b["id"]==batch_id),None)
