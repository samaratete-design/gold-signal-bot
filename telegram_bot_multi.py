"""
بوت إشارات تليجرام - استراتيجيات مختلفة لكل أصل
====================================================
- الذهب (XAUUSD)، اليورو (EURUSD) → Box Theory (صندوق اليوم اللي فات)
- البيتكوين (BTC)، الباوند (GBPUSD)، الين (USDJPY) → EMA 9/21 Crossover + RSI Filter

استراتيجية Box Theory:
- بناخد أعلى وأقل سعر لشمعة اليوم اللي فات (Daily) = "الصندوق"
- خط النص = منتصف المسافة بين القمة والقاع
- على فريم 15 دقيقة: لو السعر قريب من أعلى الصندوق (آخر 15% من الارتفاع) →
  Sell فقط. لو قريب من أسفل الصندوق (أول 15%) → Buy فقط. لو في المنتصف →
  لا تداول (منطقة غير واضحة)
- الدخول مش فوري: البوت بيستنى شمعة تأكيد/انعكاس قبل ما يبعت الإشارة،
  عشان يقلل الإشارات الكاذبة

دالة استراتيجية الـ PDH/PDL Sweep القديمة لسه موجودة في الكود
(check_sweep_signal) لو حبيت ترجعلها في أي وقت.

البوت ده بيبعت إشعار على تليجرام بس، ومش بينفذ أي صفقة فعلية.
دايماً راجع الإشارة بنفسك قبل ما تدخل صفقة.

المتطلبات:
    pip install yfinance pandas requests ta

خطوات الإعداد:
1. اعمل بوت تليجرام عن طريق @BotFather وخد التوكن
2. ابعت أي رسالة لبوتك، وبعدين افتح الرابط ده وحط التوكن مكانه:
   https://api.telegram.org/bot<TOKEN>/getUpdates
   وهتلاقي "chat":{"id": ...} - ده الـ CHAT_ID بتاعك
3. حط القيم في TELEGRAM_TOKEN و TELEGRAM_CHAT_ID (أو environment variables)
4. شغّل البوت على سيرفر شغال 24/7 - زي Render
"""

import os
import time
from datetime import datetime, timezone

import requests
import pandas as pd
import ta
import yfinance as yf

# ============ الإعدادات ============
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")

ASSETS = {
    "GOLD": {"symbol": "GC=F", "label": "الذهب (XAUUSD)", "interval": "15m", "strategy": "box_theory"},
    "EURUSD": {"symbol": "EURUSD=X", "label": "اليورو/دولار (EURUSD)", "interval": "15m", "strategy": "box_theory"},
    "BTC": {"symbol": "BTC-USD", "label": "البيتكوين (BTCUSD)", "interval": "15m", "strategy": "ema_rsi"},
    "GBPUSD": {"symbol": "GBPUSD=X", "label": "الباوند/دولار (GBPUSD)", "interval": "15m", "strategy": "ema_rsi"},
    "USDJPY": {"symbol": "USDJPY=X", "label": "دولار/ين (USDJPY)", "interval": "15m", "strategy": "ema_rsi"},
}

CHECK_EVERY_SECONDS = 60 * 5

# إعدادات استراتيجية EMA+RSI (البيتكوين، الباوند، الين)
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70

# إعدادات استراتيجية Box Theory (الذهب، اليورو)
BOX_ZONE_PERCENT = 0.15  # أقرب 15% من كل طرف تعتبر "قريب"
# =====================================


def make_sweep_state():
    return {
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


def make_ema_rsi_state():
    return {"last_signal": None}


def make_box_state():
    return {
        "current_day": None,
        "box_high": None,
        "box_low": None,
        "box_mid": None,
        "zone": None,          # "top", "bottom", "middle"
        "awaiting_confirm": None,  # "SELL" أو "BUY" لو مستني شمعة تأكيد
        "last_signal_sent": None,
    }


STATE_FACTORIES = {
    "sweep": make_sweep_state,
    "ema_rsi": make_ema_rsi_state,
    "box_theory": make_box_state,
}

state = {}
for name, cfg in ASSETS.items():
    state[name] = STATE_FACTORIES[cfg["strategy"]]()


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"فشل إرسال الرسالة: {e}")


