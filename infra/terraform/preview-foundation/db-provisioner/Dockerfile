FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY db_names.py provisioner.py server.py ./

USER 10001:10001
EXPOSE 8080
CMD ["python", "server.py"]
