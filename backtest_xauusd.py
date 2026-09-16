"""
Backtest: استراتيجية PDH/PDL Liquidity Sweep على الذهب (XAUUSD)
================================================================
الفكرة (مأخوذة من منطق ikeawesom/xauusd-backtest، مطبّقة من الصفر):

1. لكل يوم تداول، نحسب الـ Bias اليومي بناءً على اليوم السابق:
   - صعودي (bullish) لو اليوم السابق قفل أعلى من فتحه
   - هبوطي (bearish) لو اليوم السابق قفل أقل من فتحه

2. نحسب PDH (Previous Day High) و PDL (Previous Day Low) - أعلى/أقل
   سعر في اليوم السابق.

3. الدخول:
   - لو الـ Bias صعودي: نستنى السعر يكسر PDL (sweep) وبعدين يرجع
     يعدي فوق نقطة الـ sweep → دخول Long
   - لو الـ Bias هبوطي: نستنى السعر يكسر PDH (sweep) وبعدين يرجع
     يعدي تحت نقطة الـ sweep → دخول Short

4. الخروج:
   - جني الربح: يرجع السعر لنقطة الـ sweep الأصلية (PDH أو PDL)
   - وقف الخسارة/نهاية اليوم: لو الصفقة ملحقتش تقفل لنهاية اليوم التداولي

ملاحظات مهمة:
- الباكتست ده مبسّط ومفيهوش spread/commission/slippage، يعني النتيجة
  الحقيقية هتبقى أقل من اللي هتشوفه هنا.
- لازم تجرب على تايم فريمات وفترات مختلفة قبل ما تثق في النتيجة.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field


# ============ الإعدادات ============
CSV_PATH = "XAUUSD_15m.csv"   # غيّرها لمسار ملف البيانات عندك
TIMEFRAME_LABEL = "15m"
# =====================================


@dataclass
class Trade:
    date: str
    direction: str          # "LONG" or "SHORT"
    entry_price: float
    entry_time: pd.Timestamp
    exit_price: float = None
    exit_time: pd.Timestamp = None
    result: str = None      # "WIN", "LOSS", "BE"
    pnl_pct: float = None


class ExtractTrades:
    """يقرأ بيانات الشموع، ويحسب الـ bias اليومي وPDH/PDL لكل يوم."""

    def __init__(self, csv_path: str):
        df = pd.read_csv(csv_path)
        df.columns = [c.strip().lower() for c in df.columns]
        # نتوقع أعمدة: date/datetime, open, high, low, close (volume اختياري)
        date_col = "date" if "date" in df.columns else "datetime"
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.rename(columns={date_col: "datetime"})
        df = df.sort_values("datetime").reset_index(drop=True)
        df["day"] = df["datetime"].dt.date
        self.df = df
        self._daily = self._build_daily_stats()

    def _build_daily_stats(self):
        daily = self.df.groupby("day").agg(
            day_open=("open", "first"),
            day_close=("close", "last"),
            day_high=("high", "max"),
            day_low=("low", "min"),
        )
        daily["is_bullish"] = daily["day_close"] > daily["day_open"]
        return daily

    def get_df(self):
        return self.df

    def get_days(self):
        return list(self._daily.index)

    def is_bullish_daily_bias(self, day):
        """الـ bias بيتحدد من إغلاق اليوم *السابق*."""
        days = self.get_days()
        idx = days.index(day)
        if idx == 0:
            return None
        prev_day = days[idx - 1]
        return bool(self._daily.loc[prev_day, "is_bullish"])

    def get_pdh(self, day):
        days = self.get_days()
        idx = days.index(day)
        if idx == 0:
            return None
        return self._daily.loc[days[idx - 1], "day_high"]

    def get_pdl(self, day):
        days = self.get_days()
        idx = days.index(day)
        if idx == 0:
            return None
        return self._daily.loc[days[idx - 1], "day_low"]


class TradeSimulation:
    """يشغّل الباكتست بمنطق PDH/PDL sweep."""

    def __init__(self, csv_path: str):
        self.extractor = ExtractTrades(csv_path)
        self.df = self.extractor.get_df()
        self.trades: list[Trade] = []
        self._log = False

    def enable_log(self):
        self._log = True

    def disable_log(self):
        self._log = False

    def start(self):
        self.trades = []
        for day in self.extractor.get_days():
            bias = self.extractor.is_bullish_daily_bias(day)
            if bias is None:
                continue
            pdh = self.extractor.get_pdh(day)
            pdl = self.extractor.get_pdl(day)
            day_candles = self.df[self.df["day"] == day].reset_index(drop=True)
            trade = self._simulate_day(day, day_candles, bias, pdh, pdl)
            if trade:
                self.trades.append(trade)

    def _simulate_day(self, day, candles, bias, pdh, pdl):
        swept = False
        sweep_price = None
        direction = "LONG" if bias else "SHORT"
        level = pdl if bias else pdh

        for i, row in candles.iterrows():
            if not swept:
                if bias and row["low"] < pdl:
                    swept = True
                    sweep_price = pdl
                elif (not bias) and row["high"] > pdh:
                    swept = True
                    sweep_price = pdh
                continue

            # بعد الـ sweep، نستنى الارتداد وندخل
            if direction == "LONG" and row["close"] > sweep_price:
                entry_price = row["close"]
                entry_time = row["datetime"]
                trade = Trade(str(day), direction, entry_price, entry_time)
                return self._manage_exit(trade, candles.iloc[i + 1:], pdh)
            elif direction == "SHORT" and row["close"] < sweep_price:
                entry_price = row["close"]
                entry_time = row["datetime"]
                trade = Trade(str(day), direction, entry_price, entry_time)
                return self._manage_exit(trade, candles.iloc[i + 1:], pdl)

        return None  # مفيش صفقة النهاردة

    def _manage_exit(self, trade: Trade, remaining_candles, target_level):
        for _, row in remaining_candles.iterrows():
            if trade.direction == "LONG" and row["high"] >= target_level:
                trade.exit_price = target_level
                trade.exit_time = row["datetime"]
                trade.result = "WIN"
                break
            elif trade.direction == "SHORT" and row["low"] <= target_level:
                trade.exit_price = target_level
                trade.exit_time = row["datetime"]
                trade.result = "WIN"
                break

        if trade.exit_price is None:
            # نهاية اليوم من غير ما نوصل الهدف
            if len(remaining_candles) == 0:
                return None
            last = remaining_candles.iloc[-1]
            trade.exit_price = last["close"]
            trade.exit_time = last["datetime"]
            if trade.direction == "LONG":
                trade.result = "WIN" if trade.exit_price > trade.entry_price else "LOSS"
            else:
                trade.result = "WIN" if trade.exit_price < trade.entry_price else "LOSS"

        if trade.direction == "LONG":
            trade.pnl_pct = (trade.exit_price - trade.entry_price) / trade.entry_price * 100
        else:
            trade.pnl_pct = (trade.entry_price - trade.exit_price) / trade.entry_price * 100

        if self._log:
            print(f"{trade.date} | {trade.direction} | entry={trade.entry_price:.2f} "
                  f"exit={trade.exit_price:.2f} | {trade.result} | pnl={trade.pnl_pct:.2f}%")

        return trade

    def calculate_results(self):
        if not self.trades:
            return {"trades_taken": 0, "wins": 0, "winrate": 0.0, "avg_pnl_pct": 0.0}
        wins = sum(1 for t in self.trades if t.result == "WIN")
        total = len(self.trades)
        avg_pnl = np.mean([t.pnl_pct for t in self.trades])
        return {
            "trades_taken": total,
            "wins": wins,
            "losses": total - wins,
            "winrate": round(wins / total * 100, 2),
            "avg_pnl_pct": round(avg_pnl, 4),
            "cumulative_pnl_pct": round(sum(t.pnl_pct for t in self.trades), 2),
        }

    def display_results(self, full=False):
        results = self.calculate_results()
        print(f"\n=== نتائج الباكتست ({TIMEFRAME_LABEL}) ===")
        for k, v in results.items():
            print(f"{k}: {v}")
        if full:
            print("\n--- كل الصفقات ---")
            for t in self.trades:
                print(f"{t.date} | {t.direction} | {t.result} | pnl={t.pnl_pct:.2f}%")


if __name__ == "__main__":
    print(f"جاري تحميل البيانات من: {CSV_PATH}")
    sim = TradeSimulation(CSV_PATH)
    sim.enable_log()
    sim.start()
    sim.display_results(full=False)

    print("""
تنبيه: النتيجة دي بدون spread/commission/slippage.
عشان تقيّم الاستراتيجية صح:
  1. جرب على أكتر من تايم فريم (5m, 15m, 30m, 1h)
  2. اطرح spread متوسط الذهب (~20-30 سنت) من كل صفقة وشوف الفرق
  3. جرب على فترة زمنية أحدث (آخر سنة) لوحدها، مش كل التاريخ مع بعض
""")
