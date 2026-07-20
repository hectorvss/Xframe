# Imagen única para api y worker: el mismo código, distinto comando. Mantener dos
# imágenes divergiría en dependencias y el bug aparecería solo en uno de los dos.

FROM python:3.12-slim AS base

# ffmpeg y ffprobe son dependencias de ejecución, no de desarrollo: sin ellos el
# montaje final no existe. Van en la imagen base y no en la de build por eso mismo.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv

WORKDIR /srv

# Dependencias antes que el código: cambiar una línea de app/ no debe reinstalar
# langgraph. Es la diferencia entre un rebuild de 10 segundos y uno de tres minutos.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app

# Usuario sin privilegios. ffmpeg procesa ficheros que vienen de fuera; no hay razón
# para que lo haga como root.
RUN useradd --system --create-home --uid 10001 xframe \
    && mkdir -p /tmp/xframe && chown -R xframe:xframe /tmp/xframe /srv
USER xframe

EXPOSE 8000

# Por defecto la API. El worker sobreescribe el comando en docker-compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# --- variante de desarrollo: evals y tests ---------------------------------
FROM base AS dev

USER root
COPY pyproject.toml ./
RUN pip install ".[dev]"
COPY evals ./evals
USER xframe

CMD ["pytest", "-m", "not evals"]
