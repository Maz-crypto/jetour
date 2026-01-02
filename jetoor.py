# jetoor.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.ext import Application
from database import init_db, safe_db_execute, safe_db_fetchone, safe_db_fetchall
from telegram.helpers import escape_markdown
import logging
import os
import asyncio
from typing import Optional

# ---------------- CONFIG ----------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMINS = [int(x.strip()) for x in os.environ["ADMINS"].split(",") if x.strip()]
BATCH_SIZE = 30

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- STATE CONSTANTS ----------------
STATE_IDLE = "idle"
STATE_WITHDRAW_METHOD = "withdraw:method"
STATE_WITHDRAW_DATA = "withdraw:data"
STATE_SUPPORT = "support"
STATE_BROADCAST = "broadcast"
STATE_AWAITING_USER_ID = "msg:user_id"
STATE_TARGET_MESSAGE = "msg:content"
STATE_AWAITING_PAYMENT = "payment:proof"
STATE_ADD_PAYMENT_NAME = "payment:add:name"
STATE_ADD_PAYMENT_LINK = "payment:add:link"
STATE_APPROVE_PID = "admin:approve:pid"
STATE_PAY_WID = "admin:pay:wid"
STATE_EDIT_SETTING = "admin:edit:"
STATE_EDIT_PM = "admin:edit_pm:"

# ---------------- UTILS ----------------
def parse_callback(data: str):
    try:
        parts = data.split(":", 2)
        action = parts[0]
        id_val = parts[1] if len(parts) > 1 else None
        extra = parts[2] if len(parts) > 2 else None
        return action, id_val, extra
    except:
        return None, None, None


def clean_user_data(context, keys=None):
    if keys:
        for k in keys:
            context.user_data.pop(k, None)
    else:
        context.user_data.clear()

def confirm_menu(yes="✅ نعم", no="❌ لا", yes_data="confirm:yes", no_data="cancel:op"):
    return InlineKeyboardMarkup([[InlineKeyboardButton(yes, callback_data=yes_data),
                                   InlineKeyboardButton(no, callback_data=no_data)]])

# ---------------- ERROR HANDLER ----------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}", exc_info=True)

# ---------------- MENUS ----------------
def user_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 الاشتراك", callback_data="menu:subscribe")],
        [InlineKeyboardButton("💰 الإحالة", callback_data="menu:referral")],
        [InlineKeyboardButton("📊 رصيدي", callback_data="menu:balance")],
        [InlineKeyboardButton("📤 سحب الأرباح", callback_data="menu:withdraw")],
        [InlineKeyboardButton("🛠️ الدعم", callback_data="menu:support")]
    ])

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧾 طلبات الاشتراك", callback_data="admin:payments")],
        [InlineKeyboardButton("💸 طلبات السحب", callback_data="admin:withdraws")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="admin:settings")],
        [InlineKeyboardButton("💳 طرق الدفع", callback_data="admin:payment_methods")],
        [InlineKeyboardButton("🔗 روابط القناة", callback_data="admin:channel_links")],
        [InlineKeyboardButton("📢 رسالة جماعية", callback_data="admin:broadcast")],
        [InlineKeyboardButton("📨 رسالة لمستخدم", callback_data="admin:send_to_user")]
    ])

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    ref = int(args[0]) if args and args[0].isdigit() else None
    if ref == user.id:
        ref = None

    await safe_db_execute("""
        INSERT INTO users (telegram_id, username, referrer_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_id) DO NOTHING
    """, (user.id, user.username, ref))

    price_row = await safe_db_fetchone("SELECT value FROM settings WHERE key = 'subscription_price'")
    price = price_row["value"] if price_row else "5"
    await update.message.reply_text(
        f"🔐 مرحبًا بك في بوت الاشتراك في قناة الأخبار العاجلة\n\n"
        f"📌 اشترك الآن للوصول إلى المحتوى الحصري\n"
        f"💰 اربح عبر رابط الإحالة بعد تفعيل اشتراكك\n\n"
        f"💳 رسوم الاشتراك: **{price}$ أمريكي**\n"
        f"🗓️ المدة: حتى **31 ديسمبر 2026**",
        parse_mode="HTML",
        reply_markup=user_menu()
    )

