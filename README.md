# Recursive Marker Game server v33

## Public / Private rooms

`POST /rooms` JSON body:

```json
{"public": true}
```

- `public: true`: a hosttal rendelkező, még nem tele szoba megjelenik a `GET /rooms` listában.
- `public: false`: a szoba nem jelenik meg a listában, csak a 4 karakteres kóddal lehet csatlakozni.
- Nincsenek kezdő szobák: csak `POST /rooms` hoz létre szobát.
- A Room Finder csak public, 1/2 állapotú, még el nem indult szobákat kap.

## Render

Build command:

    pip install -r requirements.txt

Start command:

    uvicorn app:app --host 0.0.0.0 --port $PORT


## v36 - Alternating restart starter

- A room now stores `starting_symbol`.
- The first match starts with X.
- When both players confirm Restart, the server alternates X/O.
- `game_restart` broadcasts both `current_symbol` and `starting_symbol`.
- If the guest leaves and the room returns to the lobby, the series resets to X for the next opponent.
