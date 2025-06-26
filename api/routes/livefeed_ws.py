from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState
from algosat.brokers.fyers import FyersWrapper
import asyncio
import logging
from jose import jwt, JWTError
import algosat.api.auth_dependencies as auth_deps

router = APIRouter()
logger = logging.getLogger("ws.livefeed")

# --- Multi-client Connection Management ---

class ConnectionManager:
    """Manages active WebSocket connections from clients."""
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active_connections.append(websocket)
        logger.info(f"[Manager] New client connected: {websocket.client}. Total clients: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"[Manager] Client disconnected: {websocket.client}. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcasts a message to all connected clients."""
        connections_to_broadcast = self.active_connections[:]
        for connection in connections_to_broadcast:
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_json(message)
                else:
                    await self.disconnect(connection)
            except Exception:
                await self.disconnect(connection)

manager = ConnectionManager()

# --- Singleton Fyers Feed Handler ---

fyers_feed_task = None
fyers_connection_lock = asyncio.Lock()
fyers_wrapper_instance = FyersWrapper()

async def fyers_live_feed_loop():
    """
    A single, long-running task that connects to the Fyers WebSocket,
    subscribes to symbols, and broadcasts data to all connected clients.
    This loop will shut down when the last client disconnects.
    """
    global fyers_feed_task
    logger.info("[FyersFeedLoop] Starting Fyers live feed loop...")

    try:
        login_success = await fyers_wrapper_instance.login()
        if not login_success:
            logger.error("[FyersFeedLoop] Fyers login failed. Aborting loop.")
            await manager.broadcast({"error": "Data provider login failed."})
            return

        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_message(msg):
            loop.call_soon_threadsafe(queue.put_nowait, msg)

        def on_error(msg):
            logger.error(f"[FyersFeedLoop] Fyers WS error: {msg}")
            loop.call_soon_threadsafe(queue.put_nowait, {"error": "Fyers WS Error", "details": msg})

        def on_close(msg):
            logger.info(f"[FyersFeedLoop] Fyers WS closed: {msg}")
            fyers_wrapper_instance.ws_connected = False
            loop.call_soon_threadsafe(queue.put_nowait, {"event": "close"})

        def on_connect():
            logger.info("[FyersFeedLoop] Fyers WS connected. Subscribing...")
            fyers_wrapper_instance.ws_connected = True
            symbols = ['NSE:NIFTY50-INDEX', 'NSE:NIFTYBANK-INDEX', 'NSE:INDIAVIX-INDEX']
            data_type = "SymbolUpdate"
            fyers_wrapper_instance.subscribe_websocket(symbols, data_type=data_type)

        fyers_wrapper_instance.init_websocket(
            on_connect=on_connect, on_message=on_message, on_error=on_error, on_close=on_close
        )
        fyers_wrapper_instance.connect_websocket()
        logger.info("[FyersFeedLoop] Fyers WebSocket connection process initiated.")

        while True:
            if not manager.active_connections:
                logger.info("[FyersFeedLoop] No active clients. Waiting 5s for reconnect before shutdown...")
                await asyncio.sleep(5)  # Grace period for clients to reconnect (e.g., on page refresh)
                if not manager.active_connections:
                    logger.info("[FyersFeedLoop] No clients reconnected. Shutting down.")
                    break
            
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                if msg.get("event") == "close":
                    logger.warning("[FyersFeedLoop] Received close event. Exiting.")
                    break
                await manager.broadcast(msg)
            except asyncio.TimeoutError:
                continue

    except Exception as e:
        logger.error(f"[FyersFeedLoop] An exception occurred in the feed loop: {e}", exc_info=True)
    finally:
        logger.info("[FyersFeedLoop] Cleaning up Fyers connection.")
        try:
            fyers_wrapper_instance.close_websocket()
        except Exception as e:
            logger.error(f"[FyersFeedLoop] Error closing Fyers websocket: {e}")
        
        async with fyers_connection_lock:
            fyers_feed_task = None

@router.websocket("/ws/livefeed")
async def websocket_livefeed(websocket: WebSocket):
    logger.info(f"[ws/livefeed] Client attempting to connect: {websocket.client}")
    token = websocket.query_params.get("token")
    if not token:
        logger.warning("[ws/livefeed] No token provided, closing.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        payload = await auth_deps.security_manager.validate_token(token)
        if not payload:
            raise JWTError("Invalid Token")
        logger.info(f"[ws/livefeed] JWT validated for user: {payload.get('sub')}")
    except JWTError as e:
        logger.warning(f"[ws/livefeed] Invalid JWT: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket)

    global fyers_feed_task
    async with fyers_connection_lock:
        if fyers_feed_task is None or fyers_feed_task.done():
            logger.info("[ws/livefeed] Fyers feed task not running. Starting it.")
            fyers_feed_task = asyncio.create_task(fyers_live_feed_loop())
        else:
            logger.info("[ws/livefeed] Fyers feed task is already running. Client joined.")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"[ws/livefeed] Client {websocket.client} disconnected.")
    finally:
        await manager.disconnect(websocket)
