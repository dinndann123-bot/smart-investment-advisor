FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python -c "from pathlib import Path; p=Path('static/index.html'); s=p.read_text(encoding='utf-8'); s=s.replace('</head>','<link rel=\"stylesheet\" href=\"/static/ui-v2.css?v=2\"></head>',1) if 'ui-v2.css' not in s else s; s=s.replace('</body>','<script src=\"/static/ui-v2.js?v=2\"></script></body>',1) if 'ui-v2.js' not in s else s; p.write_text(s,encoding='utf-8')"
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
