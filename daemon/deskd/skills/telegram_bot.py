"""Telegram bot twin — control xarvii from your phone. Guarded, opt-in."""

import asyncio
import logging
import os

log = logging.getLogger("deskd.telegram")


async def run_bot(server, token_env="TELEGRAM_BOT_TOKEN", allowed_ids: str = ""):
    try:
        from telegram import Update
        from telegram.ext import (Application, CommandHandler,
                                  ContextTypes, MessageHandler, filters)
    except ImportError:
        log.info("python-telegram-bot not installed; telegram twin disabled")
        return

    token = os.environ.get(token_env, "")
    if not token:
        log.info("no %s; telegram twin disabled", token_env)
        return

    allow = {int(x) for x in allowed_ids.replace(" ", "").split(",") if x.isdigit()}

    def allowed(update: Update) -> bool:
        return not allow or (update.effective_user and update.effective_user.id in allow)

    async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not allowed(update):
            return
        st = server.brain_status()
        await update.message.reply_text(
            f"brains: {st['tiers'].get('fast')}\n"
            f"stt={st['stt_engine']} tts={st['tts_engine']}\n"
            f"pending reminders: {len(server.reminder_store.list())}")

    async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not allowed(update) or not ctx.args:
            await update.message.reply_text("usage: /remind <title> <when>")
            return
        text = update.message.text.split(" ", 1)[1]
        from .scheduler.reminders import parse_when

        m = re.match(r"(.+?)\s+(in\s+.+|at\s+.+|tomorrow.*)$", text, re.I)
        if not m:
            await update.message.reply_text("couldn't parse; e.g. /remind tea in 10m")
            return
        due = parse_when(m.group(2))
        if due is None:
            await update.message.reply_text("bad time format")
            return
        item = server.reminder_store.add(m.group(1), due)
        await update.message.reply_text(f"✓ [{item['id']}] {item['title']} @ {item['due']}")

    async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not allowed(update):
            return
        question = update.message.text.strip()
        answer = await server.answer_text(question)
        await update.message.reply_text(answer[:4000] or "…")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("remind", cmd_remind))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("telegram bot polling")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        while True:
            await asyncio.sleep(3600)


import re  # noqa: E402
