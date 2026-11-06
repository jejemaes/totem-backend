FROM python:3.14-slim

WORKDIR /usr/src/app
EXPOSE 8000

# Create directories
RUN mkdir /usr/src/static \
    /usr/src/media

# Recommended Python flags
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install Python packages requirements
COPY ./requirements.txt /usr/src/app/requirements.txt
RUN --mount=type=ssh pip install --no-cache-dir \
    -r /usr/src/app/requirements.txt

# Install runtime dependencies
RUN apt-get -qq update && \
    apt-get install -q -y --no-install-recommends \
    curl \
    postgresql-client

# Copy Docker entrypoint script
COPY entrypoints/* /usr/local/bin/

# Copy project source files
COPY src ./

ENTRYPOINT ["docker-entrypoint.sh"]

CMD "uvicorn totem.asgi:application --port 8000 --host 0.0.0.0"
