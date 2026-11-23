import os
import asyncio
from datetime import datetime
from datetime import timezone, timedelta
import aiohttp
from aiohttp import web

from database import init_db, set_task_status, get_report, get_marathon_day
from schedule_data import DAILY_SCHEDULE, AILEADERS_14_DAYS

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
TZ = timezone(timedelta(hours=5))
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def task_keyboard(task_id: str, is_alarm: bool = False):
    rows = [
        [
            {"text": "▶️ Boshladim", "callback_data": f"st:{task_id}:started"},
            {"text": "✅ Bajardim", "callback_data": f"st:{task_id}:done"}
        ],
        [{"text": "❌ O‘tkazib yubordim", "callback_data": f"st:{task_id}:skipped"}]
    ]
    if is_alarm and WEBAPP_URL.startswith("https://"):
        rows.insert(0, [{"text": "⏰ Budilnikni ochish (Misol yechish)", "web_app": {"url": WEBAPP_URL}}])
    return {"inline_keyboard": rows}

async def tg_call(session: aiohttp.ClientSession, method: str, payload: dict):
    if not BOT_TOKEN:
        return {}
    try:
        async with session.post(f"{API_URL}/{method}", json=payload, timeout=15) as resp:
            return await resp.json()
    except Exception as e:
        print(f"TG xato ({method}): {e}")
        return {}

async def notify_task(session: aiohttp.ClientSession, task: dict):
    if ADMIN_CHAT_ID == 0:
        return
    extra = ""
    if task["id"] == "aileaders":
        day = get_marathon_day()
        extra = f"\n🎯 <b>Bugungi dars:</b> {AILEADERS_14_DAYS[day]}"
    text = (
        f"🔔 <b>Vaqti bo‘ldi: {task['time']} – {task['end']}</b>\n"
        f"📌 <b>{task['title']}</b>\n"
        f"ℹ️ {task['desc']}{extra}"
    )
    await tg_call(session, "sendMessage", {
        "chat_id": ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": task_keyboard(task["id"], task["is_alarm"])
    })

