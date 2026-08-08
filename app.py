import asyncio
import random
import string
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title='Recursive TTT Server')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)

ROOM_CODE_CHARS = string.ascii_uppercase + string.digits
PALETTE_SIZE = 8


@dataclass
class Room:
    code: str
    name: str
    clients: List[WebSocket] = field(default_factory=list)
    symbols: Dict[int, str] = field(default_factory=dict)
    colors: Dict[str, Optional[int]] = field(default_factory=lambda: {'X': None, 'O': None})
    start_ready: Dict[str, bool] = field(default_factory=lambda: {'X': False, 'O': False})
    restart_ready: Dict[str, bool] = field(default_factory=lambda: {'X': False, 'O': False})
    settings: Dict[str, int] = field(default_factory=lambda: {
        'depth': 2,
        'medium_markers': 3,
        'large_markers': 3,
    })
    moves: List[dict] = field(default_factory=list)
    started: bool = False
    current_symbol: str = 'X'
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def player_count(self):
        return len(self.clients)


rooms: Dict[str, Room] = {}
room_counter = 0
rooms_lock = asyncio.Lock()


def make_room_code():
    while True:
        code = ''.join(random.choice(ROOM_CODE_CHARS) for _ in range(4))
        if code not in rooms:
            return code


def room_payload(room: Room):
    return {
        'code': room.code,
        'name': room.name,
        'players': room.player_count(),
        'status': 'In Game' if room.started else 'Waiting',
    }


async def safe_send(ws: WebSocket, payload: dict):
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        return False


async def broadcast(room: Room, payload: dict):
    dead = []
    for ws in list(room.clients):
        if not await safe_send(ws, payload):
            dead.append(ws)
    for ws in dead:
        if ws in room.clients:
            room.clients.remove(ws)
        room.symbols.pop(id(ws), None)


async def broadcast_lobby_state(room: Room):
    await broadcast(room, {'type': 'players', 'count': room.player_count()})
    await broadcast(room, {
        'type': 'color_state',
        'colors': dict(room.colors),
        'ready': {
            'X': room.colors['X'] is not None,
            'O': room.colors['O'] is not None,
        },
        'start_ready': dict(room.start_ready),
        'settings': dict(room.settings),
    })


@app.get('/')
async def root():
    return {'ok': True, 'service': 'recursive-ttt-server'}


@app.get('/rooms')
async def list_rooms():
    # No starter/default rooms. Only rooms explicitly created by Create Room exist.
    open_rooms = [
        room_payload(room)
        for room in rooms.values()
        if room.player_count() > 0 and room.player_count() < 2 and not room.started
    ]
    return {'rooms': open_rooms}


@app.post('/rooms')
async def create_room():
    global room_counter
    async with rooms_lock:
        room_counter += 1
        code = make_room_code()
        room = Room(code=code, name='Room %d' % room_counter)
        rooms[code] = room
    return room_payload(room)


