FROM python:3.12-slim

WORKDIR /app

ENV PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements-deploy.txt .

RUN pip install -r requirements-deploy.txt

COPY spoqify spoqify
COPY setup.py .
COPY README.md .

RUN pip install .

ENTRYPOINT ["uvicorn", "spoqify.app:app", "--host", "0.0.0.0", "--port", "5000"]
