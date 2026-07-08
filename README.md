# Recursive Tic Tac Toe Online Server

FastAPI + WebSocket szerver Renderre optimalizálva.

## Local futtatás

```bash
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

A kliensben a `config.py` fájlban ez legyen:

```python
self.online_server_url = "http://localhost:8000"
```

## Render deploy

1. Töltsd fel ezt a szerver mappát GitHubra.
2. Renderen válaszd a Blueprint / `render.yaml` deployt.
3. Deploy után a kapott URL-t írd be a játék `config.py` fájljába:

```python
self.online_server_url = "https://SAJAT-RENDER-URL.onrender.com"
```

## API

- `GET /health` health check
- `POST /rooms` új 4 karakteres szobakód
- `GET /rooms` szobakereső lista
- `WS /ws/{code}` online játék websocket
