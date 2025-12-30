from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from database import init_db, cursor, conn, get_setting, set_setting
from datetime import datetime, timedelta
import logging
import os  # ✅ جديد

# ✅ قراءة المتغيرات من البيئة (بدون config.py)
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMINS = [int(x.strip()) for x in os.environ["ADMINS"].split(",") if x.strip()]

init_db()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
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
    return InlineKeyboardMarkup([[InlineKeyboardButton(yes, callback_data=data_yes),
                                   InlineKeyboardButton(no, callback_data=data_no)]])

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    ref = int(args[0]) if args and args[0].isdigit() else None
    if ref == user.id:
        ref = None
    cursor.execute(
        "INSERT OR IGNORE INTO users (telegram_id, username, referrer_id) VALUES (?,?,?)",
        (user.id, user.username, ref)
    )
    conn.commit()

    price = get_setting("subscription_price")
    await update.message.reply_text(
        f"🔐 مرحبًا بك في بوت الاشتراك في قناة الأخبار العاجلة\n\n"
        f"📌 اشترك الآن للوصول إلى المحتوى الحصري\n"
        f"💰 اربح عبر رابط الإحالة بعد تفعيل اشتراكك\n\n"
        f"💳 رسوم الاشتراك: **{price}$ أمريكي**\n"
        f"🗓️ المدة: حتى **31 ديسمبر 2026**",
        parse_mode="Markdown",
        reply_markup=user_menu()
    )

