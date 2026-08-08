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

## Dual START protocol

A `start_game` üzenet már nem azonnali indítás: az adott játékos START-ready állapotát állítja be. A szerver `start_state` és `color_state` üzenetekkel azonnal szinkronizálja mindkét klienst. `game_start` csak akkor megy ki, amikor X és O is START-ready.


## Lobby settings protocol

New WebSocket message from client:
`settings_update` with `depth`, `medium_markers`, `large_markers`.
The server broadcasts `settings_state` and includes `settings` in lobby state, assign and game_start payloads.
Changing settings clears both players' START-ready state.


## v22 lobby sync

- A Board Depth, Starting Medium Markers és Starting Large Markers módosítása bármelyik kliensről azonnal WebSocketen frissül mindkét játékosnál.
- Bármely pályabeállítás-változás mindkét READY állapotot kikapcsolja.
- A READY gomb toggle: első kattintás READY, következő kattintás NOT READY.
- Mindkét kliens automatikusan megkapja a READY és lobby-beállítás változásokat, kézi Refresh nélkül.
- A játék csak akkor indul, amikor mindkét játékos egyszerre READY.


## In-game restart READY

During a started game clients may send `restart_toggle`. The server broadcasts `restart_state`. Each player can toggle their own restart confirmation. When both X and O are ready, the server clears move history, resets turn to X and broadcasts `restart_game` while preserving colors and lobby settings.
