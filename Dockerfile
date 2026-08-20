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

# 업로드된 프로필 사진이 저장될 자리.
# /app 은 root 소유라 실행 사용자(app)가 런타임에 media/ 를 새로 만들 수 없다 -
# 이미지에서 미리 만들어 소유자를 넘겨 둔다. 운영에서는 이 경로에 named volume 을
# 붙여 배포 사이에 파일이 남게 한다(compose.production.yaml).
RUN install -d -o app -g app /app/media

USER app

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]
