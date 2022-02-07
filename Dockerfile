FROM python:3.10-slim

WORKDIR /app

ENV PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements-deploy.txt .

RUN pip install -r requirements-deploy.txt

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY spoqify.py .
COPY setup.py .
COPY README.md .

RUN pip install .

ENTRYPOINT ["uvicorn", "spoqify:app", "--host", "0.0.0.0", "--port", "5000"]
