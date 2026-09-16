"""
بوت إشارات تليجرام - استراتيجية PDH/PDL Liquidity Sweep على الذهب
===================================================================
البوت ده بيبعت إشعار على تليجرام بس، ومش بينفذ أي صفقة فعلية.
دايماً راجع الإشارة بنفسك قبل ما تدخل صفقة.

المتطلبات:
    pip install yfinance pandas requests

خطوات الإعداد:
1. اعمل بوت تليجرام عن طريق @BotFather وخد التوكن
2. ابعت أي رسالة لبوتك، وبعدين افتح الرابط ده وحط التوكن مكانه:
   https://api.telegram.org/bot<TOKEN>/getUpdates
   وهتلاقي "chat":{"id": ...} - ده الـ CHAT_ID بتاعك
3. حط القيم في TELEGRAM_TOKEN و TELEGRAM_CHAT_ID تحت
4. شغّل البوت على سيرفر شغال 24/7 (مش على جهازك/موبايلك) - زي Render
   أو Railway (فيه خطط مجانية) عشان يفضل يراقب السوق حتى وإنت مش فاتح حاجة

تنبيه: البوت بيستخدم عقود الذهب الآجلة (GC=F) من Yahoo Finance كبديل
مجاني لسعر XAUUSD الفوري - الفرق بينهم بسيط عادةً لكن مش مطابق 100%.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
import yfinance as yf

# ============ الإعدادات ============
# القيم بتتقرأ من متغيرات البيئة (Environment Variables) على Render
# عشان التوكن ميتخزنش في الكود نفسه. لو بتشغّل محلي على جهازك، تقدر
# تحط القيم direct هنا بدل الـ os.environ.get.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")

SYMBOL = "GC=F"           # عقود الذهب الآجلة (بديل XAUUSD المجاني)
INTERVAL = "15m"          # الفريم الزمني: 1m,5m,15m,30m,1h
CHECK_EVERY_SECONDS = 60 * 5
# =====================================

state = {
    "current_day": None,
    "pdh": None,
    "pdl": None,
    "bias_bullish": None,
    "swept": False,
    "sweep_price": None,
    "direction": None,
    "in_trade": False,
    "last_signal_sent": None,
}


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"فشل إرسال الرسالة: {e}")


def get_daily_levels():
    """يجيب أعلى وأقل سعر لليوم السابق + الـ bias، من بيانات يومية."""
    daily = yf.download(SYMBOL, period="10d", interval="1d", progress=False)
    if len(daily) < 2:
        return None, None, None
    prev_day = daily.iloc[-2]
    pdh = float(prev_day["High"])
    pdl = float(prev_day["Low"])
    bias_bullish = bool(prev_day["Close"] > prev_day["Open"])
    return pdh, pdl, bias_bullish


def get_intraday_candles():
    df = yf.download(SYMBOL, period="2d", interval=INTERVAL, progress=False)
    df = df.reset_index()
    df.columns = [str(c[0]).lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
    return df


def reset_daily_state(today):
    pdh, pdl, bias = get_daily_levels()
    state["current_day"] = today
    state["pdh"] = pdh
    state["pdl"] = pdl
    state["bias_bullish"] = bias
    state["swept"] = False
    state["sweep_price"] = None
    state["direction"] = None
    state["in_trade"] = False
    print(f"[{today}] Bias: {'صعودي' if bias else 'هبوطي'} | PDH={pdh:.2f} PDL={pdl:.2f}")


def check_signal():
    today = datetime.now(timezone.utc).date()

    if state["current_day"] != today or state["pdh"] is None:
        reset_daily_state(today)

    if state["bias_bullish"] is None:
        print("مش قادر أحدد الـ bias دلوقتي، هحاول تاني بعد شوية.")
        return

    df = get_intraday_candles()
    today_candles = df[df["datetime"].dt.date == today] if "datetime" in df.columns else df[df.iloc[:, 0].dt.date == today]
    if len(today_candles) == 0:
        return

    last = today_candles.iloc[-1]
    price = float(last["close"])
    bias = state["bias_bullish"]

    # لو لسه ملحقناش الـ sweep
    if not state["swept"]:
        if bias and float(last["low"]) < state["pdl"]:
            state["swept"] = True
            state["sweep_price"] = state["pdl"]
            state["direction"] = "LONG"
            send_telegram_message(
                f"⚠️ <b>PDL Sweep حصل</b>\nالسعر كسر أقل سعر أمس ({state['pdl']:.2f})\n"
                f"مستني الارتداد لفوق عشان إشارة Long"
            )
        elif (not bias) and float(last["high"]) > state["pdh"]:
            state["swept"] = True
            state["sweep_price"] = state["pdh"]
            state["direction"] = "SHORT"
            send_telegram_message(
                f"⚠️ <b>PDH Sweep حصل</b>\nالسعر كسر أعلى سعر أمس ({state['pdh']:.2f})\n"
                f"مستني الارتداد لتحت عشان إشارة Short"
            )
        else:
            print(f"[{datetime.now()}] لسه مفيش sweep. السعر: {price:.2f}")
        return

    # حصل sweep، مستنيين الارتداد للدخول
    if not state["in_trade"]:
        direction = state["direction"]
        sweep_price = state["sweep_price"]
        target = state["pdh"] if direction == "LONG" else state["pdl"]

        entered = (direction == "LONG" and price > sweep_price) or \
                  (direction == "SHORT" and price < sweep_price)

        if entered:
            state["in_trade"] = True
            sig_key = f"{today}-{direction}-entry"
            if state["last_signal_sent"] != sig_key:
                message = (
                    f"🔔 <b>إشارة {direction}</b>\n"
                    f"الرمز: XAUUSD (GC=F)\n"
                    f"سعر الدخول: {price:.2f}\n"
                    f"نقطة الـ Sweep: {sweep_price:.2f}\n"
                    f"الهدف (نقطة sweep المعاكسة): {target:.2f}\n\n"
                    f"⚠️ ده إشعار فقط - راجع السوق بنفسك قبل الدخول"
                )
                send_telegram_message(message)
                print(message)
                state["last_signal_sent"] = sig_key
    else:
        # في صفقة، نتابع هل وصلنا الهدف
        direction = state["direction"]
        target = state["pdh"] if direction == "LONG" else state["pdl"]
        reached = (direction == "LONG" and price >= target) or \
                  (direction == "SHORT" and price <= target)
        if reached:
            sig_key = f"{today}-{direction}-exit"
            if state["last_signal_sent"] != sig_key:
                send_telegram_message(
                    f"✅ <b>الهدف اتحقق</b>\nالسعر وصل {price:.2f} (الهدف: {target:.2f})"
                )
                state["last_signal_sent"] = sig_key
        else:
            print(f"[{datetime.now()}] في صفقة {direction}، مستني الهدف {target:.2f}. السعر الحالي: {price:.2f}")


if __name__ == "__main__":
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE" or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("⚠️ لازم تحط TELEGRAM_TOKEN و TELEGRAM_CHAT_ID (في الكود أو environment variables)")
        raise SystemExit(1)
    send_telegram_message("✅ بوت إشارات الذهب (PDH/PDL Sweep) بدأ الشغل...")
    while True:
        try:
            check_signal()
        except Exception as e:
            print(f"خطأ: {e}")
        time.sleep(CHECK_EVERY_SECONDS)
