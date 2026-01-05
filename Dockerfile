FROM python:3.10-slim

# Create non-root user
RUN useradd -m appuser

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_sm
# Copy app code
COPY . .

# Make sure app files are owned by appuser
RUN chown -R appuser:appuser /app

# 🔹 Make /app importable as a package root (so "from app.xxx" works)
ENV PYTHONPATH="/app:${PYTHONPATH}"

# Switch to non-root user
USER appuser

# 🔹 Pre-download the SentenceTransformer model used by vector_local.py
# MODEL_NAME default is "all-MiniLM-L6-v2"
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Run in offline mode so it uses cached model and doesn't hit huggingface.co
ENV TRANSFORMERS_OFFLINE=1
ENV HF_HUB_OFFLINE=1

# Cloud Run expects the app to listen on $PORT
ENV PORT=8501
EXPOSE 8501

CMD ["bash", "-c", "streamlit run app/Chat.py --server.port=$PORT --server.address=0.0.0.0"]
