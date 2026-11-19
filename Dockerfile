FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Tk provides the desktop toolkit. Graphviz development files support the
# optional ERD dependency in requirements.txt.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tk \
        tk-dev \
        tcl-dev \
        graphviz \
        libgraphviz-dev \
        build-essential \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/database

CMD ["python", "-m", "interface.gui"]
