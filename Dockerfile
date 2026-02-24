FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY *.py ./
COPY templates ./templates
COPY static ./static

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8069

# Keep uploaded files outside the image layer.
VOLUME ["/app/uploads"]

CMD ["python", "cli.py", "start", "--host", "0.0.0.0", "--port", "8069"]
