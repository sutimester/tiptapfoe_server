# Recursive TTT server - online color ready

Render-kompatibilis FastAPI + WebSocket szerver.

## Új online folyamat

1. `POST /rooms` létrehozza a szobát és 4 karakteres kódot ad.
2. Az első WebSocket kliens X, a második O.
3. Mindkét kliens `color_select` üzenettel választ a 0..7 palettából.
4. Azonos szín nem foglalható.
5. Csak akkor érkezik `game_start`, ha mindkét játékos csatlakozott és eltérő színt választott.
6. `move` csak `game_start` után engedélyezett.

## Render

Build command:

    pip install -r requirements.txt

Start command:

    uvicorn app:app --host 0.0.0.0 --port $PORT

Nincsenek kezdő szobák. Szoba csak a Create Room gomb által hívott `POST /rooms` után létezik.

## START-ready protokoll

A szerver a két szín kiválasztása után nem indítja automatikusan a játékot.
A kliens `start_game` WebSocket üzenetet küld a START gomb megnyomásakor; a szerver csak két csatlakozott, eltérő színt választott játékos esetén broadcastolja a `game_start` üzenetet.
