FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
ENV LIFE_HOST=0.0.0.0
ENV LIFE_PORT=8765
ENV LIFE_DB=/data/lifevault.db
EXPOSE 8765
CMD ["python", "-m", "app"]
