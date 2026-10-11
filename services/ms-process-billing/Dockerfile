# Construir desde la raiz codigo_fuente_voltera/:
#   docker buildx build --platform linux/arm64 -f services/ms-process-billing/Dockerfile -t <ecr>/voltera-exp2/ms-process-billing:latest .
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY services/ms-process-billing/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY libs/voltera_common /tmp/voltera_common
RUN pip install /tmp/voltera_common && rm -rf /tmp/voltera_common
COPY services/ms-process-billing/*.py ./
RUN useradd -r -u 10001 app
USER 10001
EXPOSE 8080
# exec-form: python es PID 1 y recibe SIGTERM directamente
ENTRYPOINT ["python", "-u", "main.py"]
