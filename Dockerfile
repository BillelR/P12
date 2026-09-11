FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY sql/ sql/
COPY data/raw/ data/raw/

CMD ["python3", "--version"]
