FROM node:22-alpine AS assets
WORKDIR /app
COPY package.json .
RUN npm install
COPY app/static/css/tailwind.input.css app/static/css/tailwind.input.css
COPY app/templates app/templates
COPY app/static/js app/static/js
RUN npm run build:css

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=assets /app/app/static/css/tailwind.css app/static/css/tailwind.css
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