async def send_biweekly_report(session: aiohttp.ClientSession, chat_id: int):
    rep = get_report(14)
    weak_text = "\n".join([f"  • {w[0]} ({w[1]} marta)" for w in rep["weak_spots"]]) or "  • Yo‘q (A’lo natija!)"
    text = (
        f"📊 <b>FocusAI — 14 Kunlik Intizom Hisoboti</b>\n\n"
        f"🏆 Umumiy intizom indeksi: <b>{rep['score']}%</b>\n"
        f"✅ To‘liq bajarilgan: <b>{rep['done']}</b> ta blok\n"
        f"▶️ Boshlangan: <b>{rep['started']}</b> ta blok\n"
        f"❌ Qolib ketgan: <b>{rep['skipped']}</b> ta blok\n\n"
        f"⚠️ <b>Eng ko‘p qolib ketgan vazifalar:</b>\n{weak_text}"
    )
    await tg_call(session, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

async def bot_polling_loop(session: aiohttp.ClientSession):
    offset = 0
    print("🤖 FocusAI Telegram Bot ishga tushdi...")
    while True:
        try:
            async with session.get(f"{API_URL}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=35) as resp:
                data = await resp.json()
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                if "message" in upd:
                    msg = upd["message"]
                    chat_id = msg["chat"]["id"]
                    txt = msg.get("text", "")
                    if txt.startswith("/start"):
                        kb = {"inline_keyboard": [[{"text": "📊 FocusAI Panel & Budilnik", "web_app": {"url": WEBAPP_URL}}]]} if WEBAPP_URL.startswith("https://") else None
                        day = get_marathon_day()
                        reply = (
                            f"⚡ <b>FocusAI ishga tushdi!</b>\n"
                            f"Telegram ID: <code>{chat_id}</code>\n"
                            f"Aileaders.uz marafoni: <b>{day}-kun</b> — {AILEADERS_14_DAYS[day]}\n\n"
                            f"Buyruqlar:\n/today — Bugungi jadval\n/report — 14 kunlik hisobot\n/test — Hozirgi eslatmani sinash"
                        )
                        payload = {"chat_id": chat_id, "text": reply, "parse_mode": "HTML"}
                        if kb:
                            payload["reply_markup"] = kb
                        await tg_call(session, "sendMessage", payload)
                    elif txt.startswith("/today"):
                        lines = [f"📅 <b>Bugungi Reja (Aileaders {get_marathon_day()}-kun):</b>\n"]
                        for t in DAILY_SCHEDULE:
                            lines.append(f"• <code>{t['time']}–{t['end']}</code> — <b>{t['title']}</b>")
                        await tg_call(session, "sendMessage", {"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML"})
                    elif txt.startswith("/report"):
                        await send_biweekly_report(session, chat_id)
                    elif txt.startswith("/test"):
                        await notify_task(session, DAILY_SCHEDULE[0])
                elif "callback_query" in upd:
                    cq = upd["callback_query"]
                    cdata = cq.get("data", "")
                    if cdata.startswith("st:"):
                        _, task_id, status = cdata.split(":")
                        task = next((t for t in DAILY_SCHEDULE if t["id"] == task_id), None)
                        if task:
                            set_task_status(task_id, task["title"], status)
                            status_uz = {"started": "▶️ Boshlandi", "done": "✅ Bajarildi", "skipped": "❌ O‘tkazib yuborildi"}[status]
                            await tg_call(session, "editMessageText", {
                                "chat_id": cq["message"]["chat"]["id"],
                                "message_id": cq["message"]["message_id"],
                                "text": f"<b>{task['time']} — {task['title']}</b>\nHolat: <b>{status_uz}</b> ({datetime.now(TZ).strftime('%H:%M')})",
                                "parse_mode": "HTML"
                            })
                        await tg_call(session, "answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Saqlandi!"})
        except Exception as e:
            print(f"Polling xato: {e}")
            await asyncio.sleep(3)

async def scheduler_loop(session: aiohttp.ClientSession):
    triggered = set()
    print("⏰ FocusAI Scheduler (Asia/Tashkent) ishga tushdi...")
    while True:
        now = datetime.now(TZ)
        today_str = now.strftime("%Y-%m-%d")
        hhmm = now.strftime("%H:%M")
        for task in DAILY_SCHEDULE:
            key = f"{today_str}:{task['id']}"
            if task["time"] == hhmm and key not in triggered:
                triggered.add(key)
                asyncio.create_task(notify_task(session, task))
        # Har 14 kunda bir marta 22:30 da hisobot
        if hhmm == "22:30" and f"{today_str}:biweekly" not in triggered:
            triggered.add(f"{today_str}:biweekly")
            if get_marathon_day() == 14 and ADMIN_CHAT_ID != 0:
                asyncio.create_task(send_biweekly_report(session, ADMIN_CHAT_ID))
        await asyncio.sleep(20)

async def handle_index(request):
    return web.FileResponse("static/index.html")

async def handle_status(request):
    return web.json_response({"schedule": DAILY_SCHEDULE, "report": get_report(14), "marathon_day": get_marathon_day()})

async def handle_task_update(request):
    task_id = request.match_info["task_id"]
    status = request.match_info["status"]
    task = next((t for t in DAILY_SCHEDULE if t["id"] == task_id), {"title": task_id})
    set_task_status(task_id, task["title"], status)
    return web.json_response({"ok": True})

async def on_startup(app):
    init_db()
    session = aiohttp.ClientSession()
    app["session"] = session
    app["bot_task"] = asyncio.create_task(bot_polling_loop(session))
    app["sched_task"] = asyncio.create_task(scheduler_loop(session))

async def on_cleanup(app):
    app["bot_task"].cancel()
    app["sched_task"].cancel()
    await app["session"].close()

app = web.Application()
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)
app.router.add_get("/", handle_index)
app.router.add_get("/api/status", handle_status)
app.router.add_post("/api/task/{task_id}/{status}", handle_task_update)
app.router.add_static("/static", "static")

if __name__ == "__main__":
    print("🚀 FocusAI server http://0.0.0.0:7860 da ishga tushmoqda...")
    web.run_app(app, host="0.0.0.0", port=7860)
