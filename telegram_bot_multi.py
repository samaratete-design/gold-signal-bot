"""
بوت إشارات تليجرام - استراتيجيات مختلفة لكل أصل
====================================================
- الذهب (XAUUSD)   → PDH/PDL Liquidity Sweep
- اليورو (EURUSD)  → PDH/PDL Liquidity Sweep
- البيتكوين (BTC)  → EMA 9/21 Crossover + RSI Filter

كل أصل بياخد الاستراتيجية اللي بتناسب طبيعته: الذهب واليورو أسواق
جلسات (session-based) بترتد حوالين مستويات اليوم اللي فات، والبيتكوين
سوق 24 ساعة ميّال للاتجاهات (trending) فمناسب له متابعة اتجاه بدل
الارتداد حوالين مستوى ثابت.

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
    "GOLD": {"symbol": "GC=F", "label": "الذهب (XAUUSD)", "interval": "15m", "strategy": "sweep"},
    "EURUSD": {"symbol": "EURUSD=X", "label": "اليورو/دولار (EURUSD)", "interval": "15m", "strategy": "sweep"},
    "BTC": {"symbol": "BTC-USD", "label": "البيتكوين (BTCUSD)", "interval": "15m", "strategy": "ema_rsi"},
}

CHECK_EVERY_SECONDS = 60 * 5

# إعدادات استراتيجية EMA+RSI (للبيتكوين)
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
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


state = {}
for name, cfg in ASSETS.items():
    state[name] = make_sweep_state() if cfg["strategy"] == "sweep" else make_ema_rsi_state()


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"فشل إرسال الرسالة: {e}")


def get_daily_levels(symbol):
    daily = yf.download(symbol, period="10d", interval="1d", progress=False)
    if len(daily) < 2:
        return None, None, None
    prev_day = daily.iloc[-2]
    pdh = float(prev_day["High"])
    pdl = float(prev_day["Low"])
    bias_bullish = bool(prev_day["Close"] > prev_day["Open"])
    return pdh, pdl, bias_bullish


def get_intraday_candles(symbol, interval, period="2d"):
    df = yf.download(symbol, period=period, interval=interval, progress=False)
    df = df.reset_index()
    df.columns = [str(c[0]).lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
    return df


# ============ استراتيجية 1: PDH/PDL Sweep (الذهب، اليورو) ============

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


# ============ استراتيجية 2: EMA Crossover + RSI (البيتكوين) ============

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
            f"السعر الحالي: {price:.2f}\n"
            f"RSI: {rsi:.1f}\n"
            f"وقف الخسارة المقترح: {stop_loss:.2f}\n"
            f"جني الأرباح المقترح: {take_profit:.2f}\n\n"
            f"⚠️ ده إشعار فقط - راجع السوق بنفسك قبل الدخول"
        )
        send_telegram_message(message)
        print(message)
        s["last_signal"] = signal
    else:
        print(f"[{label} | {datetime.now()}] لا توجد إشارة جديدة. السعر: {price:.2f} | RSI: {rsi:.1f}")


# ============ التشغيل ============

STRATEGY_FUNCS = {
    "sweep": check_sweep_signal,
    "ema_rsi": check_ema_rsi_signal,
}


if __name__ == "__main__":
    if TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE" or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("⚠️ لازم تحط TELEGRAM_TOKEN و TELEGRAM_CHAT_ID (في الكود أو environment variables)")
        raise SystemExit(1)

    summary = "\n".join(
        f"- {cfg['label']}: {'PDH/PDL Sweep' if cfg['strategy'] == 'sweep' else 'EMA+RSI'}"
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
