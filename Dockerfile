FROM python:3.11-slim

WORKDIR /app

# يمنع Streamlit من انتظار إدخال تفاعلي (لا توجد طرفية داخل الحاوية) ومن جمع إحصاءات الاستخدام
ENV HOME=/app \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# HF Docker Spaces تشغّل الحاوية بمستخدم غير جذر افتراضياً؛ نمنح صلاحية الكتابة الكاملة
# على مجلد العمل حتى لا يفشل Streamlit عند إنشاء ملفات الإعداد المؤقتة
RUN chmod -R 777 /app

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]