## ---------------- CALLBACKS ----------------
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # ---------- USER ----------
    if q.data == "subscribe":
        cursor.execute("SELECT id,name,barcode FROM payment_methods")
        methods = cursor.fetchall()
        if not methods:
            await q.message.reply_text("💳 لا توجد طرق دفع متاحة. تواصل مع الدعم.")
            return
        buttons = [[InlineKeyboardButton(name, callback_data=f"paymethod_{m_id}")] for m_id, name, _ in methods]
        await q.message.reply_text("💳 اختر طريقة الدفع:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    elif q.data.startswith("paymethod_"):
        method_id = int(q.data.split("_")[1])
        context.user_data["awaiting_payment"] = True
        context.user_data["payment_method_id"] = method_id
        cursor.execute("SELECT name,barcode FROM payment_methods WHERE id=?", (method_id,))
        name, barcode = cursor.fetchone()
        await q.message.reply_text(
            f"💵 أرسل **صورة إشعار الدفع** (لقطة من تطبيق الدفع)\n"
            f"📱 الطريقة: *{name}*\n"
            f"📎 الرابط: `{barcode}`",
            parse_mode="Markdown"
        )
        return

    elif q.data == "referral":
        cursor.execute("SELECT subscription_active FROM users WHERE telegram_id=?", (uid,))
        active = cursor.fetchone()[0]
        if active != 1:
            await q.message.reply_text("❌ يجب أن تكون مشتركًا لتفعيل رابط الإحالة.")
            return
        reward = get_setting("referral_reward")
        link = f"https://t.me/news_acc_bot?start={uid}"  # ✅ تم التصحيح: لا مسافة
        await q.message.reply_text(
            f"🔗 رابطك:\n{link}\n💰 العمولة: {reward}$",
            disable_web_page_preview=True
        )
        return

    elif q.data == "balance":
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id=?", (uid,))
        bal = cursor.fetchone()[0]
        await q.message.reply_text(f"💵 رصيدك: {bal}$")
        return

    # ✅ --- سحب الأرباح: اختيار الطريقة ---
    elif q.data == "withdraw":
        min_w = get_setting("min_withdraw")
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id=?", (uid,))
        bal = cursor.fetchone()[0]
        if bal < min_w:
            await q.message.reply_text(f"❌ الحد الأدنى للسحب هو {min_w}$. رصيدك: {bal}$.")
        else:
            await q.message.reply_text(
                f"💰 رصيدك جاهز للسحب: {bal}$\n\n"
                "اختر طريقة الاستلام:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("شام كاش", callback_data="withdraw_sham")],
                    [InlineKeyboardButton("USDT (BEP20)", callback_data="withdraw_usdt")],
                    [InlineKeyboardButton("إلغاء", callback_data="cancel")]
                ])
            )
        return

    # --- شام كاش ---
    elif q.data == "withdraw_sham":
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id=?", (uid,))
        bal = cursor.fetchone()[0]
        context.user_data["withdraw_method"] = "sham"
        context.user_data["withdraw_amount"] = bal
        await q.message.reply_text(
            "🔢 أرسل **كود شام كاش** لاستلام المبلغ:\n"
            "مثال: `SC123456` أو `123456789`"
        )
        return

    # --- USDT (BEP20) ---
    elif q.data == "withdraw_usdt":
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id=?", (uid,))
        bal = cursor.fetchone()[0]
        context.user_data["withdraw_method"] = "usdt"
        context.user_data["withdraw_amount"] = bal
        await q.message.reply_text(
            "👛 أرسل **محفظة USDT (BEP20)** لاستلام المبلغ:\n"
            "مثال: `0x123...abc`"
        )
        return

    elif q.data == "support":
        context.user_data["support"] = True
        await q.message.reply_text("✉️ اكتب رسالتك:")
        return

    # ✅ --- تأكيد طلب السحب (من المستخدم) ---
    elif q.data == "confirm_withdraw":
        uid = q.from_user.id
        data = context.user_data.get("withdraw_data_temp")
        method = context.user_data.get("withdraw_method_temp")
        if not data or not method:
            await q.message.edit_text("❌ بيانات مفقودة. يرجى المحاولة من جديد.")
            return

        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id=?", (uid,))
        bal = cursor.fetchone()[0]

            # ✅ حفظ نوع الطريقة (sham أو usdt)
        method_type = "sham" if method == "sham" else "usdt"
        cursor.execute("""
                INSERT INTO withdrawals (user_id, amount, sham_cash_link, method, status) 
                VALUES (?, ?, ?, ?, 'PENDING')
            """, (uid, bal, data, method_type))

        conn.commit()
        wid = cursor.lastrowid

        context.user_data.pop("withdraw_data_temp", None)
        context.user_data.pop("withdraw_method_temp", None)
        context.user_data.pop("withdraw_amount", None)

        await q.message.edit_text(f"✅ تم إرسال طلب السحب #{wid} للأدمن.")

        method_text = "شام كاش" if method == "sham" else "USDT (BEP20)"
        for admin in ADMINS:
            try:
                await context.bot.send_message(
                    admin,
                    f"💸 طلب سحب جديد #{wid}\n"
                    f"👤 المستخدم: {uid}\n"
                    f"💵 المبلغ: {bal}$\n"
                    f"📌 الطريقة: {method_text}\n"
                    f"📋 البيانات: `{data}`",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأكيد", callback_data=f"pay_{wid}")],
                        [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_w_{wid}")],
                        [InlineKeyboardButton("ℹ️ استعلام", callback_data=f"inquiry_{uid}")]
                    ])
                )
            except:
                pass
        return

    # ✅ --- تعديل طلب السحب (من المستخدم) ---
    elif q.data == "edit_withdraw_data":
        method = context.user_data.get("withdraw_method_temp", "sham")
        bal = context.user_data.get("withdraw_amount", 0)
        
        if method == "sham":
            msg = "🔢 أعد إدخال كود شام كاش:"
        else:
            msg = "👛 أعد إدخال محفظة USDT (BEP20):"
            
        context.user_data["withdraw_method"] = method
        context.user_data.pop("withdraw_data_temp", None)
        await q.message.edit_text(f"{msg}\n💵 المبلغ: {bal}$")
        return
    

    # ---------- ADMIN ----------
    if uid in ADMINS:
        if q.data == "admin_payments":
            cursor.execute("SELECT id,user_id,amount,proof FROM payments WHERE status='PENDING'")
            rows = cursor.fetchall()
            if not rows:
                await q.message.reply_text("📭 لا توجد طلبات.")
                return
            for pid, u, amt, proof in rows:
                await context.bot.send_photo(
                    uid, photo=proof,
                    caption=f"🧾 اشتراك #{pid}\n👤 {u}\n💵 {amt}$",
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
            await q.message.reply_text("⚠️ تأكيد الرفض؟", reply_markup=confirm_menu("✅", "❌", f"confirm_reject_{pid}", "cancel"))
            return

        elif q.data.startswith("confirm_reject_"):
            pid = int(q.data.split("_")[2])
            cursor.execute("UPDATE payments SET status='REJECTED' WHERE id=?", (pid,))
            conn.commit()
            await q.message.reply_text("❌ تم الرفض.")
            return

        # ✅ --- عرض طلبات السحب مع تمييز الطريقة ---
        # ✅ --- عرض طلبات السحب مع تمييز الطريقة ---
        elif q.data == "admin_withdraws":
            cursor.execute("SELECT id,user_id,amount,sham_cash_link,method FROM withdrawals WHERE status='PENDING'")
            rows = cursor.fetchall()
            if not rows:
                await q.message.reply_text("📭 لا توجد طلبات سحب.")
                return
            for wid, u, amt, data, method_type in rows:
                cursor.execute("SELECT referral_balance FROM users WHERE telegram_id=?", (u,))
                bal = cursor.fetchone()[0]
                
                # ✅ تحديد الطريقة حسب اختيار المستخدم
                method = "شام كاش" if method_type == "sham" else "USDT (BEP20)" if method_type == "usdt" else "غير معروف"
                
                await q.message.reply_text(
                    f"💸 طلب سحب #{wid}\n"
                    f"👤 المستخدم: {u}\n"
                    f"💵 المبلغ: {amt}$\n"
                    f"📊 رصيده الحالي: {bal}$\n"
                    f"📌 الطريقة: {method}\n"
                    f"📋 البيانات: `{data or '---'}`",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ تأكيد", callback_data=f"pay_{wid}"),
                            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_w_{wid}"),
                            InlineKeyboardButton("ℹ️ استعلام", callback_data=f"inquiry_{u}")
                        ]
                    ])
                )
            return

        # ✅ --- استعلام عن المستخدم ---
        elif q.data.startswith("inquiry_"):
            user_id = int(q.data.split("_")[1])
            cursor.execute("SELECT * FROM users WHERE telegram_id=?", (user_id,))
            user = cursor.fetchone()
            if not user:
                await q.message.reply_text("❌ المستخدم غير موجود.")
                return
            _, tid, username, referrer, balance, active, end_date, _ = user
            status = "نشط" if active == 1 else "غير نشط"
            await q.message.reply_text(
                f"ℹ️ استعلام عن المستخدم {tid}:\n"
                f"👤 المعرف: @{username or '---'}\n"
                f"💰 الرصيد: {balance}$\n"
                f"📌 حالة الاشتراك: {status}\n"
                f"🗓️ انتهاء الاشتراك: {end_date or '---'}\n"
                f"👥 المُحيل: {referrer or '---'}"
            )
            return

        # ✅ --- إلغاء طلب السحب ---
        elif q.data.startswith("cancel_w_"):
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
            return

        elif q.data.startswith("confirm_cancel_w_"):
            wid = int(q.data.split("_")[3])
            cursor.execute("SELECT user_id FROM withdrawals WHERE id=?", (wid,))
            u = cursor.fetchone()[0]
            cursor.execute("UPDATE withdrawals SET status='CANCELLED' WHERE id=?", (wid,))
            conn.commit()
            try:
                await context.bot.send_message(u, "❌ تم إلغاء طلب سحب أرباحك. تواصل مع الدعم للمزيد.")
            except:
                pass
            await q.message.reply_text("✅ تم إلغاء الطلب.")
            return

        elif q.data.startswith("pay_"):
            wid = int(q.data.split("_")[1])
            context.user_data["pay_wid"] = wid
            await q.message.reply_text("🔢 أدخل رقم العملية:")
            return  # ← لا تنسَ هذا

        elif q.data == "admin_settings":
            p = get_setting("subscription_price")
            r = get_setting("referral_reward")
            m = get_setting("min_withdraw")
            await q.message.reply_text(
                f"⚙️ الإعدادات:\n- السعر: {p}$\n- العمولة: {r}$\n- الحد الأدنى: {m}$",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ سعر", callback_data="edit_price")],
                    [InlineKeyboardButton("✏️ عمولة", callback_data="edit_ref")],
                    [InlineKeyboardButton("✏️ حد السحب", callback_data="edit_min")]
                ])
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
            
            # ✅ الزر يظهر دائمًا — حتى لو لم تكن هناك طرق
            buttons = [[InlineKeyboardButton("➕ إضافة طريقة دفع", callback_data="add_payment")]]
            
            for m_id, name in methods:
                buttons.append([
                    InlineKeyboardButton("✏️ تعديل", callback_data=f"edit_pm_{m_id}"),
                    InlineKeyboardButton("🗑️ حذف", callback_data=f"del_pm_{m_id}")
                ])
                buttons.append([
                    InlineKeyboardButton(f"💳 {name}", callback_data="cancel")
                ])
            
            buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="cancel")])
            
            await q.message.reply_text(
                "💳 طرق الدفع المتوفرة:" if methods else "💳 لا توجد طرق دفع مُضافة بعد.",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return
        elif q.data == "add_payment":
            context.user_data["add_payment"] = True
            await q.message.reply_text("✏️ أرسل اسم طريقة الدفع:")
            return

        elif q.data == "channel_links":
            cursor.execute("SELECT id,link FROM channel_links")
            links = cursor.fetchall()
            buttons = [[InlineKeyboardButton("➕ إضافة روابط", callback_data="add_links_bulk")]]
            for lid, link in links:
                short = link[:25] + "..." if len(link) > 25 else link
                buttons.append([InlineKeyboardButton(f"🗑️ {short}", callback_data=f"del_link_{lid}")])
            buttons.append([InlineKeyboardButton("🔙", callback_data="cancel")])
            await q.message.reply_text("🔗 روابط القناة:", reply_markup=InlineKeyboardMarkup(buttons))
            return

        elif q.data == "add_links_bulk":
            context.user_data["expecting_links"] = True
            await q.message.reply_text(
                "📎 أرسل جميع روابط القناة في رسالة واحدة (كل رابط في سطر):\n\n"
                "مثال:\nhttps://t.me/channel1\nhttps://t.me/channel2"
            )
            return

        elif q.data == "confirm_add_payment":
            if "tmp_payment" not in context.user_data:
                await q.message.edit_text("❌ بيانات مفقودة.")
                return
            name, barcode = context.user_data.pop("tmp_payment")
            try:
                cursor.execute("INSERT INTO payment_methods (name, barcode) VALUES (?, ?)", (name, barcode))
                conn.commit()
                await q.message.edit_text("✅ تم الإضافة بنجاح!")
            except Exception as e:
                logger.error(f"Database error: {e}")
                await q.message.edit_text("❌ خطأ في الحفظ.")
            return

        elif q.data == "cancel_add_payment":
            context.user_data.pop("tmp_payment", None)
            await q.message.edit_text("❌ تم الإلغاء.")
            return

        elif q.data.startswith("del_link_"):
            lid = int(q.data.split("_")[2])
            await q.message.reply_text("⚠️ حذف الرابط؟", reply_markup=confirm_menu("✅", "❌", f"confirm_del_link_{lid}", "cancel"))
            return

        elif q.data.startswith("confirm_del_link_"):
            lid = int(q.data.split("_")[3])
            cursor.execute("DELETE FROM channel_links WHERE id=?", (lid,))
            conn.commit()
            await q.message.reply_text("✅ تم الحذف.")
            return

        elif q.data.startswith("del_pm_"):
            m_id = int(q.data.split("_")[2])
            await q.message.reply_text("⚠️ حذف الطريقة؟", reply_markup=confirm_menu("✅", "❌", f"confirm_del_pm_{m_id}", "cancel"))
            return

        elif q.data.startswith("confirm_del_pm_"):
            m_id = int(q.data.split("_")[3])
            cursor.execute("DELETE FROM payment_methods WHERE id=?", (m_id,))
            conn.commit()
            await q.message.reply_text("✅ تم الحذف.")
            return

        elif q.data.startswith("edit_pm_"):
            m_id = int(q.data.split("_")[2])
            context.user_data["edit_pm_id"] = m_id
            await q.message.reply_text("أدخل الاسم الجديد:")
            return


         # ✅ --- إرسال رسالة لمستخدم محدد ---
        elif q.data == "send_to_user":
            context.user_data["awaiting_user_id"] = True
            await q.message.reply_text("👤 أرسل معرف المستخدم (ID):")
            return
        

        elif q.data == "cancel":
            keys = ["add_payment", "awaiting_payment_link", "new_payment_name", "tmp_payment", "edit", 
                    "expecting_links", "withdraw_method", "withdraw_amount", 
                    "withdraw_data_temp", "withdraw_method_temp",
                    # ✅ أضف هذين المتغيرين:
                    "awaiting_user_id", "target_user_id"]
            for k in keys:
                context.user_data.pop(k, None)
            await q.message.reply_text("❌ تم الإلغاء.")
            return
        

# ---------------- MESSAGES ----------------
async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    uid = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

        # ✅ --- 1. إدخال معرف المستخدم ---
    if context.user_data.get("awaiting_user_id") and uid in ADMINS:
        try:
            target_id = int(text.strip())
            context.user_data["target_user_id"] = target_id
            context.user_data.pop("awaiting_user_id", None)
            await update.message.reply_text(f"📨 أرسل الرسالة لـ `{target_id}`:")
        except ValueError:
            await update.message.reply_text("❌ معرف غير صالح. أدخل أرقامًا فقط.")
        return

    # ✅ --- 2. إرسال الرسالة للمستخدم ---
    if context.user_data.get("target_user_id") and uid in ADMINS:
        target_id = context.user_data["target_user_id"]
        try:
            await context.bot.send_message(target_id, f"📩 **رسالة من الإدارة**:\n\n{text}", parse_mode="Markdown")
            await update.message.reply_text(f"✅ تم الإرسال إلى `{target_id}`.")
        except Exception as e:
            error_msg = "❌ فشل الإرسال. الأسباب:\n"
            if "bot was blocked" in str(e):
                error_msg += "• المستخدم حظر البوت\n"
            if "chat not found" in str(e):
                error_msg += "• المعرف خاطئ أو المستخدم لم يبدأ محادثة\n"
            await update.message.reply_text(error_msg)
        finally:
            context.user_data.pop("target_user_id", None)
        return

    # ✅ --- إدخال بيانات السحب (شام كاش أو USDT) ---
    if context.user_data.get("withdraw_method") in ["sham", "usdt"]:
        method = context.user_data["withdraw_method"]
        bal = context.user_data.get("withdraw_amount", 0)
        data = text.strip()

        # ✅ تحقق من الصحة
        if method == "sham":
            if len(data) < 5 or ' ' in data or 'HTTP' in data.upper():
                await update.message.reply_text("❌ كود شام كاش غير صالح. أعد المحاولة.")
                return
            label = "كود شام كاش"
        else:  # usdt
            if not data.startswith("0x") or len(data) < 10:
                await update.message.reply_text("❌ محفظة USDT غير صالحة. يجب أن تبدأ بـ `0x`.")
                return
            label = "محفظة USDT"

        # ✅ تحقق من طلب معلق
        cursor.execute("SELECT id FROM withdrawals WHERE user_id=? AND status='PENDING'", (uid,))
        if cursor.fetchone():
            await update.message.reply_text("⏳ لديك طلب سحب معلق. انتظر معالجته أولًا.")
            context.user_data.pop("withdraw_method", None)
            return

        # ✅ حفظ مؤقت + تأكيد
        context.user_data.update({
            "withdraw_data_temp": data,
            "withdraw_method_temp": method
        })
        context.user_data.pop("withdraw_method", None)

        await update.message.reply_text(
            f"⚠️ تأكيد طلب السحب:\n"
            f"💵 المبلغ: {bal}$\n"
            f"📌 الطريقة: {'شام كاش' if method == 'sham' else 'USDT (BEP20)'}\n"
            f"📋 {label}: `{data}`\n\n"
            f"هل تريد تأكيد الطلب؟",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد", callback_data="confirm_withdraw")],
                [InlineKeyboardButton("❌ تعديل", callback_data="edit_withdraw_data")]
            ])
        )
        return

    # --- تأكيد الطلب ---
    if update.callback_query and update.callback_query.data == "confirm_withdraw":
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id

        data = context.user_data.get("withdraw_data_temp")
        method = context.user_data.get("withdraw_method_temp")
        if not data or not method:
            await q.message.edit_text("❌ بيانات مفقودة.")
            return

        # جلب الرصيد
        cursor.execute("SELECT referral_balance FROM users WHERE telegram_id=?", (uid,))
        bal = cursor.fetchone()[0]

        # ✅ حفظ الطلب
        cursor.execute("""
            INSERT INTO withdrawals (user_id, amount, sham_cash_link, status) 
            VALUES (?, ?, ?, 'PENDING')
        """, (uid, bal, data))
        conn.commit()
        wid = cursor.lastrowid

        context.user_data.pop("withdraw_data_temp", None)
        context.user_data.pop("withdraw_method_temp", None)

        await q.message.edit_text(f"✅ تم إرسال طلب السحب #{wid} للأدمن.")

        # إشعار الأدمن
        method_text = "شام كاش" if method == "sham" else "USDT (BEP20)"
        for admin in ADMINS:
            try:
                await context.bot.send_message(
                    admin,
                    f"💸 طلب سحب جديد #{wid}\n"
                    f"👤 المستخدم: {uid}\n"
                    f"💵 المبلغ: {bal}$\n"
                    f"📌 الطريقة: {method_text}\n"
                    f"📋 البيانات: `{data}`",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ تأكيد", callback_data=f"pay_{wid}"),
                            InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_w_{wid}"),
                            InlineKeyboardButton("ℹ️ استعلام", callback_data=f"inquiry_{uid}")
                        ]
                    ])
                )
            except Exception as e:
                logger.warning(f"فشل إرسال إشعار سحب: {e}")
        return

    # --- تعديل البيانات ---
    if update.callback_query and update.callback_query.data == "edit_withdraw_data":
        q = update.callback_query
        await q.answer()
        method = context.user_data.get("withdraw_method_temp", "sham")
        bal = context.user_data.get("withdraw_amount", 0)
        
        if method == "sham":
            msg = "أعد إدخال كود شام كاش:"
        else:
            msg = "أعد إدخال محفظة USDT (BEP20):"
            
        context.user_data["withdraw_method"] = method
        context.user_data.pop("withdraw_data_temp", None)
        await q.message.edit_text(f"{msg}\n💵 المبلغ: {bal}$")
        return

    # --- 2. إضافة روابط دفعة واحدة ---
    if context.user_data.get("expecting_links") and uid in ADMINS:
        context.user_data.pop("expecting_links", None)
        lines = text.strip().splitlines()
        links = [line.strip() for line in lines if line.strip() and line.strip().startswith("http")]
        if not links:
            await update.message.reply_text("❌ لم يتم العثور على روابط صالحة.")
            return
        added = 0
        for link in links:
            try:
                cursor.execute("INSERT OR IGNORE INTO channel_links (link) VALUES (?)", (link,))
                added += 1
            except Exception as e:
                logger.error(f"فشل إدخال الرابط: {e}")
        conn.commit()
        await update.message.reply_text(f"✅ تم حفظ {added} رابط.")
        return

    # --- 3. إثبات الدفع (صورة) ---
    if context.user_data.get("awaiting_payment") and update.message.photo:
        price = get_setting("subscription_price")
        method_id = context.user_data.get("payment_method_id")
        if method_id is None:
            await update.message.reply_text("❌ حدث خطأ. يرجى المحاولة من جديد.")
            context.user_data.pop("awaiting_payment", None)
            return
        file_id = update.message.photo[-1].file_id
        cursor.execute("""
            INSERT INTO payments (user_id, amount, proof, status, payment_method_id)
            VALUES (?, ?, ?, 'PENDING', ?)
        """, (uid, price, file_id, method_id))
        conn.commit()
        pid = cursor.lastrowid
        context.user_data.pop("awaiting_payment", None)
        context.user_data.pop("payment_method_id", None)
        await update.message.reply_text("📩 تم استلام صورة إشعار الدفع.")
        for admin in ADMINS:
            try:
                await context.bot.send_photo(
                    admin, photo=file_id,
                    caption=f"طلب اشتراك جديد\nالمستخدم: {uid}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅", callback_data=f"approve_{pid}"),
                         InlineKeyboardButton("❌", callback_data=f"reject_{pid}")]
                    ])
                )
            except:
                pass
        return

    # --- 4. إضافة طريقة دفع: الاسم ---
    if context.user_data.get("add_payment") and uid in ADMINS:
        context.user_data["new_payment_name"] = text
        context.user_data["awaiting_payment_link"] = True
        context.user_data.pop("add_payment", None)
        await update.message.reply_text(f"✅ الاسم: *{text}*\n🔗 أرسل الرابط:", parse_mode="Markdown")
        return

    # --- 5. إضافة طريقة دفع: الرابط ---
    if context.user_data.get("awaiting_payment_link") and uid in ADMINS:
        name = context.user_data["new_payment_name"]
        context.user_data["tmp_payment"] = (name, text)
        context.user_data.pop("awaiting_payment_link", None)
        context.user_data.pop("new_payment_name", None)
        await update.message.reply_text(
            f"📛: `{name}`\n📎: `{text}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد", callback_data="confirm_add_payment"),
                 InlineKeyboardButton("❌ إلغاء", callback_data="cancel_add_payment")]
            ])
        )
        return

    # --- 6. الموافقة على الاشتراك ---
    if "approve_pid" in context.user_data and uid in ADMINS:
        pid = context.user_data["approve_pid"]
        try:
            cursor.execute("SELECT user_id FROM payments WHERE id = ? AND status = 'PENDING'", (pid,))
            row = cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ الطلب غير موجود أو مُعالج مسبقًا.")
                context.user_data.pop("approve_pid", None)
                return
            user_id = row[0]

            cursor.execute("SELECT id, link FROM channel_links ORDER BY id LIMIT 1")
            link_row = cursor.fetchone()
            if not link_row:
                await update.message.reply_text("❌ لا توجد روابط. أضف روابط أولًا.")
                return
            link_id, link = link_row

            end_date = "2026-12-31"
            cursor.execute("UPDATE payments SET status = 'APPROVED', transaction_id = ? WHERE id = ?", (text, pid))
            cursor.execute("UPDATE users SET subscription_active = 1, subscription_end = ? WHERE telegram_id = ?", (end_date, user_id))

            cursor.execute("SELECT referrer_id FROM users WHERE telegram_id = ?", (user_id,))
            ref = cursor.fetchone()[0]
            if ref:
                cursor.execute("SELECT subscription_active FROM users WHERE telegram_id = ?", (ref,))
                if cursor.fetchone()[0] == 1:
                    reward = get_setting("referral_reward")
                    cursor.execute("UPDATE users SET referral_balance = referral_balance + ? WHERE telegram_id = ?", (reward, ref))

            cursor.execute("DELETE FROM channel_links WHERE id = ?", (link_id,))
            conn.commit()

            try:
                await context.bot.send_message(user_id, f"🎉 اشتراكك مفعل!\nالرابط:\n{link}")
            except:
                pass
            await update.message.reply_text(f"✅ تم تفعيل الاشتراك لـ {user_id}.")
            context.user_data.pop("approve_pid", None)
            return
        except Exception as e:
            logger.error(f"خطأ في الموافقة: {e}")
            await update.message.reply_text("❌ خطأ في المعالجة.")
            context.user_data.pop("approve_pid", None)
            return

    # ✅ --- معالجة رقم عملية السحب (يجب أن تكون في الأعلى) ---
    # --- 7. صرف السحب (يُصفّر الرصيد) ---
    if "pay_wid" in context.user_data and uid in ADMINS:
        wid = context.user_data["pay_wid"]
        cursor.execute("SELECT user_id, amount, sham_cash_link, method FROM withdrawals WHERE id=?", (wid,))
        row = cursor.fetchone()
        if not row:
            await update.message.reply_text("❌ طلب السحب غير موجود.")
            context.user_data.pop("pay_wid", None)
            return
        u, amt, data, method_type = row

        # ✅ تحديد الطريقة حسب اختيار المستخدم
        method = "شام كاش" if method_type == "sham" else "USDT (BEP20)" if method_type == "usdt" else "غير معروف"

        cursor.execute("UPDATE users SET referral_balance = 0 WHERE telegram_id=?", (u,))
        cursor.execute("UPDATE withdrawals SET status='PAID', transaction_id=? WHERE id=?", (text, wid))
        conn.commit()

        try:
            await context.bot.send_message(
                u,
                f"✅ تم صرف أرباحك بنجاح!\n\n"
                f"💵 المبلغ: {amt}$\n"
                f"🆔 رقم العملية: {text}\n"
                f"📌 الطريقة: {method}\n"
                f"📋 البيانات: `{data}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"فشل إرسال إشعار سحب: {e}")

        await update.message.reply_text(f"✅ تم صرف {amt}$ لـ {u}.")
        context.user_data.pop("pay_wid", None)
        return
    # --- باقي المعالجات ---
    if "edit" in context.user_data and uid in ADMINS:
        try:
            val = float(text) if context.user_data["edit"] != "subscription_price" else int(text)
            set_setting(context.user_data["edit"], val)
            context.user_data.pop("edit")
            await update.message.reply_text("✅ تم التعديل.")
        except:
            await update.message.reply_text("❌ أدخل رقمًا صحيحًا.")
        return

    if "edit_pm_id" in context.user_data and uid in ADMINS:
        m_id = context.user_data["edit_pm_id"]
        cursor.execute("UPDATE payment_methods SET name = ? WHERE id = ?", (text, m_id))
        conn.commit()
        context.user_data.pop("edit_pm_id")
        await update.message.reply_text("✅ تم التعديل.")
        return

    if context.user_data.get("support"):
        for admin in ADMINS:
            try:
                await context.bot.send_message(admin, f"📩 دعم من {uid}:\n{text}")
            except:
                pass
        context.user_data["support"] = False
        await update.message.reply_text("✅ تم الإرسال.")
        return

    if context.user_data.get("broadcast") and uid in ADMINS:
        cursor.execute("SELECT telegram_id FROM users")
        for (u,) in cursor.fetchall():
            try:
                await context.bot.send_message(u, text)
            except:
                pass
        context.user_data["broadcast"] = False
        await update.message.reply_text("✅ تم الإرسال.")
        return

# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", lambda u, c: 
        u.message.reply_text("🛂 الأدمن", reply_markup=admin_menu()) if u.effective_user.id in ADMINS else None))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, messages))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))

    logger.info("✅ البوت جاهز...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()