def get_daily_levels(symbol):
    """بترجع (أعلى سعر، أقل سعر، bias صعودي؟) لآخر يوم مكتمل قبل النهارده."""
    daily = yf.download(symbol, period="10d", interval="1d", progress=False)
    if daily is None or len(daily) < 2:
        return None, None, None

    # تسطيح الأعمدة لو MultiIndex (ده اللي كان بيسبب خطأ float/Series)
    if isinstance(daily.columns, pd.MultiIndex):
        daily.columns = daily.columns.get_level_values(0)

    # ناخد الأيام اللي قبل النهارده بس، وآخر يوم منهم هو "اليوم اللي فات"
    today = datetime.now(timezone.utc).date()
    daily = daily[daily.index.date < today]
    if len(daily) < 1:
        return None, None, None

    prev_day = daily.iloc[-1]
    pdh = float(prev_day["High"])
    pdl = float(prev_day["Low"])
    bias_bullish = bool(float(prev_day["Close"]) > float(prev_day["Open"]))
    return pdh, pdl, bias_bullish


def get_intraday_candles(symbol, interval, period="2d"):
    df = yf.download(symbol, period=period, interval=interval, progress=False)
    df = df.reset_index()
    df.columns = [str(c[0]).lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
    return df


# ============ استراتيجية 1: PDH/PDL Sweep (قديمة، غير مستخدمة حالياً) ============

def reset_sweep_state(asset_name, today):
    cfg = ASSETS[asset_name]
    pdh, pdl, bias = get_daily_levels(cfg["symbol"])
    s = state[asset_name]
    s.update(make_sweep_state())
    s["current_day"] = today
    s["pdh"] = pdh
    s["pdl"] = pdl
    s["bias_bullish"] = bias
    if pdh is not None:
        print(f"[{cfg['label']} | {today}] Bias: {'صعودي' if bias else 'هبوطي'} | PDH={pdh:.4f} PDL={pdl:.4f}")


def check_sweep_signal(asset_name):
    cfg = ASSETS[asset_name]
    symbol, label, interval = cfg["symbol"], cfg["label"], cfg["interval"]
    s = state[asset_name]
    today = datetime.now(timezone.utc).date()

    if s["current_day"] != today or s["pdh"] is None:
        reset_sweep_state(asset_name, today)

    if s["bias_bullish"] is None:
        print(f"[{label}] مش قادر أحدد الـ bias دلوقتي، هحاول تاني بعد شوية.")
        return

    df = get_intraday_candles(symbol, interval)
    if "datetime" in df.columns:
        today_candles = df[df["datetime"].dt.date == today]
    else:
        today_candles = df[df.iloc[:, 0].dt.date == today]
    if len(today_candles) == 0:
        return

    last = today_candles.iloc[-1]
    price = float(last["close"])
    bias = s["bias_bullish"]

    if not s["swept"]:
        if bias and float(last["low"]) < s["pdl"]:
            s["swept"] = True
            s["sweep_price"] = s["pdl"]
            s["direction"] = "LONG"
            send_telegram_message(
                f"⚠️ <b>{label} - PDL Sweep حصل</b>\nالسعر كسر أقل سعر أمس ({s['pdl']:.4f})\n"
                f"مستني الارتداد لفوق عشان إشارة Long"
            )
        elif (not bias) and float(last["high"]) > s["pdh"]:
            s["swept"] = True
            s["sweep_price"] = s["pdh"]
            s["direction"] = "SHORT"
            send_telegram_message(
                f"⚠️ <b>{label} - PDH Sweep حصل</b>\nالسعر كسر أعلى سعر أمس ({s['pdh']:.4f})\n"
                f"مستني الارتداد لتحت عشان إشارة Short"
            )
        else:
            print(f"[{label} | {datetime.now()}] لسه مفيش sweep. السعر: {price:.4f}")
        return

    if not s["in_trade"]:
        direction = s["direction"]
        sweep_price = s["sweep_price"]
        target = s["pdh"] if direction == "LONG" else s["pdl"]
        entered = (direction == "LONG" and price > sweep_price) or \
                  (direction == "SHORT" and price < sweep_price)
        if entered:
            s["in_trade"] = True
            sig_key = f"{today}-{direction}-entry"
            if s["last_signal_sent"] != sig_key:
                message = (
                    f"🔔 <b>إشارة {direction} - {label}</b>\n"
                    f"سعر الدخول: {price:.4f}\n"
                    f"نقطة الـ Sweep: {sweep_price:.4f}\n"
                    f"الهدف: {target:.4f}\n\n"
                    f"⚠️ ده إشعار فقط - راجع السوق بنفسك قبل الدخول"
                )
                send_telegram_message(message)
                print(message)
                s["last_signal_sent"] = sig_key
    else:
        direction = s["direction"]
        target = s["pdh"] if direction == "LONG" else s["pdl"]
        reached = (direction == "LONG" and price >= target) or \
                  (direction == "SHORT" and price <= target)
        if reached:
            sig_key = f"{today}-{direction}-exit"
            if s["last_signal_sent"] != sig_key:
                send_telegram_message(
                    f"✅ <b>{label} - الهدف اتحقق</b>\nالسعر وصل {price:.4f} (الهدف: {target:.4f})"
                )
                s["last_signal_sent"] = sig_key
        else:
            print(f"[{label} | {datetime.now()}] في صفقة {direction}، مستني الهدف {target:.4f}. السعر الحالي: {price:.4f}")


# ============ استراتيجية 2: EMA Crossover + RSI (البيتكوين، الباوند، الين) ============

def check_ema_rsi_signal(asset_name):
    cfg = ASSETS[asset_name]
    symbol, label, interval = cfg["symbol"], cfg["label"], cfg["interval"]
    s = state[asset_name]

    df = get_intraday_candles(symbol, interval, period="5d")
    if len(df) < EMA_SLOW + 2:
        print(f"[{label}] بيانات مش كفاية لسه.")
        return

    df["ema_fast"] = ta.trend.ema_indicator(df["close"], window=EMA_FAST)
    df["ema_slow"] = ta.trend.ema_indicator(df["close"], window=EMA_SLOW)
    df["rsi"] = ta.momentum.rsi(df["close"], window=RSI_PERIOD)

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    crossed_up = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
    crossed_down = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]

    price = float(curr["close"])
    rsi = float(curr["rsi"])

    signal = None
    if crossed_up and rsi < RSI_OVERBOUGHT:
        signal = "BUY"
    elif crossed_down:
        signal = "SELL"

    if signal and signal != s["last_signal"]:
        stop_loss = price * 0.98 if signal == "BUY" else price * 1.02
        take_profit = price * 1.04 if signal == "BUY" else price * 0.96
        message = (
            f"🔔 <b>إشارة {signal} - {label}</b>\n"
            f"السعر الحالي: {price:.4f}\n"
            f"RSI: {rsi:.1f}\n"
            f"وقف الخسارة المقترح: {stop_loss:.4f}\n"
            f"جني الأرباح المقترح: {take_profit:.4f}\n\n"
            f"⚠️ ده إشعار فقط - راجع السوق بنفسك قبل الدخول"
        )
        send_telegram_message(message)
        print(message)
        s["last_signal"] = signal
    else:
        print(f"[{label} | {datetime.now()}] لا توجد إشارة جديدة. السعر: {price:.4f} | RSI: {rsi:.1f}")