# ---------------- CALLBACKS ----------------
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, id_val, extra = parse_callback(q.data)
    if not action:
        await q.message.reply_text("❌ طلب غير صالح.")
        return

    uid = q.from_user.id

    # ---------- USER ----------
    if action == "menu":
        if id_val == "subscribe":
            rows = await safe_db_fetchall("SELECT id, name, barcode FROM payment_methods")
            if not rows:
                await q.message.reply_text("💳 لا توجد طرق دفع متاحة. تواصل مع الدعم.")
                return
            buttons = [[InlineKeyboardButton(r["name"], callback_data=f"paymethod:{r['id']}")] for r in rows]
            await q.message.reply_text("💳 اختر طريقة الدفع:", reply_markup=InlineKeyboardMarkup(buttons))
        
        elif id_val == "referral":
            row = await safe_db_fetchone(
                "SELECT subscription_active FROM users WHERE telegram_id = %s", (uid,)
            )
            active = row["subscription_active"] if row else 0
            if active != 1:
                await q.message.reply_text("❌ يجب أن تكون مشتركًا لتفعيل رابط الإحالة.")
                return
            reward = (await safe_db_fetchone(
                "SELECT value FROM settings WHERE key = 'referral_reward'"
            ))["value"]
            # ✅ رابط صحيح بدون مسافات
            link = f"https://t.me/news_acc_bot?start={uid}"
            await q.message.reply_text(
                f"🔗 رابطك:\n{link}\n💰 العمولة: {reward}$",
                disable_web_page_preview=True,
                parse_mode="HTML"
            )
        
        elif id_val == "balance":
            row = await safe_db_fetchone(
                "SELECT referral_balance FROM users WHERE telegram_id = %s", (uid,)
            )
            bal = row["referral_balance"] if row else 0
            await q.message.reply_text(f"💵 رصيدك: {bal}$", parse_mode="HTML")
        
        elif id_val == "withdraw":
            row = await safe_db_fetchone(
                "SELECT referral_balance FROM users WHERE telegram_id = %s", (uid,)
            )
            bal = float(row["referral_balance"]) if row else 0.0
            min_w = float((await safe_db_fetchone(
                "SELECT value FROM settings WHERE key = 'min_withdraw'"
            ))["value"])
            if bal < min_w:
                await q.message.reply_text(
                    f"❌ الحد الأدنى للسحب هو {min_w}$. رصيدك: {bal}$.",
                    parse_mode="HTML"
                )
            else:
                context.user_data.update({
                    "state": STATE_WITHDRAW_METHOD,
                    "amount": bal
                })
                await q.message.reply_text(
                    f"💰 رصيدك جاهز للسحب: {bal}$nnاختر طريقة الاستلام:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("شام كاش", callback_data="withdraw:sham")],
                        [InlineKeyboardButton("USDT (BEP20)", callback_data="withdraw:usdt")],
                        [InlineKeyboardButton("إلغاء", callback_data="cancel:op")]
                    ])
                )
        
        elif id_val == "support":
            context.user_data["state"] = STATE_SUPPORT
            await q.message.reply_text("✉️ اكتب رسالتك:")

    elif action == "paymethod":
        try:
            method_id = int(id_val)
            context.user_data.update({
                "state": STATE_AWAITING_PAYMENT,
                "payment_method_id": method_id
            })
            row = await safe_db_fetchone(
                "SELECT name, barcode FROM payment_methods WHERE id = %s", (method_id,)
            )
            if not row:
                await q.message.reply_text("❌ طريقة دفع غير موجودة.")
                return
            name = row["name"]
            barcode = row["barcode"]
            await q.message.reply_text(
                f"💵 أرسل **صورة إشعار الدفع** (لقطة من تطبيق الدفع)\n"
                f"📱 الطريقة: *{ name }*\n"
                f"📎 الرابط: `{ barcode }`",
                parse_mode="HTML"
            )
        except (ValueError, TypeError):
            await q.message.reply_text("❌ معرّف غير صالح.")

    elif action == "withdraw":
        context.user_data.update({
            "state": STATE_WITHDRAW_DATA,
            "withdraw_method": id_val  # sham أو usdt
        })
        msg = "كود شام كاش:" if id_val == "sham" else "محفظة USDT (BEP20):"
        await q.message.reply_text(f"🔢 {msg}", parse_mode="HTML")

    elif action == "confirm" and id_val == "withdraw":
        wd = context.user_data.pop("temp_withdraw", None)
        if not wd:
            await q.message.edit_text("❌ بيانات مفقودة أو منتهية.", parse_mode="HTML")
            return
        try:
            row = await safe_db_fetchone("""
                INSERT INTO withdrawals (user_id, amount, sham_cash_link, method, status)
                VALUES (%s, %s, %s, %s, 'PENDING')
                RETURNING id
            """, (uid, wd["amount"], wd["data"], wd["method"]))
            wid = row["id"]
            clean_user_data(context, ["temp_withdraw"])
            await q.message.edit_text(f"✅ تم إرسال طلب السحب #{wid} للأدمن.", parse_mode="HTML")
            # إشعار الأدمن
            method_text = "شام كاش" if wd["method"] == "sham" else "USDT (BEP20)"
            for admin in ADMINS:
                try:
                    await context.bot.send_message(
                        admin,
                        f"💸 طلب سحب جديد #{wid}\n"
                        f"👤 المستخدم: {uid}\n"
                        f"💵 المبلغ: {wd['amount']}$\n"
                        f"📌 الطريقة: {method_text}\n"
                        f"📋 البيانات: `{ wd['data'] }`",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ تأكيد", callback_data=f"pay:{wid}")],
                            [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_w:{wid}")],
                            [InlineKeyboardButton("ℹ️ استعلام", callback_data=f"inquiry:{uid}")]
                        ])
                    )
                except Exception as e:
                    logger.warning(f"Failed to notify admin {admin}: {e}")
        except Exception as e:
            logger.error(f"Withdraw insert failed: {e}")
            await q.message.edit_text("❌ خطأ في معالجة الطلب.", parse_mode="HTML")

    elif action == "edit" and id_val == "withdraw_data":
        method = context.user_data.get("withdraw_method_temp", "sham")
        bal = context.user_data.get("withdraw_amount", 0)
        msg = "أعد إدخال كود شام كاش:" if method == "sham" else "أعد إدخال محفظة USDT (BEP20):"
        context.user_data["state"] = STATE_WITHDRAW_DATA
        context.user_data["withdraw_method"] = method
        context.user_data.pop("withdraw_data_temp", None)
        await q.message.edit_text(f"{msg}\n💵 المبلغ: {bal}$", parse_mode="HTML")

    elif action == "cancel":
        clean_user_data(context)
        await q.message.reply_text("❌ تم الإلغاء.", parse_mode="HTML")

    # ---------- ADMIN ----------
    if uid not in ADMINS:
        return

    if action == "admin":
        if id_val == "payments":
            rows = await safe_db_fetchall(
                "SELECT id, user_id, amount, proof FROM payments WHERE status = 'PENDING'"
            )
            if not rows:
                await q.message.reply_text("📭 لا توجد طلبات.", parse_mode="HTML")
                return
            for r in rows:
                try:
                    await context.bot.send_photo(
                        uid, photo=r["proof"],
                        caption=f"🧾 اشتراك #{r['id']}\n👤 {r['user_id']}\n💵 {r['amount']}$",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅", callback_data=f"approve:{r['id']}"),
                             InlineKeyboardButton("❌", callback_data=f"reject:{r['id']}")]
                        ])
                    )
                except Exception as e:
                    logger.warning(f"Photo send failed: {e}")
        
        elif id_val == "withdraws":
            rows = await safe_db_fetchall("""
                SELECT id, user_id, amount, sham_cash_link, method
                FROM withdrawals WHERE status = 'PENDING'
            """)
            if not rows:
                await q.message.reply_text("📭 لا توجد طلبات سحب.", parse_mode="HTML")
                return
            for r in rows:
                bal_row = await safe_db_fetchone(
                    "SELECT referral_balance FROM users WHERE telegram_id = %s", (r["user_id"],)
                )
                bal = bal_row["referral_balance"] if bal_row else 0
                method = "شام كاش" if r["method"] == "sham" else "USDT (BEP20)"
                await q.message.reply_text(
                    f"💸 طلب سحب #{r['id']}\n"
                    f"👤 المستخدم: {r['user_id']}\n"
                    f"💵 المبلغ: {r['amount']}$\n"
                    f"📊 رصيده الحالي: {bal}$\n"
                    f"📌 الطريقة: {method}\n"
                    f"📋 البيانات: `{ r['sham_cash_link'] or '---' }`",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأكيد", callback_data=f"pay:{r['id']}"),
                         InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_w:{r['id']}"),
                         InlineKeyboardButton("ℹ️ استعلام", callback_data=f"inquiry:{r['user_id']}")]
                    ])
                )
        
        elif id_val == "settings":
            p = (await safe_db_fetchone("SELECT value FROM settings WHERE key = 'subscription_price'"))["value"]
            r = (await safe_db_fetchone("SELECT value FROM settings WHERE key = 'referral_reward'"))["value"]
            m = (await safe_db_fetchone("SELECT value FROM settings WHERE key = 'min_withdraw'"))["value"]
            await q.message.reply_text(
                f"⚙️ الإعدادات:\n- السعر: {p}$\n- العمولة: {r}$\n- الحد الأدنى: {m}$",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ سعر", callback_data="edit:price")],
                    [InlineKeyboardButton("✏️ عمولة", callback_data="edit:ref")],
                    [InlineKeyboardButton("✏️ حد السحب", callback_data="edit:min")]
                ])
            )
        
        elif id_val == "payment_methods":
            rows = await safe_db_fetchall("SELECT id, name FROM payment_methods")
            buttons = [[InlineKeyboardButton("➕ إضافة طريقة دفع", callback_data="add_payment:new")]]
            for r in rows:
                buttons.append([
                    InlineKeyboardButton("✏️ تعديل", callback_data=f"edit_pm:{r['id']}"),
                    InlineKeyboardButton("🗑️ حذف", callback_data=f"del_pm:{r['id']}")
                ])
                buttons.append([InlineKeyboardButton(f"💳 {r['name']}", callback_data="cancel:op")])
            buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="cancel:op")])
            await q.message.reply_text(
                "💳 طرق الدفع المتوفرة:" if rows else "💳 لا توجد طرق دفع مُضافة بعد.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        
        elif id_val == "channel_links":
            rows = await safe_db_fetchall("SELECT id, link FROM channel_links")
            buttons = [[InlineKeyboardButton("➕ إضافة روابط", callback_data="add_links:bulk")]]
            for r in rows:
                short = (r["link"][:25] + "…") if len(r["link"]) > 25 else r["link"]
                buttons.append([InlineKeyboardButton(f"🗑️ { short }", callback_data=f"del_link:{r['id']}")])
            buttons.append([InlineKeyboardButton("🔙", callback_data="cancel:op")])
            await q.message.reply_text("🔗 روابط القناة:", reply_markup=InlineKeyboardMarkup(buttons))
        
        elif id_val == "broadcast":
            context.user_data["state"] = STATE_BROADCAST
            await q.message.reply_text("📢 أرسل الرسالة الجماعية:")
        
        elif id_val == "send_to_user":
            context.user_data["state"] = STATE_AWAITING_USER_ID
            await q.message.reply_text("👤 أرسل معرف المستخدم (ID):", parse_mode="HTML")

    elif action == "approve":
        try:
            pid = int(id_val)
            context.user_data.update({
                "state": STATE_APPROVE_PID,
                "approve_pid": pid
            })
            await q.message.reply_text("🔢 أدخل رقم العملية:")
        except (ValueError, TypeError):
            await q.message.reply_text("❌ معرّف غير صالح.")

    elif action == "reject":
        await q.message.reply_text("⚠️ تأكيد الرفض؟", reply_markup=confirm_menu("✅", "❌", f"confirm_reject:{id_val}", "cancel:op"))

    elif action == "confirm_reject":
        try:
            pid = int(id_val)
            await safe_db_execute("UPDATE payments SET status = 'REJECTED' WHERE id = %s", (pid,))
            await q.message.reply_text("❌ تم الرفض.", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Reject failed: {e}")
            await q.message.reply_text("❌ خطأ في المعالجة.")

    elif action == "pay":
        try:
            wid = int(id_val)
            context.user_data.update({
                "state": STATE_PAY_WID,
                "pay_wid": wid
            })
            await q.message.reply_text("🔢 أدخل رقم العملية:")
        except (ValueError, TypeError):
            await q.message.reply_text("❌ معرّف غير صالح.")

    elif action == "cancel_w":
        await q.message.reply_text("⚠️ تأكيد إلغاء طلب السحب؟", reply_markup=confirm_menu("✅", "❌", f"confirm_cancel_w:{id_val}", "cancel:op"))

    elif action == "confirm_cancel_w":
        try:
            wid = int(id_val)
            row = await safe_db_fetchone("SELECT user_id FROM withdrawals WHERE id = %s", (wid,))
            if not row:
                await q.message.reply_text("❌ الطلب غير موجود.")
                return
            u = row["user_id"]
            await safe_db_execute("UPDATE withdrawals SET status = 'CANCELLED' WHERE id = %s", (wid,))
            try:
                await context.bot.send_message(
                    u,
                    "❌ تم إلغاء طلب سحب أرباحك. تواصل مع الدعم للمزيد.",
                    parse_mode="HTML"
                )
            except:
                pass
            await q.message.reply_text("✅ تم الإلغاء.", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Cancel withdrawal failed: {e}")
            await q.message.reply_text("❌ خطأ في المعالجة.")

    elif action == "inquiry":
        try:
            user_id = int(id_val)
            row = await safe_db_fetchone("SELECT * FROM users WHERE telegram_id = %s", (user_id,))
            if not row:
                await q.message.reply_text("❌ المستخدم غير موجود.", parse_mode="HTML")
                return
            status = "نشط" if row["subscription_active"] == 1 else "غير نشط"
            await q.message.reply_text(
                f"ℹ️ استعلام عن المستخدم {row['telegram_id']}:\n"
                f"👤 المعرف: @{row['username'] or '---'}\n"
                f"💰 الرصيد: {row['referral_balance']}$\n"
                f"📌 حالة الاشتراك: {status}\n"
                f"🗓️ انتهاء الاشتراك: {row['subscription_end'] or '---'}\n"
                f"👥 المُحيل: {row['referrer_id'] or '---'}",
                parse_mode="HTML"
            )
        except (ValueError, TypeError):
            await q.message.reply_text("❌ معرّف غير صالح.")

    elif action == "edit":
        key_map = {"price": "subscription_price", "ref": "referral_reward", "min": "min_withdraw"}
        key = key_map.get(id_val)
        if key:
            context.user_data["state"] = STATE_EDIT_SETTING + key
            await q.message.reply_text(f"أدخل القيمة الجديدة لـ '{id_val}':")

    elif action == "add_payment" and id_val == "new":
        context.user_data["state"] = STATE_ADD_PAYMENT_NAME
        await q.message.reply_text("✏️ أرسل اسم طريقة الدفع:")

    elif action == "edit_pm":
        try:
            m_id = int(id_val)
            context.user_data["state"] = STATE_EDIT_PM + str(m_id)
            await q.message.reply_text("أدخل الاسم الجديد:")
        except (ValueError, TypeError):
            await q.message.reply_text("❌ معرّف غير صالح.")

    elif action == "del_pm":
        await q.message.reply_text("⚠️ حذف الطريقة؟", reply_markup=confirm_menu("✅", "❌", f"confirm_del_pm:{id_val}", "cancel:op"))

    elif action == "confirm_del_pm":
        try:
            m_id = int(id_val)
            await safe_db_execute("DELETE FROM payment_methods WHERE id = %s", (m_id,))
            await q.message.reply_text("✅ تم الحذف.", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Delete payment method failed: {e}")
            await q.message.reply_text("❌ خطأ في الحذف.")

    elif action == "add_links" and id_val == "bulk":
        context.user_data["state"] = "add_links:bulk"
        await q.message.reply_text(
            "📎 أرسل جميع روابط القناة في رسالة واحدة (كل رابط في سطر):\n\n"
            "مثال:\n`https://t.me/channel1`\n`https://t.me/channel2`",
            parse_mode="HTML"
        )

    elif action == "del_link":
        await q.message.reply_text("⚠️ حذف الرابط؟", reply_markup=confirm_menu("✅", "❌", f"confirm_del_link:{id_val}", "cancel:op"))

    elif action == "confirm_del_link":
        try:
            lid = int(id_val)
            await safe_db_execute("DELETE FROM channel_links WHERE id = %s", (lid,))
            await q.message.reply_text("✅ تم الحذف.", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Delete link failed: {e}")
            await q.message.reply_text("❌ خطأ في الحذف.")

# ---------------- MESSAGES ----------------
async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    text = update.message.text.strip() if update.message.text else ""
    state = context.user_data.get("state", STATE_IDLE)
    uid = update.effective_user.id

    # --- دعم ---
    if state == STATE_SUPPORT:
        for admin in ADMINS:
            try:
                await context.bot.send_message(admin, f"📩 دعم من {uid}:\n{text}")
            except Exception as e:
                logger.warning(f"Support msg to admin failed: {e}")
        clean_user_data(context, ["state"])
        await update.message.reply_text("✅ تم الإرسال.", parse_mode="HTML")
        return

    # --- إدخال معرف مستخدم (للرسالة الفردية) ---
    if state == STATE_AWAITING_USER_ID:
        try:
            target_id = int(text.strip())
            context.user_data.update({
                "state": STATE_TARGET_MESSAGE,
                "target_user_id": target_id
            })
            await update.message.reply_text(f"📨 أرسل الرسالة لـ `{target_id}`:", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ معرف غير صالح. أدخل أرقامًا فقط.", parse_mode="HTML")
        return

    # --- إرسال رسالة لمستخدم محدد ---
    if state == STATE_TARGET_MESSAGE:
        target_id = context.user_data.get("target_user_id")
        if not target_id:
            clean_user_data(context, ["state", "target_user_id"])
            await update.message.reply_text("❌ خطأ داخلي. أعد المحاولة.")
            return
        try:
            await context.bot.send_message(
                target_id,
                f"📩 **رسالة من الإدارة**:\n\n{ text }",
                parse_mode="HTML"
            )
            await update.message.reply_text(f"✅ تم الإرسال إلى `{target_id}`.", parse_mode="HTML")
        except Exception as e:
            err = "❌ فشل الإرسال:n"
            if "bot was blocked" in str(e):
                err += "• المستخدم حظر البوتn"
            elif "chat not found" in str(e):
                err += "• المعرف خاطئ أو لم يبدأ محادثةn"
            else:
                err += f"• خطأ: {type(e).__name__}"
            logger.warning(f"Message to {target_id} failed: {e}")
            await update.message.reply_text(err, parse_mode="HTML")
        finally:
            clean_user_data(context, ["state", "target_user_id"])
        return

    # --- إدخال بيانات السحب ---
    if state == STATE_WITHDRAW_DATA:
        method = context.user_data.get("withdraw_method")
        amount = context.user_data.get("amount", 0)
        if not method or amount <= 0:
            clean_user_data(context, ["state", "withdraw_method", "amount"])
            await update.message.reply_text("❌ خطأ داخلي. أعد المحاولة.")
            return

        # تحقق من صحة البيانات
        if method == "sham":
            if len(text) < 5 or " " in text or "HTTP" in text.upper():
                await update.message.reply_text("❌ كود شام كاش غير صالح. أعد المحاولة.", parse_mode="HTML")
                return
            label = "كود شام كاش"
        else:  # usdt
            if not text.startswith("0x") or len(text) < 10:
                await update.message.reply_text("❌ محفظة USDT غير صالحة. يجب أن تبدأ بـ `0x`.", parse_mode="HTML")
                return
            label = "محفظة USDT"

        # تحقق من طلب معلق
        row = await safe_db_fetchone(
            "SELECT id FROM withdrawals WHERE user_id = %s AND status = 'PENDING'", (uid,)
        )
        if row:
            clean_user_data(context, ["state", "withdraw_method", "amount"])
            await update.message.reply_text("⏳ لديك طلب سحب معلق. انتظر معالجته أولًا.", parse_mode="HTML")
            return

        # حفظ مؤقت
        context.user_data.update({
            "temp_withdraw": {"method": method, "amount": amount, "data": text}
        })
        clean_user_data(context, ["state", "withdraw_method", "amount"])

        method_text = "شام كاش" if method == "sham" else "USDT (BEP20)"
        await update.message.reply_text(
            f"⚠️ تأكيد طلب السحب:\n"
            f"💵 المبلغ: {amount}$\n"
            f"📌 الطريقة: {method_text}\n"
            f"📋 {label}: `{ text }`\n\n"
            f"هل تريد تأكيد الطلب؟",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد", callback_data="confirm:withdraw")],
                [InlineKeyboardButton("❌ تعديل", callback_data="edit:withdraw_data")]
            ])
        )
        return

    # --- صورة إثبات الدفع ---
    if state == STATE_AWAITING_PAYMENT and update.message.photo:
        price = (await safe_db_fetchone("SELECT value FROM settings WHERE key = 'subscription_price'"))["value"]
        method_id = context.user_data.get("payment_method_id")
        if not method_id:
            clean_user_data(context, ["state", "payment_method_id"])
            await update.message.reply_text("❌ خطأ داخلي. أعد المحاولة.")
            return
        file_id = update.message.photo[-1].file_id
        try:
            row = await safe_db_fetchone("""
                INSERT INTO payments (user_id, amount, proof, status, payment_method_id)
                VALUES (%s, %s, %s, 'PENDING', %s)
                RETURNING id
            """, (uid, price, file_id, method_id))
            pid = row["id"]
            clean_user_data(context, ["state", "payment_method_id"])
            await update.message.reply_text("📩 تم استلام صورة إشعار الدفع.", parse_mode="HTML")
            # إشعار الأدمن
            for admin in ADMINS:
                try:
                    await context.bot.send_photo(
                        admin, photo=file_id,
                        caption=f"طلب اشتراك جديدnالمستخدم: {uid}",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅", callback_data=f"approve:{pid}")],
                            [InlineKeyboardButton("❌", callback_data=f"reject:{pid}")]
                        ])
                    )
                except Exception as e:
                    logger.warning(f"Payment photo to admin failed: {e}")
        except Exception as e:
            logger.error(f"Payment insert failed: {e}")
            await update.message.reply_text("❌ خطأ في تسجيل الدفع.", parse_mode="HTML")
        return

    # --- إضافة طريقة دفع: الاسم ---
    if state == STATE_ADD_PAYMENT_NAME:
        context.user_data.update({
            "state": STATE_ADD_PAYMENT_LINK,
            "new_payment_name": text
        })
        await update.message.reply_text(f"✅ الاسم: *{ text }*\n🔗 أرسل الرابط:", parse_mode="HTML")
        return

    # --- إضافة طريقة دفع: الرابط ---
    if state == STATE_ADD_PAYMENT_LINK:
        name = context.user_data.get("new_payment_name")
        if not name:
            clean_user_data(context, ["state", "new_payment_name"])
            await update.message.reply_text("❌ خطأ داخلي. أعد المحاولة.")
            return
        try:
            await safe_db_execute(
                "INSERT INTO payment_methods (name, barcode) VALUES (%s, %s)",
                (name, text)
            )
            clean_user_data(context, ["state", "new_payment_name"])
            await update.message.reply_text("✅ تم الإضافة بنجاح!", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Add payment method failed: {e}")
            await update.message.reply_text("❌ خطأ في الحفظ.", parse_mode="HTML")
        return

    # --- إضافة روابط دفعة واحدة ---
    if state == "add_links:bulk":
        clean_user_data(context, ["state"])
        lines = text.strip().splitlines()
        links = [line.strip() for line in lines if line.strip().startswith("http")]
        if not links:
            await update.message.reply_text("❌ لم يتم العثور على روابط صالحة.", parse_mode="HTML")
            return
        added = 0
        for link in links:
            try:
                row = await safe_db_fetchone("""
                    INSERT INTO channel_links (link)
                    VALUES (%s)
                    ON CONFLICT (link) DO NOTHING
                    RETURNING id
                """, (link,))
                if row:
                    added += 1
            except Exception as e:
                logger.error(f"Link insert failed: {link} | {e}")
        await update.message.reply_text(f"✅ تم حفظ {added} رابط.", parse_mode="HTML")
        return

    # --- الموافقة على الاشتراك (أدخل رقم العملية) ---
    if state == STATE_APPROVE_PID:
        pid = context.user_data.get("approve_pid")
        if not pid:
            clean_user_data(context, ["state", "approve_pid"])
            await update.message.reply_text("❌ خطأ داخلي. أعد المحاولة.")
            return
        try:
            row = await safe_db_fetchone(
                "SELECT user_id FROM payments WHERE id = %s AND status = 'PENDING'", (pid,)
            )
            if not row:
                clean_user_data(context, ["state", "approve_pid"])
                await update.message.reply_text("❌ الطلب غير موجود أو مُعالج مسبقًا.", parse_mode="HTML")
                return
            user_id = row["user_id"]
            link_row = await safe_db_fetchone("SELECT id, link FROM channel_links ORDER BY id LIMIT 1")
            if not link_row:
                await update.message.reply_text("❌ لا توجد روابط. أضف روابط أولًا.", parse_mode="HTML")
                return
            link_id = link_row["id"]
            link = link_row["link"]
            end_date = "2026-12-31"
            await safe_db_execute(
                "UPDATE payments SET status = 'APPROVED', transaction_id = %s WHERE id = %s",
                (text, pid)
            )
            await safe_db_execute(
                "UPDATE users SET subscription_active = 1, subscription_end = %s WHERE telegram_id = %s",
                (end_date, user_id)
            )
            # مكافأة المُحيل
            ref_row = await safe_db_fetchone("SELECT referrer_id FROM users WHERE telegram_id = %s", (user_id,))
            ref = ref_row["referrer_id"] if ref_row else None
            if ref:
                ref_active = await safe_db_fetchone(
                    "SELECT subscription_active FROM users WHERE telegram_id = %s", (ref,)
                )
                if ref_active and ref_active["subscription_active"] == 1:
                    reward = (await safe_db_fetchone(
                        "SELECT value FROM settings WHERE key = 'referral_reward'"
                    ))["value"]
                    await safe_db_execute(
                        "UPDATE users SET referral_balance = referral_balance + %s WHERE telegram_id = %s",
                        (reward, ref)
                    )
            await safe_db_execute("DELETE FROM channel_links WHERE id = %s", (link_id,))
            try:
                await context.bot.send_message(
                    user_id,
                    f"🎉 اشتراكك مفعل!\nالرابط:\n{ link }",
                    parse_mode="HTML"
                )
            except:
                pass
            clean_user_data(context, ["state", "approve_pid"])
            await update.message.reply_text(f"✅ تم تفعيل الاشتراك لـ {user_id}.", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Approve failed: {e}")
            clean_user_data(context, ["state", "approve_pid"])
            await update.message.reply_text("❌ خطأ في المعالجة.", parse_mode="HTML")
        return

    # --- صرف السحب (أدخل رقم العملية) ---
    if state == STATE_PAY_WID:
        wid = context.user_data.get("pay_wid")
        if not wid:
            clean_user_data(context, ["state", "pay_wid"])
            await update.message.reply_text("❌ خطأ داخلي. أعد المحاولة.")
            return
        try:
            row = await safe_db_fetchone(
                "SELECT user_id, amount, sham_cash_link, method FROM withdrawals WHERE id = %s", (wid,)
            )
            if not row:
                clean_user_data(context, ["state", "pay_wid"])
                await update.message.reply_text("❌ طلب السحب غير موجود.", parse_mode="HTML")
                return
            u = row["user_id"]
            amt = row["amount"]
            data = row["sham_cash_link"]
            method_type = row["method"]
            await safe_db_execute("UPDATE users SET referral_balance = 0 WHERE telegram_id = %s", (u,))
            await safe_db_execute(
                "UPDATE withdrawals SET status = 'PAID', transaction_id = %s WHERE id = %s",
                (text, wid)
            )
            method = "شام كاش" if method_type == "sham" else "USDT (BEP20)"
            try:
                await context.bot.send_message(
                    u,
                    f"✅ تم صرف أرباحك بنجاح!nn"
                    f"💵 المبلغ: {amt}$\n"
                    f"🆔 رقم العملية: { text }\n"
                    f"📌 الطريقة: {method}\n"
                    f"📋 البيانات: `{ data or '' }`",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"User notification failed on payout: {e}")
            clean_user_data(context, ["state", "pay_wid"])
            await update.message.reply_text(f"✅ تم صرف {amt}$ لـ {u}.", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Payout failed: {e}")
            clean_user_data(context, ["state", "pay_wid"])
            await update.message.reply_text("❌ خطأ في المعالجة.", parse_mode="HTML")
        return

    # --- تعديل الإعدادات ---
    if state.startswith(STATE_EDIT_SETTING):
        key = state[len(STATE_EDIT_SETTING):]
        try:
            val = float(text) if key != "subscription_price" else int(text)
            await safe_db_execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, str(val))
            )
            clean_user_data(context, ["state"])
            await update.message.reply_text("✅ تم التعديل.", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ أدخل رقمًا صحيحًا.", parse_mode="HTML")
        return

    # --- تعديل طريقة دفع ---
    if state.startswith(STATE_EDIT_PM):
        try:
            m_id = int(state[len(STATE_EDIT_PM):])
            await safe_db_execute("UPDATE payment_methods SET name = %s WHERE id = %s", (text, m_id))
            clean_user_data(context, ["state"])
            await update.message.reply_text("✅ تم التعديل.", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Edit payment method failed: {e}")
            clean_user_data(context, ["state"])
            await update.message.reply_text("❌ خطأ في الحفظ.", parse_mode="HTML")
        return

    # --- بث جماعي ---
    if state == STATE_BROADCAST:
        clean_user_data(context, ["state"])
        rows = await safe_db_fetchall("SELECT telegram_id FROM users")
        user_ids = [r["telegram_id"] for r in rows]
        total = len(user_ids)
        if total == 0:
            await update.message.reply_text("📭 لا يوجد مستخدمون.", parse_mode="HTML")
            return
        success = 0
        for i in range(0, total, BATCH_SIZE):
            batch = user_ids[i:i + BATCH_SIZE]
            tasks = [context.bot.send_message(uid, text, parse_mode=None) for uid in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success += sum(1 for r in results if not isinstance(r, Exception))
            # توقف عند فشل > 30%
            if i > 0 and success < (i + len(batch)) * 0.7:
                await update.message.reply_text(
                    f"⚠️ توقف مؤقت: نسبة فشل عالية ({success}/{i + len(batch)}).",
                    parse_mode="HTML"
                )
                break
        await update.message.reply_text(f"✅ تم الإرسال إلى {success}/{total} مستخدم.", parse_mode="HTML")
        return

# ---------------- COMMANDS ----------------
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMINS:
        await update.message.reply_text("🛂 لوحة الأدمن", reply_markup=admin_menu())

# ---------------- MAIN ----------------
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, messages))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))
    logger.info("✅ Jetoor Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

