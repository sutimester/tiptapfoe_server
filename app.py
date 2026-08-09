
import asyncio
import random
import string
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Recursive Marker Game Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

CODE_CHARS = string.ascii_uppercase + string.digits
PALETTE_SIZE = 8


@dataclass
class Room:
    code: str
    name: str
    public: bool = False
    clients: List[WebSocket] = field(default_factory=list)
    symbols: Dict[int, str] = field(default_factory=dict)
    colors: Dict[str, Optional[int]] = field(default_factory=lambda: {"X": None, "O": None})
    start_ready: Dict[str, bool] = field(default_factory=lambda: {"X": False, "O": False})
    restart_ready: Dict[str, bool] = field(default_factory=lambda: {"X": False, "O": False})
    settings: Dict[str, int] = field(default_factory=lambda: {
        "depth": 2,
        "medium_markers": 3,
        "large_markers": 3,
    })
    starting_symbol: str = "X"
    current_symbol: str = "X"
    moves: List[dict] = field(default_factory=list)
    started: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def player_count(self):
        return len(self.clients)


rooms: Dict[str, Room] = {}
room_counter = 0
rooms_lock = asyncio.Lock()


def new_code():
    while True:
        code = "".join(random.choice(CODE_CHARS) for _ in range(4))
        if code not in rooms:
            return code


def room_payload(room: Room):
    return {
        "code": room.code,
        "name": room.name,
        "players": room.player_count(),
        "public": room.public,
        "status": "In Game" if room.started else "Waiting",
    }


async def safe_send(ws: WebSocket, payload: dict):
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        return False


async def broadcast(room: Room, payload: dict):
    for ws in list(room.clients):
        await safe_send(ws, payload)


async def broadcast_lobby(room: Room):
    await broadcast(room, {"type": "players", "count": room.player_count()})
    await broadcast(room, {
        "type": "color_state",
        "colors": dict(room.colors),
        "start_ready": dict(room.start_ready),
        "settings": dict(room.settings),
        "public": room.public,
        "starting_symbol": room.starting_symbol,
    })


@app.get("/")
async def root():
    return {"ok": True}


@app.get("/rooms")
async def list_rooms():
    return {
        "rooms": [
            room_payload(room)
            for room in rooms.values()
            if room.public and room.player_count() > 0 and room.player_count() < 2 and not room.started
        ]
    }


@app.post("/rooms")
async def create_room(payload: Optional[dict] = Body(default=None)):
    global room_counter
    payload = payload or {}
    async with rooms_lock:
        room_counter += 1
        room = Room(
            code=new_code(),
            name="Room %d" % room_counter,
            public=bool(payload.get("public", False)),
        )
        rooms[room.code] = room
    return room_payload(room)


