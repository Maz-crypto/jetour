from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from database import init_db, cursor, conn, get_setting, set_setting
from datetime import datetime, timedelta
import logging
import os
from telegram.helpers import escape_markdown

# ✅ قراءة المتغيرات من البيئة
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMINS = [int(x.strip()) for x in os.environ["ADMINS"].split(",") if x.strip()]

init_db()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------- ERROR HANDLER ----------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}", exc_info=True)


# ---------------- MENUS ----------------
def user_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 الاشتراك", callback_data="subscribe")],
        [InlineKeyboardButton("💰 الإحالة", callback_data="referral")],
        [InlineKeyboardButton("📊 رصيدي", callback_data="balance")],
        [InlineKeyboardButton("📤 سحب الأرباح", callback_data="withdraw")],
        [InlineKeyboardButton("🛠️ الدعم", callback_data="support")]
    ])


def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧾 طلبات الاشتراك", callback_data="admin_payments")],
        [InlineKeyboardButton("💸 طلبات السحب", callback_data="admin_withdraws")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="admin_settings")],
        [InlineKeyboardButton("💳 طرق الدفع", callback_data="payment_methods")],
        [InlineKeyboardButton("🔗 إدارة روابط القناة", callback_data="channel_links")],
        [InlineKeyboardButton("📢 رسالة جماعية", callback_data="broadcast")],
        [InlineKeyboardButton("📨 رسالة لمستخدم", callback_data="send_to_user")]
    ])


def confirm_menu(yes="✅ نعم", no="❌ لا", data_yes="confirm_yes", data_no="confirm_no"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(yes, callback_data=data_yes),
         InlineKeyboardButton(no, callback_data=data_no)]
    ])


# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    ref = int(args[0]) if args and args[0].isdigit() else None
    if ref == user.id:
        ref = None

    cursor.execute("""
        INSERT INTO users (telegram_id, username, referrer_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_id) DO NOTHING
    """, (user.id, user.username, ref))
    conn.commit()

    price = get_setting("subscription_price")
    await update.message.reply_text(
        f"🔐 مرحبًا بك في بوت الاشتراك في قناة الأخبار العاجلة\n\n"
        f"📌 اشترك الآن للوصول إلى المحتوى الحصري\n"
        f"💰 اربح عبر رابط الإحالة بعد تفعيل اشتراكك\n\n"
        f"💳 رسوم الاشتراك: **{price}$ أمريكي**\n"
        f"🗓️ المدة: حتى **31 ديسمبر 2026**",
        parse_mode="MarkdownV2",
        reply_markup=user_menu()
    )


