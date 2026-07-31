# Imagen Python. (No hay engine de Rust en la ruta crítica — ver docs/ROADMAP.md, D-1.)
FROM python:3.11-slim
WORKDIR /app

COPY python/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir -e python

EXPOSE 8080
CMD ["python", "-m", "compiled_ai_router.cli", "serve"]
