FROM python:3.12-slim

WORKDIR /app

# System deps: gcc needed for some scientific-Python wheels (scikit-learn/
# sentence-transformers transitive deps) on slim images without prebuilt
# wheels for the host arch.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# main_hybrid.py is the only supported entrypoint — see README.md.
CMD ["uvicorn", "api.main_hybrid:app", "--host", "0.0.0.0", "--port", "8000"]