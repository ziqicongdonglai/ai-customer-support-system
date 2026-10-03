FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

ARG PIP_INDEX_URL

# requirements.txt 只维护 Torch 逻辑版本；所有受支持 Docker 路径显式选择同版本 CPU artifact，避免 reviewer/demo topology 引入无业务价值的 CUDA dependency chain。
# --no-deps 让 PyTorch CPU index 只提供 Torch，其余 Python 依赖仍由常规 index 解析。
# 构建内断言显式验证 CPU artifact，防止 resolver 或 source drift 意外恢复 CUDA build。
RUN python -m pip install --no-cache-dir --no-deps torch==2.13.0 \
      --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -c "import torch; assert torch.__version__ == '2.13.0+cpu'; assert torch.version.cuda is None; assert not torch.cuda.is_available()"

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
