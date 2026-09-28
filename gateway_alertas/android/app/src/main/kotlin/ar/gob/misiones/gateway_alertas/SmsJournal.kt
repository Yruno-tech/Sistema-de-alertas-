package ar.gob.misiones.gateway_alertas

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject

class SmsJournal(context: Context) : SQLiteOpenHelper(context, "gateway_sms_v1.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""CREATE TABLE jobs(server TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'PREPARED',delivery TEXT NOT NULL DEFAULT 'WAITING',
            detail TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0,ack INTEGER NOT NULL DEFAULT 0,
            started INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL,PRIMARY KEY(server,id))""")
    }
    override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) { error("Migración no disponible") }
    override fun onConfigure(db: SQLiteDatabase) { db.execSQL("PRAGMA synchronous=FULL") }
    fun job(server: String, id: String): JSONObject? = readableDatabase.rawQuery(
        "SELECT payload FROM jobs WHERE server=? AND id=?", arrayOf(server, id)).use {
        if (it.moveToFirst()) JSONObject(it.getString(0)) else null
    }
    fun prepare(server: String, payload: JSONObject) {
        val id = payload.getString("id")
        val existing = job(server, id)
        if (existing != null) {
            require(listOf("phone", "message", "ticket", "batch_id").all { existing.getString(it) == payload.getString(it) }) { "El trabajo cambió de contenido" }
            return
        }
        writableDatabase.insertOrThrow("jobs", null, ContentValues().apply {
            put("server", server); put("id", id); put("payload", payload.toString()); put("updated", System.currentTimeMillis())
        })
    }
    fun beginSubmission(server: String, id: String): Boolean {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val state = db.rawQuery("SELECT state FROM jobs WHERE server=? AND id=?", arrayOf(server, id)).use {
                check(it.moveToFirst()) { "No existe el trabajo" }; it.getString(0)
            }
            if (state != "PREPARED") { db.setTransactionSuccessful(); return false }
            val now = System.currentTimeMillis()
            val last = db.rawQuery("SELECT COALESCE(MAX(started),0) FROM jobs", null).use { it.moveToFirst(); it.getLong(0) }
            check(now - last >= 30000) { "Esperá 30 segundos entre SMS" }
            db.execSQL("""UPDATE jobs SET state='UNKNOWN',revision=revision+1,started=?,updated=?,
                detail='Inicio registrado; resultado pendiente' WHERE server=? AND id=? AND state='PREPARED'""",
                arrayOf<Any>(now, now, server, id))
            db.setTransactionSuccessful()
            return true
        } finally { db.endTransaction() }
    }
    fun submitted(server: String, id: String) {
        writableDatabase.execSQL("""UPDATE jobs SET state='SUBMITTED',detail='Esperando resultado de Android',
            revision=revision+1,updated=? WHERE server=? AND id=? AND state='UNKNOWN'""", arrayOf<Any>(System.currentTimeMillis(), server, id))
    }
    fun uncertain(server: String, id: String, detail: String) {
        writableDatabase.execSQL("""UPDATE jobs SET state='UNKNOWN',detail=?,revision=revision+1,updated=?
            WHERE server=? AND id=? AND state IN ('UNKNOWN','SUBMITTED')""", arrayOf<Any>(detail, System.currentTimeMillis(), server, id))
    }
    fun sent(server: String, id: String, success: Boolean, detail: String) {
        writableDatabase.execSQL("""UPDATE jobs SET state=?,detail=?,revision=revision+1,updated=?
            WHERE server=? AND id=? AND state IN ('UNKNOWN','SUBMITTED')""",
            arrayOf<Any>(if (success) "SENT" else "FAILED", detail, System.currentTimeMillis(), server, id))
    }
    fun delivered(server: String, id: String, delivery: String, detail: String) {
        writableDatabase.execSQL("""UPDATE jobs SET delivery=?,state=CASE WHEN ?='DELIVERED' THEN 'SENT' ELSE state END,
            detail=?,revision=revision+1,updated=? WHERE server=? AND id=? AND started>0 AND delivery!='DELIVERED'""",
            arrayOf<Any>(delivery, delivery, detail, System.currentTimeMillis(), server, id))
    }
    fun expireSubmissions() {
        writableDatabase.execSQL("""UPDATE jobs SET state='UNKNOWN',detail='Sin resultado después de 2 minutos; revisar sin reenviar',
            revision=revision+1,updated=? WHERE state='SUBMITTED' AND started<?""",
            arrayOf(System.currentTimeMillis(), System.currentTimeMillis() - 120000))
    }
    fun prepared(server: String): List<String> = readableDatabase.rawQuery(
        "SELECT payload FROM jobs WHERE server=? AND state='PREPARED' ORDER BY updated", arrayOf(server)).use {
        val rows = mutableListOf<String>(); while (it.moveToNext()) rows.add(it.getString(0)); rows
    }
    fun reports(server: String): List<Map<String, Any>> = readableDatabase.rawQuery(
        "SELECT id,payload,state,delivery,detail,revision FROM jobs WHERE server=? AND revision>ack AND started>0 ORDER BY updated LIMIT 100", arrayOf(server)).use {
        val rows = mutableListOf<Map<String, Any>>()
        while (it.moveToNext()) rows.add(mapOf("id" to it.getString(0), "ticket" to JSONObject(it.getString(1)).getString("ticket"),
            "state" to it.getString(2), "delivery" to it.getString(3), "detail" to it.getString(4), "revision" to it.getInt(5)))
        rows
    }
    fun recent(server: String): List<Map<String, Any>> = readableDatabase.rawQuery(
        "SELECT id,payload,state,delivery,detail FROM jobs WHERE server=? ORDER BY updated DESC LIMIT 10", arrayOf(server)).use {
        val rows = mutableListOf<Map<String, Any>>()
        while (it.moveToNext()) rows.add(mapOf("id" to it.getString(0), "phone" to "…${JSONObject(it.getString(1)).getString("phone").takeLast(4)}",
            "state" to it.getString(2), "delivery" to it.getString(3), "detail" to it.getString(4)))
        rows
    }
    fun ack(server: String, id: String, revision: Int) {
        writableDatabase.execSQL("UPDATE jobs SET ack=MAX(ack,?) WHERE server=? AND id=? AND revision>=?", arrayOf<Any>(revision, server, id, revision))
    }
    fun abandon(server: String, id: String) {
        writableDatabase.execSQL("UPDATE jobs SET state='CANCELLED',detail='Orden cancelada o vencida',updated=? WHERE server=? AND id=? AND state='PREPARED'",
            arrayOf<Any>(System.currentTimeMillis(), server, id))
    }
}
