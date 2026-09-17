---
title: Trading Bot Dashboard
emoji: 📈
colorFrom: green
colorTo: red
<<<<<<< HEAD
sdk: docker
app_port: 8501
=======
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
>>>>>>> c5e4923036140ec58033f81959aa081be2c2d4b3
pinned: false
---

# لوحة عرض بوت التداول (قراءة فقط)

واجهة عامة تعرض بيانات مخزَّنة في قاعدة بيانات Aiven التي يستخدمها بوت التداول
على Telegram/Cloud Run — **قراءة فقط**، لا تُعدّل أو تتحكم بالبوت بأي شكل.

<<<<<<< HEAD
مبنية بـ Streamlit، ومشغَّلة عبر Docker SDK (Hugging Face أوقفت دعم Streamlit
كـ SDK مدمج مباشر منذ أبريل 2025، والبديل الرسمي هو تشغيلها داخل حاوية Docker).

=======
>>>>>>> c5e4923036140ec58033f81959aa081be2c2d4b3
## الإعداد المطلوب (Secrets)

من إعدادات هذا الـ Space، أضف تحت "Repository secrets":

- `DATABASE_URL` — نفس رابط اتصال Aiven (يُفضَّل مستخدم قراءة فقط منفصل)
- `DB_CA_CERT_PEM` — محتوى شهادة CA الكامل من Aiven (نفس القيمة المستخدمة في Cloud Run)
- `AUTO_ANALYSIS_INTERVAL_MINUTES` (اختياري، افتراضي 10) — لحساب مؤشر "حداثة البيانات"
<<<<<<< HEAD

=======
>>>>>>> c5e4923036140ec58033f81959aa081be2c2d4b3
