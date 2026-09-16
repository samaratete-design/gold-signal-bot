# خطوات نشر البوت على Render.com

## 1. ارفع الملفات على GitHub
لو عندك الريبو القديم `trading-signal-bot`، ممكن تستبدل الملفات فيه
بالملفات دي (أو تعمل ريبو جديد). لازم يكون فيه:
- telegram_bot_gold.py
- backtest_xauusd.py
- requirements.txt
- render.yaml

عن طريق موبايلك: أسهل حاجة تستخدم تطبيق GitHub الرسمي أو تفتح
github.com من المتصفح وتعمل Upload files مباشرة في الريبو.

## 2. اعمل حساب على Render.com
- روح على https://render.com وسجّل دخول بحساب الـ GitHub بتاعك

## 3. أنشئ Background Worker جديد
- من الداشبورد: New + → Background Worker
- اختار الريبو بتاعك
- Render هيقرأ ملف `render.yaml` تلقائي ويعرف إنه worker مش website
- لو سألك عن Start Command يدوي، حطه:
  `python telegram_bot_gold.py`
- Build Command:
  `pip install -r requirements.txt`
- Plan: Free

## 4. حط الـ Environment Variables
في إعدادات الـ Service → Environment:
- TELEGRAM_TOKEN = التوكن بتاعك
- TELEGRAM_CHAT_ID = الـ chat id بتاعك

(متحطش القيم دي في الكود نفسه لو الريبو public - حد تاني ممكن ياخدها
ويبعت رسايل من بوتك)

## 5. Deploy
- دوس Create Background Worker / Deploy
- من الـ Logs هتشوف رسالة "بدأ الشغل" وبعدها هتوصلك رسالة على تليجرام

## ملاحظات مهمة
- الخطة المجانية في Render ممكن توقف الـ worker لو مفيش نشاط لفترة
  طويلة - راجع حدود الخطة المجانية الحالية على موقعهم.
- لو حبيت تغيّر SYMBOL أو INTERVAL، عدّل في telegram_bot_gold.py
  وارفع تاني (git push) - Render هيعيد الـ deploy تلقائي.
- جرب الـ backtest الأول قبل ما تسيب البوت يشتغل بمبلغ حقيقي.