@app.websocket("/ws/{room_code}")
async def websocket_room(websocket: WebSocket, room_code: str):
    code = room_code.upper()
    room = rooms.get(code)
    if room is None:
        await websocket.close(code=4404, reason="Room not found")
        return

    await websocket.accept()

    async with room.lock:
        if room.player_count() >= 2:
            await websocket.send_json({"type": "error", "message": "Room is full"})
            await websocket.close(code=4409, reason="Room full")
            return

        symbol = "X" if room.player_count() == 0 else "O"
        room.clients.append(websocket)
        room.symbols[id(websocket)] = symbol

        await websocket.send_json({
            "type": "assign",
            "symbol": symbol,
            "colors": dict(room.colors),
            "start_ready": dict(room.start_ready),
            "restart_ready": dict(room.restart_ready),
            "settings": dict(room.settings),
            "public": room.public,
            "starting_symbol": room.starting_symbol,
        })
        await broadcast_lobby(room)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            async with room.lock:
                sender = room.symbols.get(id(websocket))
                if sender not in ("X", "O"):
                    continue

                if msg_type == "settings_update":
                    if room.started:
                        continue
                    try:
                        depth = int(data.get("depth"))
                        medium = int(data.get("medium_markers"))
                        large = int(data.get("large_markers"))
                    except (TypeError, ValueError):
                        continue
                    room.settings = {
                        "depth": max(1, min(3, depth)),
                        "medium_markers": max(0, min(9, medium)),
                        "large_markers": max(0, min(9, large)),
                    }
                    room.start_ready = {"X": False, "O": False}
                    await broadcast(room, {
                        "type": "settings_state",
                        "settings": dict(room.settings),
                        "start_ready": dict(room.start_ready),
                        "starting_symbol": room.starting_symbol,
                    })
                    await broadcast_lobby(room)
                    continue

                if msg_type == "starting_toggle":
                    if room.started:
                        continue
                    room.starting_symbol = "O" if room.starting_symbol == "X" else "X"
                    room.current_symbol = room.starting_symbol
                    room.start_ready = {"X": False, "O": False}
                    await broadcast(room, {
                        "type": "starting_state",
                        "starting_symbol": room.starting_symbol,
                        "start_ready": dict(room.start_ready),
                        "settings": dict(room.settings),
                        "colors": dict(room.colors),
                    })
                    await broadcast_lobby(room)
                    continue

                if msg_type == "color_select":
                    if room.started:
                        continue
                    try:
                        color = int(data.get("color_index"))
                    except (TypeError, ValueError):
                        continue
                    if not 0 <= color < PALETTE_SIZE:
                        continue
                    other = "O" if sender == "X" else "X"
                    if room.colors.get(other) == color:
                        await safe_send(websocket, {"type": "error", "message": "That color is already selected"})
                        continue
                    room.colors[sender] = color
                    room.start_ready[sender] = False
                    await broadcast_lobby(room)
                    continue

                if msg_type == "ready_toggle":
                    if room.started or room.player_count() != 2:
                        continue
                    if room.colors["X"] is None or room.colors["O"] is None:
                        continue
                    room.start_ready[sender] = not room.start_ready[sender]
                    await broadcast(room, {
                        "type": "start_state",
                        "start_ready": dict(room.start_ready),
                        "starting_symbol": room.starting_symbol,
                        "settings": dict(room.settings),
                    })
                    await broadcast_lobby(room)

                    if room.start_ready["X"] and room.start_ready["O"]:
                        room.started = True
                        room.current_symbol = room.starting_symbol
                        room.restart_ready = {"X": False, "O": False}
                        await broadcast(room, {
                            "type": "game_start",
                            "colors": dict(room.colors),
                            "settings": dict(room.settings),
                            "starting_symbol": room.starting_symbol,
                            "current_symbol": room.current_symbol,
                        })
                    continue

                if msg_type == "move":
                    if not room.started or sender != room.current_symbol:
                        continue
                    path = data.get("path")
                    size = data.get("size")
                    if not isinstance(path, list) or size not in (1, 2, 3):
                        continue
                    move = {"type": "move", "symbol": sender, "path": path, "size": size}
                    room.moves.append(move)
                    room.current_symbol = "O" if sender == "X" else "X"
                    room.restart_ready = {"X": False, "O": False}
                    await broadcast(room, move)
                    continue

                if msg_type == "restart_toggle":
                    if not room.started:
                        continue
                    room.restart_ready[sender] = not room.restart_ready[sender]
                    await broadcast(room, {
                        "type": "restart_state",
                        "restart_ready": dict(room.restart_ready),
                    })
                    if room.restart_ready["X"] and room.restart_ready["O"]:
                        room.moves = []
                        room.starting_symbol = "O" if room.starting_symbol == "X" else "X"
                        room.current_symbol = room.starting_symbol
                        room.restart_ready = {"X": False, "O": False}
                        await broadcast(room, {
                            "type": "game_restart",
                            "starting_symbol": room.starting_symbol,
                            "current_symbol": room.current_symbol,
                            "restart_ready": dict(room.restart_ready),
                        })
                    continue

    except WebSocketDisconnect:
        pass
    finally:
        async with room.lock:
            symbol = room.symbols.pop(id(websocket), None)
            if websocket in room.clients:
                room.clients.remove(websocket)

            if symbol in ("X", "O"):
                room.colors[symbol] = None
                room.start_ready[symbol] = False
                room.restart_ready[symbol] = False

            host_present = any(room.symbols.get(id(ws)) == "X" for ws in room.clients)
            if not host_present:
                rooms.pop(code, None)
            else:
                room.started = False
                room.moves = []
                room.starting_symbol = "X"
                room.current_symbol = room.starting_symbol
                room.colors["O"] = None
                room.start_ready = {"X": False, "O": False}
                room.restart_ready = {"X": False, "O": False}
                await broadcast_lobby(room)
