FROM python:3.12-slim
RUN useradd -m -u 10001 app && mkdir /data && chown app /data
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY scripts scripts
COPY migrations migrations
COPY alembic.ini ./
COPY frontend frontend
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