# ---------------- CALLBACKS ----------------
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # ---------- USER ----------
    if q.data == "subscribe":
        cursor.execute("SELECT id, name, barcode FROM payment_methods")
        methods = cursor.fetchall()
        if not methods:
            await q.message.reply_text("💳 لا توجد طرق دفع متاحة\\. تواصل مع الدعم\\.")
            return
        buttons = [[InlineKeyboardButton(name, callback_data=f"paymethod_{m_id}")] for m_id, name, _ in methods]
        await q.message.reply_text("💳 اختر طريقة الدفع:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    elif q.data.startswith("paymethod_"):
        method_id = int(q.data.split("_")[1])
        context.user_data["awaiting_payment"] = True
        context.user_data["payment_method_id"] = method_id
        cursor.execute("SELECT name, barcode FROM payment_methods WHERE id = %s", (method_id,))
        row = cursor.fetchone()
        name = row["name"]
        barcode = row["barcode"]
        escaped_name = escape_markdown(name, version=2)
        escaped_barcode = escape_markdown(barcode, version=2)
        await q.message.reply_text(
            f"💵 أرسل **صورة إشعار الدفع** \\(لقطة من تطبيق الدفع\\)\n"
            f"📱 الطريقة: *{escaped_name}*\n"
            f"📎 الرابط: `{escaped_barcode}`",
            parse_mode="MarkdownV2"
        )
        return

    elif q.data == "referral":
        cursor.execute("SELECT subscription_active FROM users WHERE telegram_id = %s", (uid,))
        row = cursor.fetchone()
        active = row["subscription_active"] if row else 0
        if active != 1:
            await q.message.reply_text("❌ يجب أن تكون مشتركًا لتفعيل رابط الإحالة\\.")
            return
        reward = get_setting("referral_reward")
        # ✅ إصلاح الرابط: لا مسافات
        link = f"https://t.me/news_acc_bot?start={uid}"
        escaped_link = escape_markdown(link, version=2)
        await q.message.reply_text(
            f"🔗 رابطك:\n{escaped_link}\n💰 العمولة: {reward}\\$",
            disable_web_page_preview=True,
            parse_mode="MarkdownV2"
        )
        return

    elif q.data == "balance":
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id = %s", (uid,))
        row = cursor.fetchone()
        bal = row["referral_balance"] if row else 0
        await q.message.reply_text(f"💵 رصيدك: {bal}\\$", parse_mode="MarkdownV2")
        return

    elif q.data == "withdraw":
        min_w = get_setting("min_withdraw")
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id = %s", (uid,))
        row = cursor.fetchone()
        bal = row["referral_balance"] if row else 0
        if bal < min_w:
            await q.message.reply_text(
                f"❌ الحد الأدنى للسحب هو {min_w}\\$\\. رصيدك: {bal}\\$\\.",
                parse_mode="MarkdownV2"
            )
        else:
            await q.message.reply_text(
                f"💰 رصيدك جاهز للسحب: {bal}\\$\\n\\nاختر طريقة الاستلام:",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("شام كاش", callback_data="withdraw_sham")],
                    [InlineKeyboardButton("USDT \\(BEP20\\)", callback_data="withdraw_usdt")],
                    [InlineKeyboardButton("إلغاء", callback_data="cancel")]
                ])
            )
        return

    elif q.data == "withdraw_sham":
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id = %s", (uid,))
        row = cursor.fetchone()
        bal = row["referral_balance"] if row else 0
        context.user_data.update({
            "withdraw_method": "sham",
            "withdraw_amount": bal
        })
        await q.message.reply_text(
            "🔢 أرسل **كود شام كاش** لاستلام المبلغ:\n"
            "مثال: `SC123456` أو `123456789`",
            parse_mode="MarkdownV2"
        )
        return

    elif q.data == "withdraw_usdt":
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id = %s", (uid,))
        row = cursor.fetchone()
        bal = row["referral_balance"] if row else 0
        context.user_data.update({
            "withdraw_method": "usdt",
            "withdraw_amount": bal
        })
        await q.message.reply_text(
            "👛 أرسل **محفظة USDT \\(BEP20\\)** لاستلام المبلغ:\n"
            "مثال: `0x123\\.\\.\\.abc`",
            parse_mode="MarkdownV2"
        )
        return

    elif q.data == "support":
        context.user_data["support"] = True
        await q.message.reply_text("✉️ اكتب رسالتك:")
        return

    # ✅ تأكيد السحب من الزر (بدون تكرار)
    elif q.data == "confirm_withdraw":
        await _handle_confirm_withdraw(q, context, uid)
        return

    elif q.data == "edit_withdraw_data":
        method = context.user_data.get("withdraw_method_temp", "sham")
        bal = context.user_data.get("withdraw_amount", 0)
        msg = "أعد إدخال كود شام كاش:" if method == "sham" else "أعد إدخال محفظة USDT \\(BEP20\\):"
        context.user_data["withdraw_method"] = method
        context.user_data.pop("withdraw_data_temp", None)
        await q.message.edit_text(f"{msg}\n💵 المبلغ: {bal}\\$", parse_mode="MarkdownV2")
        return

    # ---------- ADMIN ----------
    if uid not in ADMINS:
        return

    if q.data == "admin_payments":
        cursor.execute("SELECT id, user_id, amount, proof FROM payments WHERE status = 'PENDING'")
        rows = cursor.fetchall()
        if not rows:
            await q.message.reply_text("📭 لا توجد طلبات\\.", parse_mode="MarkdownV2")
            return
        for row in rows:
            pid = row["id"]
            u = row["user_id"]
            amt = row["amount"]
            proof = row["proof"]
            await context.bot.send_photo(
                uid, photo=proof,
                caption=f"🧾 اشتراك #{pid}\n👤 {u}\n💵 {amt}\\$",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅", callback_data=f"approve_{pid}"),
                     InlineKeyboardButton("❌", callback_data=f"reject_{pid}")]
                ])
            )
        return

    elif q.data.startswith("approve_"):
        pid = int(q.data.split("_")[1])
        context.user_data["approve_pid"] = pid
        await q.message.reply_text("🔢 أدخل رقم العملية:")
        return

    elif q.data.startswith("reject_"):
        pid = int(q.data.split("_")[1])
        await q.message.reply_text(
            "⚠️ تأكيد الرفض؟",
            reply_markup=confirm_menu("✅", "❌", f"confirm_reject_{pid}", "cancel")
        )
        return

    elif q.data.startswith("confirm_reject_"):
        pid = int(q.data.split("_")[2])
        cursor.execute("UPDATE payments SET status = 'REJECTED' WHERE id = %s", (pid,))
        conn.commit()
        await q.message.reply_text("❌ تم الرفض\\.", parse_mode="MarkdownV2")
        return

    elif q.data == "admin_withdraws":
        cursor.execute("""
            SELECT id, user_id, amount, sham_cash_link, method
            FROM withdrawals
            WHERE status = 'PENDING'
        """)
        rows = cursor.fetchall()
        if not rows:
            await q.message.reply_text("📭 لا توجد طلبات سحب\\.", parse_mode="MarkdownV2")
            return
        for r in rows:
            wid = r["id"]
            u = r["user_id"]
            amt = r["amount"]
            data = r["sham_cash_link"] or "---"
            method_type = r["method"]
            method = "شام كاش" if method_type == "sham" else "USDT \\(BEP20\\)" if method_type == "usdt" else "غير معروف"
            escaped_data = escape_markdown(data, version=2)
            await q.message.reply_text(
                f"💸 طلب سحب #{wid}\n"
                f"👤 المستخدم: {u}\n"
                f"💵 المبلغ: {amt}\\$\n"
                f"📌 الطريقة: {method}\n"
                f"📋 البيانات: `{escaped_data}`",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ تأكيد", callback_data=f"pay_{wid}"),
                        InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_w_{wid}"),
                        InlineKeyboardButton("ℹ️ استعلام", callback_data=f"inquiry_{u}")
                    ]
                ])
            )
        return

    elif q.data.startswith("inquiry_"):
        try:
            user_id = int(q.data.split("_")[1])
            cursor.execute("SELECT * FROM users WHERE telegram_id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                await q.message.reply_text("❌ المستخدم غير موجود\\.", parse_mode="MarkdownV2")
                return
            tid = user["telegram_id"]
            username = user["username"] or "---"
            referrer = user["referrer_id"] or "---"
            balance = user["referral_balance"]
            active = user["subscription_active"]
            end_date = user["subscription_end"] or "---"
            status = "نشط" if active == 1 else "غير نشط"
            await q.message.reply_text(
                f"ℹ️ استعلام عن المستخدم {tid}:\n"
                f"👤 المعرف: @{escape_markdown(username, version=2)}\n"
                f"💰 الرصيد: {balance}\\$\n"
                f"📌 حالة الاشتراك: {status}\n"
                f"🗓️ انتهاء الاشتراك: {end_date}\n"
                f"👥 المُحيل: {referrer}",
                parse_mode="MarkdownV2"
            )
        except (ValueError, IndexError, KeyError) as e:
            logger.warning(f"Invalid inquiry callback: {q.data}, error: {e}")
            await q.message.reply_text("❌ طلب غير صالح\\.", parse_mode="MarkdownV2")
        return

    elif q.data.startswith("cancel_w_"):
        try:
            wid = int(q.data.split("_")[2])
            await q.message.reply_text(
                "⚠️ تأكيد إلغاء طلب السحب؟",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ نعم", callback_data=f"confirm_cancel_w_{wid}"),
                        InlineKeyboardButton("❌ لا", callback_data="cancel")
                    ]
                ])
            )
        except (ValueError, IndexError):
            await q.message.reply_text("❌ طلب غير صالح\\.", parse_mode="MarkdownV2")
        return

    elif q.data.startswith("confirm_cancel_w_"):
        try:
            wid = int(q.data.split("_")[3])
            cursor.execute("SELECT user_id FROM withdrawals WHERE id = %s", (wid,))
            row = cursor.fetchone()
            if not row:
                await q.message.reply_text("❌ الطلب غير موجود\\.", parse_mode="MarkdownV2")
                return
            u = row["user_id"]
            cursor.execute("UPDATE withdrawals SET status = 'CANCELLED' WHERE id = %s", (wid,))
            conn.commit()
            try:
                await context.bot.send_message(
                    u,
                    "❌ تم إلغاء طلب سحب أرباحك\\. تواصل مع الدعم للمزيد\\.",
                    parse_mode="MarkdownV2"
                )
            except Exception as e:
                logger.warning(f"Failed to notify user {u} on cancel: {e}")
            await q.message.reply_text("✅ تم الإلغاء\\.", parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Error in confirm_cancel_w: {e}")
            await q.message.reply_text("❌ خطأ في المعالجة\\.", parse_mode="MarkdownV2")
        return

    elif q.data.startswith("pay_"):
        try:
            wid = int(q.data.split("_")[1])
            context.user_data["pay_wid"] = wid
            await q.message.reply_text("🔢 أدخل رقم العملية:")
        except (ValueError, IndexError):
            await q.message.reply_text("❌ طلب غير صالح\\.", parse_mode="MarkdownV2")
        return

    elif q.data == "admin_settings":
        p = get_setting("subscription_price")
        r = get_setting("referral_reward")
        m = get_setting("min_withdraw")
        await q.message.reply_text(
            f"⚙️ الإعدادات:\n"
            f"- السعر: {p}\\$\n"
            f"- العمولة: {r}\\$\n"
            f"- الحد الأدنى: {m}\\$",
            parse_mode="MarkdownV2"
        )
        return

    elif q.data == "edit_price":
        context.user_data["edit"] = "subscription_price"
        await q.message.reply_text("أدخل السعر الجديد:")
        return

    elif q.data == "edit_ref":
        context.user_data["edit"] = "referral_reward"
        await q.message.reply_text("أدخل العمولة الجديدة:")
        return

    elif q.data == "edit_min":
        context.user_data["edit"] = "min_withdraw"
        await q.message.reply_text("أدخل الحد الأدنى الجديد:")
        return

    elif q.data == "broadcast":
        context.user_data["broadcast"] = True
        await q.message.reply_text("أرسل الرسالة الجماعية:")
        return

    elif q.data == "payment_methods":
        cursor.execute("SELECT id, name FROM payment_methods")
        methods = cursor.fetchall()
        buttons = [[InlineKeyboardButton("➕ إضافة طريقة دفع", callback_data="add_payment")]]
        for row in methods:
            m_id = row["id"]
            name = row["name"]
            buttons.append([
                InlineKeyboardButton("✏️ تعديل", callback_data=f"edit_pm_{m_id}"),
                InlineKeyboardButton("🗑️ حذف", callback_data=f"del_pm_{m_id}")
            ])
            buttons.append([InlineKeyboardButton(f"💳 {name}", callback_data="cancel")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="cancel")])
        await q.message.reply_text(
            "💳 طرق الدفع المتوفرة:" if methods else "💳 لا توجد طرق دفع مُضافة بعد\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    elif q.data == "add_payment":
        context.user_data["add_payment"] = True
        await q.message.reply_text("✏️ أرسل اسم طريقة الدفع:")
        return

    elif q.data == "channel_links":
        cursor.execute("SELECT id, link FROM channel_links")
        links = cursor.fetchall()
        buttons = [[InlineKeyboardButton("➕ إضافة روابط", callback_data="add_links_bulk")]]
        for row in links:
            lid = row["id"]
            link = row["link"]
            short = (link[:25] + "…") if len(link) > 25 else link
            escaped_short = escape_markdown(short, version=2)
            buttons.append([InlineKeyboardButton(f"🗑️ {escaped_short}", callback_data=f"del_link_{lid}")])
        buttons.append([InlineKeyboardButton("🔙", callback_data="cancel")])
        await q.message.reply_text("🔗 روابط القناة:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    elif q.data == "add_links_bulk":
        context.user_data["expecting_links"] = True
        await q.message.reply_text(
            "📎 أرسل جميع روابط القناة في رسالة واحدة \\(كل رابط في سطر\\):\n\n"
            "مثال:\n`https://t.me/channel1`\n`https://t.me/channel2`",
            parse_mode="MarkdownV2"
        )
        return

    elif q.data == "confirm_add_payment":
        if "tmp_payment" not in context.user_data:
            await q.message.edit_text("❌ بيانات مفقودة\\.", parse_mode="MarkdownV2")
            return
        name, barcode = context.user_data.pop("tmp_payment")
        try:
            cursor.execute(
                "INSERT INTO payment_methods (name, barcode) VALUES (%s, %s)",
                (name, barcode)
            )
            conn.commit()
            await q.message.edit_text("✅ تم الإضافة بنجاح\\!", parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"DB error on add_payment: {e}")
            await q.message.edit_text("❌ خطأ في الحفظ\\.", parse_mode="MarkdownV2")
        return

    elif q.data == "cancel_add_payment":
        context.user_data.pop("tmp_payment", None)
        await q.message.edit_text("❌ تم الإلغاء\\.", parse_mode="MarkdownV2")
        return

    elif q.data.startswith("del_link_"):
        try:
            lid = int(q.data.split("_")[2])
            await q.message.reply_text(
                "⚠️ حذف الرابط؟",
                reply_markup=confirm_menu("✅", "❌", f"confirm_del_link_{lid}", "cancel")
            )
        except (ValueError, IndexError):
            await q.message.reply_text("❌ طلب غير صالح\\.", parse_mode="MarkdownV2")
        return

    elif q.data.startswith("confirm_del_link_"):
        try:
            lid = int(q.data.split("_")[3])
            cursor.execute("DELETE FROM channel_links WHERE id = %s", (lid,))
            conn.commit()
            await q.message.reply_text("✅ تم الحذف\\.", parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"DB error on delete link: {e}")
            await q.message.reply_text("❌ خطأ في الحذف\\.", parse_mode="MarkdownV2")
        return

    elif q.data.startswith("del_pm_"):
        try:
            m_id = int(q.data.split("_")[2])
            await q.message.reply_text(
                "⚠️ حذف الطريقة؟",
                reply_markup=confirm_menu("✅", "❌", f"confirm_del_pm_{m_id}", "cancel")
            )
        except (ValueError, IndexError):
            await q.message.reply_text("❌ طلب غير صالح\\.", parse_mode="MarkdownV2")
        return

    elif q.data.startswith("confirm_del_pm_"):
        try:
            m_id = int(q.data.split("_")[3])
            cursor.execute("DELETE FROM payment_methods WHERE id = %s", (m_id,))
            conn.commit()
            await q.message.reply_text("✅ تم الحذف\\.", parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"DB error on delete payment method: {e}")
            await q.message.reply_text("❌ خطأ في الحذف\\.", parse_mode="MarkdownV2")
        return

    elif q.data.startswith("edit_pm_"):
        try:
            m_id = int(q.data.split("_")[2])
            context.user_data["edit_pm_id"] = m_id
            await q.message.reply_text("أدخل الاسم الجديد:")
        except (ValueError, IndexError):
            await q.message.reply_text("❌ طلب غير صالح\\.", parse_mode="MarkdownV2")
        return

    elif q.data == "send_to_user":
        context.user_data["awaiting_user_id"] = True
        await q.message.reply_text("👤 أرسل معرف المستخدم \\(ID\\):", parse_mode="MarkdownV2")
        return

    elif q.data == "cancel":
        keys_to_clear = [
            "add_payment", "awaiting_payment_link", "new_payment_name", "tmp_payment",
            "edit", "expecting_links", "withdraw_method", "withdraw_amount",
            "withdraw_data_temp", "withdraw_method_temp", "awaiting_user_id", "target_user_id"
        ]
        for k in keys_to_clear:
            context.user_data.pop(k, None)
        await q.message.reply_text("❌ تم الإلغاء\\.", parse_mode="MarkdownV2")
        return


# ---------------- MESSAGES ----------------
async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    uid = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

    # --- دعم المستخدم ---
    if context.user_data.get("support"):
        for admin in ADMINS:
            try:
                await context.bot.send_message(
                    admin,
                    f"📩 دعم من {uid}:\n{text}",
                    parse_mode=None
                )
            except Exception as e:
                logger.warning(f"Failed to send support msg to admin {admin}: {e}")
        context.user_data.pop("support", None)
        await update.message.reply_text("✅ تم الإرسال\\.", parse_mode="MarkdownV2")
        return

    # --- إدخال معرف المستخدم (للرسالة الفردية) ---
    if context.user_data.get("awaiting_user_id") and uid in ADMINS:
        try:
            target_id = int(text.strip())
            context.user_data["target_user_id"] = target_id
            context.user_data.pop("awaiting_user_id", None)
            await update.message.reply_text(
                f"📨 أرسل الرسالة لـ `{target_id}`:",
                parse_mode="MarkdownV2"
            )
        except ValueError:
            await update.message.reply_text("❌ معرف غير صالح\\. أدخل أرقامًا فقط\\.", parse_mode="MarkdownV2")
        return

    # --- إرسال رسالة لمستخدم محدد ---
    if context.user_data.get("target_user_id") and uid in ADMINS:
        target_id = context.user_data["target_user_id"]
        try:
            escaped_text = escape_markdown(text, version=2)
            await context.bot.send_message(
                target_id,
                f"📩 **رسالة من الإدارة**:\n\n{escaped_text}",
                parse_mode="MarkdownV2"
            )
            await update.message.reply_text(f"✅ تم الإرسال إلى `{target_id}`\\.", parse_mode="MarkdownV2")
        except Exception as e:
            err = "❌ فشل الإرسال\\. الأسباب:\n"
            if "bot was blocked" in str(e):
                err += "• المستخدم حظر البوت\n"
            elif "chat not found" in str(e):
                err += "• المعرف خاطئ أو لم يبدأ محادثة\n"
            else:
                err += f"• خطأ غير معروف: {type(e).__name__}"
            logger.warning(f"Failed to send message to {target_id}: {e}")
            await update.message.reply_text(err, parse_mode="MarkdownV2")
        finally:
            context.user_data.pop("target_user_id", None)
        return

    # --- بيانات السحب (من المستخدم) ---
    if context.user_data.get("withdraw_method") in ["sham", "usdt"]:
        method = context.user_data["withdraw_method"]
        bal = context.user_data.get("withdraw_amount", 0)
        data = text.strip()

        # ✅ التحقق من الصحة
        if method == "sham":
            if len(data) < 5 or " " in data or "HTTP" in data.upper():
                await update.message.reply_text("❌ كود شام كاش غير صالح\\. أعد المحاولة\\.", parse_mode="MarkdownV2")
                return
            label = "كود شام كاش"
        else:  # usdt
            if not data.startswith("0x") or len(data) < 10:
                await update.message.reply_text("❌ محفظة USDT غير صالحة\\. يجب أن تبدأ بـ `0x`\\.", parse_mode="MarkdownV2")
                return
            label = "محفظة USDT"

        # ✅ تحقق من طلب معلق
        cursor.execute("SELECT id FROM withdrawals WHERE user_id = %s AND status = 'PENDING'", (uid,))
        if cursor.fetchone():
            await update.message.reply_text("⏳ لديك طلب سحب معلق\\. انتظر معالجته أولًا\\.", parse_mode="MarkdownV2")
            context.user_data.pop("withdraw_method", None)
            return

        # ✅ حفظ مؤقت
        context.user_data.update({
            "withdraw_data_temp": data,
            "withdraw_method_temp": method
        })
        context.user_data.pop("withdraw_method", None)

        method_text = "شام كاش" if method == "sham" else "USDT \\(BEP20\\)"
        escaped_data = escape_markdown(data, version=2)
        await update.message.reply_text(
            f"⚠️ تأكيد طلب السحب:\n"
            f"💵 المبلغ: {bal}\\$\n"
            f"📌 الطريقة: {method_text}\n"
            f"📋 {label}: `{escaped_data}`\n\n"
            f"هل تريد تأكيد الطلب؟",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد", callback_data="confirm_withdraw")],
                [InlineKeyboardButton("❌ تعديل", callback_data="edit_withdraw_data")]
            ])
        )
        return

    # --- إضافة روابط دفعة واحدة ---
    if context.user_data.get("expecting_links") and uid in ADMINS:
        context.user_data.pop("expecting_links", None)
        lines = text.strip().splitlines()
        links = [line.strip() for line in lines if line.strip().startswith("http")]
        if not links:
            await update.message.reply_text("❌ لم يتم العثور على روابط صالحة\\.", parse_mode="MarkdownV2")
            return
        added = 0
        for link in links:
            try:
                cursor.execute("""
                    INSERT INTO channel_links (link)
                    VALUES (%s)
                    ON CONFLICT (link) DO NOTHING
                    RETURNING id
                """, (link,))
                if cursor.fetchone():
                    added += 1
            except Exception as e:
                logger.error(f"Failed to insert link '{link}': {e}")
        conn.commit()
        await update.message.reply_text(f"✅ تم حفظ {added} رابط\\.", parse_mode="MarkdownV2")
        return

    # --- صورة إثبات الدفع ---
    if context.user_data.get("awaiting_payment") and update.message.photo:
        price = get_setting("subscription_price")
        method_id = context.user_data.get("payment_method_id")
        if method_id is None:
            await update.message.reply_text("❌ حدث خطأ\\. يرجى المحاولة من جديد\\.", parse_mode="MarkdownV2")
            context.user_data.pop("awaiting_payment", None)
            return
        file_id = update.message.photo[-1].file_id
        try:
            cursor.execute("""
                INSERT INTO payments (user_id, amount, proof, status, payment_method_id)
                VALUES (%s, %s, %s, 'PENDING', %s)
                RETURNING id
            """, (uid, price, file_id, method_id))
            row = cursor.fetchone()
            pid = row["id"] if row else None
            if not pid:
                raise Exception("No payment ID returned")
            conn.commit()
        except Exception as e:
            logger.error(f"DB error on payment insert: {e}")
            await update.message.reply_text("❌ خطأ في تسجيل الدفع\\.", parse_mode="MarkdownV2")
            return

        context.user_data.pop("awaiting_payment", None)
        context.user_data.pop("payment_method_id", None)
        await update.message.reply_text("📩 تم استلام صورة إشعار الدفع\\.", parse_mode="MarkdownV2")

        for admin in ADMINS:
            try:
                await context.bot.send_photo(
                    admin, photo=file_id,
                    caption=f"طلب اشتراك جديد\\nالمستخدم: {uid}",
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅", callback_data=f"approve_{pid}")],
                        [InlineKeyboardButton("❌", callback_data=f"reject_{pid}")]
                    ])
                )
            except Exception as e:
                logger.warning(f"Failed to notify admin {admin} on new payment: {e}")
        return

    # --- إضافة طريقة دفع: الاسم ---
    if context.user_data.get("add_payment") and uid in ADMINS:
        context.user_data["new_payment_name"] = text
        context.user_data["awaiting_payment_link"] = True
        context.user_data.pop("add_payment", None)
        escaped_name = escape_markdown(text, version=2)
        await update.message.reply_text(
            f"✅ الاسم: *{escaped_name}*\n🔗 أرسل الرابط:",
            parse_mode="MarkdownV2"
        )
        return

    # --- إضافة طريقة دفع: الرابط ---
    if context.user_data.get("awaiting_payment_link") and uid in ADMINS:
        name = context.user_data["new_payment_name"]
        context.user_data["tmp_payment"] = (name, text)
        context.user_data.pop("awaiting_payment_link", None)
        context.user_data.pop("new_payment_name", None)
        escaped_name = escape_markdown(name, version=2)
        escaped_link = escape_markdown(text, version=2)
        await update.message.reply_text(
            f"📛: `{escaped_name}`\n📎: `{escaped_link}`",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد", callback_data="confirm_add_payment")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_add_payment")]
            ])
        )
        return

    # --- الموافقة على الاشتراك (أدخل رقم العملية) ---
    if "approve_pid" in context.user_data and uid in ADMINS:
        pid = context.user_data["approve_pid"]
        try:
            cursor.execute("SELECT user_id FROM payments WHERE id = %s AND status = 'PENDING'", (pid,))
            row = cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ الطلب غير موجود أو مُعالج مسبقًا\\.", parse_mode="MarkdownV2")
                context.user_data.pop("approve_pid", None)
                return
            user_id = row["user_id"]

            cursor.execute("SELECT id, link FROM channel_links ORDER BY id LIMIT 1")
            link_row = cursor.fetchone()
            if not link_row:
                await update.message.reply_text("❌ لا توجد روابط\\. أضف روابط أولًا\\.", parse_mode="MarkdownV2")
                return
            link_id = link_row["id"]
            link = link_row["link"]

            end_date = "2026-12-31"
            cursor.execute(
                "UPDATE payments SET status = 'APPROVED', transaction_id = %s WHERE id = %s",
                (text, pid)
            )
            cursor.execute(
                "UPDATE users SET subscription_active = 1, subscription_end = %s WHERE telegram_id = %s",
                (end_date, user_id)
            )

            cursor.execute("SELECT referrer_id FROM users WHERE telegram_id = %s", (user_id,))
            ref_row = cursor.fetchone()
            ref = ref_row["referrer_id"] if ref_row else None
            if ref:
                cursor.execute("SELECT subscription_active FROM users WHERE telegram_id = %s", (ref,))
                ref_active_row = cursor.fetchone()
                if ref_active_row and ref_active_row["subscription_active"] == 1:
                    reward = get_setting("referral_reward")
                    cursor.execute(
                        "UPDATE users SET referral_balance = referral_balance + %s WHERE telegram_id = %s",
                        (reward, ref)
                    )

            cursor.execute("DELETE FROM channel_links WHERE id = %s", (link_id,))
            conn.commit()

            try:
                await context.bot.send_message(
                    user_id,
                    f"🎉 اشتراكك مفعل\\!\nالرابط:\n{escape_markdown(link, version=2)}",
                    parse_mode="MarkdownV2"
                )
            except Exception as e:
                logger.warning(f"Failed to send link to user {user_id}: {e}")

            await update.message.reply_text(f"✅ تم تفعيل الاشتراك لـ {user_id}\\.", parse_mode="MarkdownV2")
            context.user_data.pop("approve_pid", None)
            return
        except Exception as e:
            logger.error(f"Error in approve: {e}")
            await update.message.reply_text("❌ خطأ في المعالجة\\.", parse_mode="MarkdownV2")
            context.user_data.pop("approve_pid", None)
            return

    # --- صرف السحب (أدخل رقم العملية) ---
    if "pay_wid" in context.user_data and uid in ADMINS:
        wid = context.user_data["pay_wid"]
        try:
            cursor.execute("""
                SELECT user_id, amount, sham_cash_link, method
                FROM withdrawals
                WHERE id = %s
            """, (wid,))
            row = cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ طلب السحب غير موجود\\.", parse_mode="MarkdownV2")
                context.user_data.pop("pay_wid", None)
                return
            u = row["user_id"]
            amt = row["amount"]
            data = row["sham_cash_link"]
            method_type = row["method"]
            method = "شام كاش" if method_type == "sham" else "USDT \\(BEP20\\)"

            cursor.execute("UPDATE users SET referral_balance = 0 WHERE telegram_id = %s", (u,))
            cursor.execute(
                "UPDATE withdrawals SET status = 'PAID', transaction_id = %s WHERE id = %s",
                (text, wid)
            )
            conn.commit()

            escaped_data = escape_markdown(data or "", version=2)
            try:
                await context.bot.send_message(
                    u,
                    f"✅ تم صرف أرباحك بنجاح\\!\\n\\n"
                    f"💵 المبلغ: {amt}\\$\n"
                    f"🆔 رقم العملية: {escape_markdown(text, version=2)}\n"
                    f"📌 الطريقة: {method}\n"
                    f"📋 البيانات: `{escaped_data}`",
                    parse_mode="MarkdownV2"
                )
            except Exception as e:
                logger.warning(f"Failed to notify user {u} on withdrawal payout: {e}")

            await update.message.reply_text(f"✅ تم صرف {amt}\\$ لـ {u}\\.", parse_mode="MarkdownV2")
            context.user_data.pop("pay_wid", None)
            return
        except Exception as e:
            logger.error(f"Error in pay_wid: {e}")
            await update.message.reply_text("❌ خطأ في المعالجة\\.", parse_mode="MarkdownV2")
            context.user_data.pop("pay_wid", None)
            return

    # --- تعديل الإعدادات ---
    if "edit" in context.user_data and uid in ADMINS:
        key = context.user_data["edit"]
        try:
            val = float(text) if key != "subscription_price" else int(text)
            set_setting(key, val)
            context.user_data.pop("edit")
            await update.message.reply_text("✅ تم التعديل\\.", parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text("❌ أدخل رقمًا صحيحًا\\.", parse_mode="MarkdownV2")
        return

    # --- تعديل طريقة دفع ---
    if "edit_pm_id" in context.user_data and uid in ADMINS:
        m_id = context.user_data["edit_pm_id"]
        try:
            cursor.execute("UPDATE payment_methods SET name = %s WHERE id = %s", (text, m_id))
            conn.commit()
            context.user_data.pop("edit_pm_id")
            await update.message.reply_text("✅ تم التعديل\\.", parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"DB error on edit payment method: {e}")
            await update.message.reply_text("❌ خطأ في الحفظ\\.", parse_mode="MarkdownV2")
        return

    # --- رسالة جماعية ---
    if context.user_data.get("broadcast") and uid in ADMINS:
        cursor.execute("SELECT telegram_id FROM users")
        users = cursor.fetchall()
        success = 0
        for row in users:
            try:
                await context.bot.send_message(row["telegram_id"], text)
                success += 1
            except Exception as e:
                logger.debug(f"Broadcast failed to {row['telegram_id']}: {e}")
        context.user_data.pop("broadcast", None)
        await update.message.reply_text(f"✅ تم الإرسال إلى {success} مستخدم\\.", parse_mode="MarkdownV2")
        return


# ---------------- HELPER: تأكيد السحب ----------------
async def _handle_confirm_withdraw(q, context, uid):
    data = context.user_data.get("withdraw_data_temp")
    method = context.user_data.get("withdraw_method_temp")
    bal = context.user_data.get("withdraw_amount", 0)

    if not data or not method:
        await q.message.edit_text("❌ بيانات مفقودة\\.", parse_mode="MarkdownV2")
        return

    try:
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id = %s", (uid,))
        row = cursor.fetchone()
        current_bal = row["referral_balance"] if row else 0
        if bal != current_bal:
            await q.message.edit_text("❌ تغير الرصيد\\. أعد المحاولة\\.", parse_mode="MarkdownV2")
            return

        method_type = "sham" if method == "sham" else "usdt"
        cursor.execute("""
            INSERT INTO withdrawals (user_id, amount, sham_cash_link, method, status)
            VALUES (%s, %s, %s, %s, 'PENDING')
            RETURNING id
        """, (uid, bal, data, method_type))
        row = cursor.fetchone()
        wid = row["id"] if row else None
        if not wid:
            raise Exception("No withdrawal ID returned")
        conn.commit()

        # ✅ تنظيف الـ user_data
        context.user_data.pop("withdraw_data_temp", None)
        context.user_data.pop("withdraw_method_temp", None)
        context.user_data.pop("withdraw_amount", None)

        # ✅ إعلام المستخدم
        await q.message.edit_text(f"✅ تم إرسال طلب السحب #{wid} للأدمن\\.", parse_mode="MarkdownV2")

        # ✅ إعلام الأدمن
        method_text = "شام كاش" if method == "sham" else "USDT \\(BEP20\\)"
        escaped_data = escape_markdown(data, version=2)
        for admin in ADMINS:
            try:
                await context.bot.send_message(
                    admin,
                    f"💸 طلب سحب جديد #{wid}\n"
                    f"👤 المستخدم: {uid}\n"
                    f"💵 المبلغ: {bal}\\$\n"
                    f"📌 الطريقة: {method_text}\n"
                    f"📋 البيانات: `{escaped_data}`",
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأكيد", callback_data=f"pay_{wid}")],
                        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_w_{wid}")],
                        [InlineKeyboardButton("ℹ️ استعلام", callback_data=f"inquiry_{uid}")]
                    ])
                )
            except Exception as e:
                logger.warning(f"Failed to notify admin {admin} on new withdrawal: {e}")

    except Exception as e:
        logger.error(f"Error in _handle_confirm_withdraw: {e}")
        await q.message.edit_text("❌ خطأ في معالجة الطلب\\.", parse_mode="MarkdownV2")


# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", lambda u, c:
        u.message.reply_text("🛂 الأدمن", reply_markup=admin_menu()) if u.effective_user.id in ADMINS else None))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, messages))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))

    logger.info("✅ البوت جاهز...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
