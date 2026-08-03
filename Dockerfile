FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir .
EXPOSE 8080
CMD ["python", "-m", "agent_scan", "serve", "--port", "8080"]