# ============ استراتيجية 3: Box Theory (الذهب، اليورو) ============

def reset_box_state(asset_name, today):
    cfg = ASSETS[asset_name]
    box_high, box_low, _ = get_daily_levels(cfg["symbol"])
    s = state[asset_name]
    s.update(make_box_state())
    s["current_day"] = today
    s["box_high"] = box_high
    s["box_low"] = box_low
    if box_high is not None:
        s["box_mid"] = (box_high + box_low) / 2
        print(f"[{cfg['label']} | {today}] Box High={box_high:.4f} Low={box_low:.4f} Mid={s['box_mid']:.4f}")


def get_box_zone(price, box_high, box_low):
    box_range = box_high - box_low
    if box_range <= 0:
        return "middle"
    top_threshold = box_high - box_range * BOX_ZONE_PERCENT
    bottom_threshold = box_low + box_range * BOX_ZONE_PERCENT
    if price >= top_threshold:
        return "top"
    elif price <= bottom_threshold:
        return "bottom"
    else:
        return "middle"


def check_box_theory_signal(asset_name):
    cfg = ASSETS[asset_name]
    symbol, label, interval = cfg["symbol"], cfg["label"], cfg["interval"]
    s = state[asset_name]
    today = datetime.now(timezone.utc).date()

    if s["current_day"] != today or s["box_high"] is None:
        reset_box_state(asset_name, today)

    if s["box_high"] is None:
        print(f"[{label}] مش قادر أحدد الصندوق دلوقتي، هحاول تاني بعد شوية.")
        return

    df = get_intraday_candles(symbol, interval)
    if len(df) < 2:
        return

    prev = df.iloc[-2]
    curr = df.iloc[-1]
    price = float(curr["close"])
    box_high, box_low, box_mid = s["box_high"], s["box_low"], s["box_mid"]
    zone = get_box_zone(price, box_high, box_low)

    # لو السعر رجع للمنتصف، نلغي أي تأكيد كنا مستنيينه
    if zone == "middle":
        if s["awaiting_confirm"]:
            print(f"[{label}] السعر رجع لمنطقة النص، إلغاء انتظار التأكيد.")
        s["awaiting_confirm"] = None
        print(f"[{label} | {datetime.now()}] السعر في منطقة غير واضحة (النص). السعر: {price:.4f}")
        return

    expected_direction = "SELL" if zone == "top" else "BUY"

    # شمعة تأكيد/انعكاس: شمعة بتقفل عكس اتجاه الحركة اللي وصلت بيها للمنطقة
    is_bearish_reversal = float(curr["close"]) < float(curr["open"]) and float(prev["close"]) > float(prev["open"])
    is_bullish_reversal = float(curr["close"]) > float(curr["open"]) and float(prev["close"]) < float(prev["open"])

    confirmed = (expected_direction == "SELL" and is_bearish_reversal) or \
                (expected_direction == "BUY" and is_bullish_reversal)

    if not confirmed:
        s["awaiting_confirm"] = expected_direction
        print(
            f"[{label} | {datetime.now()}] السعر قريب من {'القمة' if zone == 'top' else 'القاع'}، "
            f"مستني شمعة تأكيد {expected_direction}. السعر: {price:.4f}"
        )
        return

    sig_key = f"{today}-{expected_direction}-{zone}"
    if s["last_signal_sent"] == sig_key:
        return

    target = box_mid
    stop_loss = box_high * 1.002 if expected_direction == "SELL" else box_low * 0.998
    message = (
        f"🔔 <b>إشارة {expected_direction} - {label} (Box Theory)</b>\n"
        f"السعر الحالي: {price:.4f}\n"
        f"أعلى الصندوق: {box_high:.4f} | أقل الصندوق: {box_low:.4f}\n"
        f"وقف الخسارة المقترح: {stop_loss:.4f}\n"
        f"الهدف (خط النص): {target:.4f}\n\n"
        f"⚠️ ده إشعار فقط - راجع السوق بنفسك قبل الدخول"
    )
    send_telegram_message(message)
    print(message)
    s["last_signal_sent"] = sig_key
    s["awaiting_confirm"] = None


# ============ التشغيل ============

STRATEGY_FUNCS = {
    "sweep": check_sweep_signal,
    "ema_rsi": check_ema_rsi_signal,
    "box_theory": check_box_theory_signal,
}


if __name__ == "__main__":
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE" or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("⚠️ لازم تحط TELEGRAM_TOKEN و TELEGRAM_CHAT_ID (في الكود أو environment variables)")
        raise SystemExit(1)

    STRATEGY_NAMES = {"sweep": "PDH/PDL Sweep", "ema_rsi": "EMA+RSI", "box_theory": "Box Theory"}
    summary = "\n".join(
        f"- {cfg['label']}: {STRATEGY_NAMES[cfg['strategy']]}"
        for cfg in ASSETS.values()
    )
    send_telegram_message(f"✅ بوت الإشارات بدأ الشغل...\n{summary}")

    while True:
        for asset_name, cfg in ASSETS.items():
            try:
                STRATEGY_FUNCS[cfg["strategy"]](asset_name)
            except Exception as e:
                print(f"[{asset_name}] خطأ: {e}")
        time.sleep(CHECK_EVERY_SECONDS)