@app.websocket('/ws/{room_code}')
async def websocket_room(websocket: WebSocket, room_code: str):
    code = room_code.upper()
    room = rooms.get(code)
    if room is None:
        await websocket.close(code=4404, reason='Room not found')
        return

    await websocket.accept()

    async with room.lock:
        if len(room.clients) >= 2:
            await websocket.send_json({'type': 'error', 'message': 'Room is full'})
            await websocket.close(code=4409, reason='Room full')
            return

        symbol = 'X' if len(room.clients) == 0 else 'O'
        room.clients.append(websocket)
        room.symbols[id(websocket)] = symbol

        await websocket.send_json({
            'type': 'assign',
            'symbol': symbol,
            'moves': list(room.moves),
            'colors': dict(room.colors),
            'start_ready': dict(room.start_ready),
            'settings': dict(room.settings),
        })
        await broadcast_lobby_state(room)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type')

            async with room.lock:
                sender_symbol = room.symbols.get(id(websocket))
                if sender_symbol not in ('X', 'O'):
                    continue

                if msg_type == 'settings_update':
                    if room.started:
                        await safe_send(websocket, {'type': 'error', 'message': 'Game already started'})
                        continue

                    try:
                        depth = int(data.get('depth'))
                        medium = int(data.get('medium_markers'))
                        large = int(data.get('large_markers'))
                    except (TypeError, ValueError):
                        await safe_send(websocket, {'type': 'error', 'message': 'Invalid match settings'})
                        continue

                    if depth < 1 or depth > 3 or medium < 0 or medium > 9 or large < 0 or large > 9:
                        await safe_send(websocket, {'type': 'error', 'message': 'Match settings out of range'})
                        continue

                    room.settings = {
                        'depth': depth,
                        'medium_markers': medium,
                        'large_markers': large,
                    }

                    # Any match-setting change invalidates both START confirmations.
                    room.start_ready['X'] = False
                    room.start_ready['O'] = False
                    await broadcast(room, {
                        'type': 'settings_state',
                        'settings': dict(room.settings),
                        'start_ready': dict(room.start_ready),
                    })
                    await broadcast_lobby_state(room)
                    continue

                if msg_type == 'color_select':
                    if room.started:
                        await safe_send(websocket, {'type': 'error', 'message': 'Game already started'})
                        continue

                    try:
                        color_index = int(data.get('color_index'))
                    except (TypeError, ValueError):
                        await safe_send(websocket, {'type': 'error', 'message': 'Invalid color'})
                        continue

                    if color_index < 0 or color_index >= PALETTE_SIZE:
                        await safe_send(websocket, {'type': 'error', 'message': 'Invalid color'})
                        continue

                    other_symbol = 'O' if sender_symbol == 'X' else 'X'
                    if room.colors.get(other_symbol) == color_index:
                        await safe_send(websocket, {'type': 'error', 'message': 'That color is already selected'})
                        continue

                    room.colors[sender_symbol] = color_index
                    # Changing color cancels this player's START-ready state.
                    room.start_ready[sender_symbol] = False
                    await broadcast_lobby_state(room)

                    # Selecting both colors only makes the room ready.
                    # The match starts only after a player presses START.
                    continue

                if msg_type in ('ready_toggle', 'start_game'):
                    if room.started:
                        continue

                    if room.player_count() != 2:
                        await safe_send(websocket, {'type': 'error', 'message': 'Two players are required'})
                        continue

                    if room.colors['X'] is None or room.colors['O'] is None:
                        await safe_send(websocket, {'type': 'error', 'message': 'Both players must choose a color'})
                        continue

                    if room.colors['X'] == room.colors['O']:
                        await safe_send(websocket, {'type': 'error', 'message': 'Players must use different colors'})
                        continue

                    # READY is a per-player toggle. Clicking it again cancels
                    # the player's ready state. Broadcast immediately so both
                    # clients always display the same state without Refresh.
                    room.start_ready[sender_symbol] = not room.start_ready[sender_symbol]
                    await broadcast(room, {
                        'type': 'start_state',
                        'start_ready': dict(room.start_ready),
                        'settings': dict(room.settings),
                    })
                    await broadcast_lobby_state(room)

                    # The match starts only while BOTH players are READY.
                    if not (room.start_ready['X'] and room.start_ready['O']):
                        continue

                    room.started = True
                    room.current_symbol = 'X'
                    room.restart_ready['X'] = False
                    room.restart_ready['O'] = False
                    await broadcast(room, {
                        'type': 'game_start',
                        'colors': dict(room.colors),
                        'current_symbol': room.current_symbol,
                        'settings': dict(room.settings),
                    })
                    continue

                if msg_type == 'restart_toggle':
                    if not room.started:
                        await safe_send(websocket, {'type': 'error', 'message': 'Game has not started'})
                        continue

                    # Restart works exactly like the lobby READY toggle.
                    # Each player can turn their own request on/off independently.
                    room.restart_ready[sender_symbol] = not room.restart_ready[sender_symbol]
                    await broadcast(room, {
                        'type': 'restart_state',
                        'restart_ready': dict(room.restart_ready),
                    })

                    if not (room.restart_ready['X'] and room.restart_ready['O']):
                        continue

                    # Both players confirmed: clear the authoritative match history
                    # and restart with the same colors/settings, X to move first.
                    room.moves = []
                    room.current_symbol = 'X'
                    room.restart_ready['X'] = False
                    room.restart_ready['O'] = False
                    await broadcast(room, {
                        'type': 'restart_game',
                        'current_symbol': room.current_symbol,
                        'colors': dict(room.colors),
                        'settings': dict(room.settings),
                        'restart_ready': dict(room.restart_ready),
                    })
                    continue

                if msg_type == 'move':
                    if not room.started:
                        await safe_send(websocket, {'type': 'error', 'message': 'Both players must choose a color first'})
                        continue
                    if sender_symbol != room.current_symbol:
                        await safe_send(websocket, {'type': 'error', 'message': 'Not your turn'})
                        continue

                    path = data.get('path')
                    size = data.get('size')
                    if not isinstance(path, list) or size not in (1, 2, 3):
                        await safe_send(websocket, {'type': 'error', 'message': 'Invalid move'})
                        continue

                    move = {
                        'type': 'move',
                        'symbol': sender_symbol,
                        'path': path,
                        'size': size,
                    }
                    room.moves.append(move)
                    room.current_symbol = 'O' if sender_symbol == 'X' else 'X'
                    await broadcast(room, move)
                    continue

                await safe_send(websocket, {'type': 'error', 'message': 'Unknown message type'})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        async with room.lock:
            symbol = room.symbols.pop(id(websocket), None)
            if websocket in room.clients:
                room.clients.remove(websocket)

            if symbol in ('X', 'O'):
                room.colors[symbol] = None
                room.start_ready[symbol] = False
                room.restart_ready[symbol] = False

            # If the host (X) leaves, the room is removed. This also avoids ghost rooms.
            host_present = any(room.symbols.get(id(ws)) == 'X' for ws in room.clients)
            if not host_present:
                for ws in list(room.clients):
                    await safe_send(ws, {'type': 'error', 'message': 'Host left. Room closed.'})
                    try:
                        await ws.close(code=4410, reason='Host left')
                    except Exception:
                        pass
                room.clients.clear()
                room.symbols.clear()
                rooms.pop(code, None)
            else:
                # Guest left: return to pre-game waiting state and allow another guest.
                room.started = False
                room.moves = []
                room.current_symbol = 'X'
                room.colors['O'] = None
                room.start_ready['X'] = False
                room.start_ready['O'] = False
                room.restart_ready['X'] = False
                room.restart_ready['O'] = False
                await broadcast_lobby_state(room)
