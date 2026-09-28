# コードレース: バックエンド(FastAPI)がフロントエンドの静的ファイルも
# 同じプロセスから配信するため、イメージは1つだけで完結する。
# ビルドコンテキストはリポジトリ直下(backend/ と frontend/ の親)を指定する。
#
#   docker build -t code-race .
#   docker run --rm -p 8000:8000 code-race
#
# その後 http://localhost:8000 にアクセスすれば遊べる。
#
# Render等のPaaSにデプロイする場合、リッスンすべきポート番号が環境変数
# PORT で渡されることが多い(ローカル実行時は未設定なので8000を使う)。

FROM python:3.11-slim

WORKDIR /app

# 依存関係だけ先にインストールすることで、アプリコードの変更時に
# pip installレイヤーがキャッシュされ再ビルドが速くなる。
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app backend/app
COPY frontend frontend

WORKDIR /app/backend

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
