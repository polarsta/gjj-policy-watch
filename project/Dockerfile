FROM python:3.12-slim

WORKDIR /app

# 仅安装运行时依赖（pytest 等测试依赖不进镜像）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gjjwatch ./gjjwatch
COPY config ./config

# 运行时目录（建议挂载持久卷）：
#   -v $(pwd)/config:/app/config  -v $(pwd)/data:/app/data  -v $(pwd)/reports:/app/reports
VOLUME ["/app/config", "/app/data", "/app/reports"]

ENTRYPOINT ["python", "-m", "gjjwatch.cli"]
CMD ["daily"]
