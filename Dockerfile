FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

RUN DJANGO_DEBUG=True DJANGO_SECRET_KEY=collectstatic-only \
    python manage.py collectstatic --noinput

# 사용자가 올린 프로필 사진이 저장되는 곳. git에는 없는 디렉터리라 미리 만들어
# app 사용자가 쓸 수 있게 해야 한다 - 운영에서는 이 경로에 영구 볼륨을 마운트한다.
RUN mkdir -p /app/media && chown app:app /app/media

USER app

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]
