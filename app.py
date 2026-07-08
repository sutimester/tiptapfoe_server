import asyncio
import json
import os
import random
import string
import time
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware


ROOM_TTL_SECONDS = int(os.getenv('ROOM_TTL_SECONDS', '7200'))
MAX_ROOMS = int(os.getenv('MAX_ROOMS', '500'))

app = FastAPI(title='Recursive Tic Tac Toe Online Server')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

rooms: Dict[str, dict] = {}
lock = asyncio.Lock()


def make_code() -> str:
    chars = string.ascii_uppercase + string.digits

    while True:
        code = ''.join(random.choice(chars) for _ in range(4))

        if code not in rooms:
            return code


def cleanup_rooms() -> None:
    now = time.time()
    expired = []

    for code, room in rooms.items():
        if room['clients']:
            continue

        if now - room['updated_at'] > ROOM_TTL_SECONDS:
            expired.append(code)

    for code in expired:
        rooms.pop(code, None)


async def broadcast(room: dict, payload: dict) -> None:
    message = json.dumps(payload)
    dead: List[WebSocket] = []

    for websocket in list(room['clients']):
        try:
            await websocket.send_text(message)
        except Exception:
            dead.append(websocket)

    for websocket in dead:
        if websocket in room['clients']:
            room['clients'].remove(websocket)


@app.get('/')
async def root():
    return {
        'status': 'ok',
        'service': 'recursive-ttt-server'
    }


@app.get('/health')
async def health():
    return {'status': 'healthy'}


@app.post('/rooms')
async def create_room():
    async with lock:
        cleanup_rooms()

        if len(rooms) >= MAX_ROOMS:
            raise HTTPException(status_code=429, detail='Too many rooms')

        code = make_code()
        rooms[code] = {
            'code': code,
            'created_at': time.time(),
            'updated_at': time.time(),
            'moves': [],
            'clients': [],
            'symbols': {}
        }

    return {'code': code}


@app.get('/rooms')
async def list_rooms():
    async with lock:
        cleanup_rooms()

        visible = []

        for room in rooms.values():
            players = len(room['clients'])

            if players >= 2:
                continue

            visible.append({
                'code': room['code'],
                'players': players,
                'created_at': room['created_at']
            })

        visible.sort(key=lambda item: item['created_at'], reverse=True)

    return {'rooms': visible[:50]}


@app.websocket('/ws/{code}')
async def websocket_room(websocket: WebSocket, code: str):
    code = code.upper()
    await websocket.accept()

    async with lock:
        cleanup_rooms()

        if code not in rooms:
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Room not found'
            }))
            await websocket.close()
            return

        room = rooms[code]

        if len(room['clients']) >= 2:
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Room is full'
            }))
            await websocket.close()
            return

        symbol = 'X' if len(room['clients']) == 0 else 'O'
        room['clients'].append(websocket)
        room['symbols'][websocket] = symbol
        room['updated_at'] = time.time()

        moves = list(room['moves'])
        count = len(room['clients'])

    await websocket.send_text(json.dumps({
        'type': 'assign',
        'symbol': symbol,
        'room': code,
        'moves': moves
    }))

    await broadcast(room, {
        'type': 'players',
        'count': count
    })

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if data.get('type') != 'move':
                continue

            symbol = room['symbols'].get(websocket)

            move = {
                'type': 'move',
                'symbol': symbol,
                'path': data.get('path'),
                'size': data.get('size'),
                'number': len(room['moves'])
            }

            async with lock:
                room['moves'].append(move)
                room['updated_at'] = time.time()

            await broadcast(room, move)

    except WebSocketDisconnect:
        pass
    finally:
        async with lock:
            room = rooms.get(code)

            if room:
                if websocket in room['clients']:
                    room['clients'].remove(websocket)

                room['symbols'].pop(websocket, None)
                room['updated_at'] = time.time()
                count = len(room['clients'])
            else:
                count = 0

        if code in rooms:
            await broadcast(rooms[code], {
                'type': 'players',
                'count': count
            })
