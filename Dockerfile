FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

RUN addgroup --system safeops && adduser --system --ingroup safeops safeops
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=safeops:safeops . .
RUN mkdir -p /app/data && chown safeops:safeops /app/data

USER safeops
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
