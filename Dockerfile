FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY data data
ENV DATABASE_URL=sqlite:////data/product_hunter.db
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
