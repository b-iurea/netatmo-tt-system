from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import logging

import requests
from requests.exceptions import ConnectionError, Timeout, RequestException
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler


app = Flask(__name__)

# Silence Werkzeug access logs (health/liveness probes flood the logs at INFO level)
try:
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
except Exception:
    pass

# Configuration
SOURCE_BASE_URL = os.getenv("SOURCE_BASE_URL", "").rstrip("/")
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "5"))
CHECK_ROUNDS = int(os.getenv("CHECK_ROUNDS", "6"))  # 6 * 5min = 30min
TEMP_DELTA = float(os.getenv("TEMP_DELTA", "0.5"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "15"))
# Retry configuration for connection errors
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("RETRY_BACKOFF", "2.0"))  # exponential backoff factor
# Poll interval for homestatus (seconds). Default 150s = 2.5 minutes to reduce API calls.
POLL_INTERVAL_SECONDS = int(float(os.getenv("POLL_INTERVAL_SECONDS", "150")))
# Valve detection: module types considered valves (comma-separated, uppercase-matched)
VALVE_MODULE_TYPES = [t.strip().upper() for t in os.getenv("VALVE_MODULE_TYPES", "NRV,VALVE").split(",") if t.strip()]
# Keys to inspect on a valve module to determine activity (comma-separated)
VALVE_ACTIVE_KEYS = [k.strip() for k in os.getenv("VALVE_ACTIVE_KEYS", "valve_position,valve,position,open,heating_power_request,valve_level").split(",") if k.strip()]

_session = requests.Session()

# In-memory state
STATE: Dict[str, Any] = {
    "rooms_map": {},  # room_id -> {module_ids: []}
    "monitors": {},  # room_id -> monitor state
}

scheduler = BackgroundScheduler()
scheduler.start()

# Logging
logger = logging.getLogger("monitor")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
try:
    logger.setLevel(LOG_LEVEL)
except Exception:
    logger.setLevel("INFO")
if not logger.handlers:
    h = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s %(levelname)s [monitor] %(message)s")
    h.setFormatter(fmt)
    logger.addHandler(h)

logger.info("monitor starting: SOURCE_BASE_URL=%s CHECK_INTERVAL_MIN=%s CHECK_ROUNDS=%s TEMP_DELTA=%s MAX_RETRIES=%s RETRY_BACKOFF=%s", SOURCE_BASE_URL, CHECK_INTERVAL_MIN, CHECK_ROUNDS, TEMP_DELTA, MAX_RETRIES, RETRY_BACKOFF)

# Simple deduplicating logger helper to avoid repeating identical info messages
LAST_LOGS: Dict[str, float] = {}
def log_once(key: str, level: str, msg: str, *args, window: int = 60) -> None:
    try:
        now = datetime.now(timezone.utc).timestamp()
        last = LAST_LOGS.get(key)
        if last and (now - last) < float(window):
            return
        LAST_LOGS[key] = now
    except Exception:
        pass
    if level == "debug":
        logger.debug(msg, *args)
    elif level == "warning":
        logger.warning(msg, *args)
    elif level == "error":
        logger.error(msg, *args)
    else:
        logger.info(msg, *args)


def _now_iso() -> str:
    # Use timezone-aware UTC timestamp and render with Z suffix
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_request_with_retry(method: str, url: str, max_retries: int = None, **kwargs) -> requests.Response:
    """
    Make HTTP request with automatic retry on connection errors.
    Implements exponential backoff to avoid overwhelming the service.
    """
    import time
    
    if max_retries is None:
        max_retries = MAX_RETRIES
    
    last_exception = None
    for attempt in range(max_retries):
        try:
            if method.upper() == "GET":
                return _session.get(url, **kwargs)
            elif method.upper() == "PUT":
                return _session.put(url, **kwargs)
            elif method.upper() == "POST":
                return _session.post(url, **kwargs)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
        except (ConnectionError, Timeout) as e:
            last_exception = e
            if attempt < max_retries - 1:
                wait_time = RETRY_BACKOFF ** attempt
                logger.warning(
                    "Connection error on attempt %d/%d for %s: %s. Retrying in %.1fs...",
                    attempt + 1, max_retries, url, str(e)[:100], wait_time
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    "Connection failed after %d attempts for %s: %s",
                    max_retries, url, str(e)[:150]
                )
        except RequestException as e:
            # For other request exceptions (like HTTP errors), don't retry
            logger.error("Request error for %s: %s", url, str(e)[:150])
            raise
    
    # If we exhausted all retries, raise the last exception
    if last_exception:
        raise last_exception


def fetch_homesdata() -> Dict[str, Any]:
    url = f"{SOURCE_BASE_URL}/homesdata"
    logger.debug("fetch_homesdata: GET %s", url)
    try:
        r = _make_request_with_retry("GET", url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except (ConnectionError, Timeout) as e:
        logger.error("fetch_homesdata: connection failed after retries: %s", str(e)[:150])
        raise
    except Exception as e:
        logger.exception("fetch_homesdata error: %s", e)
        raise
    logger.debug("fetch_homesdata: status=%s", r.status_code)
    data = r.json()
    # verbose summary
    try:
        homes = data.get("body", {}).get("homes", [])
        log_once("fetch_homesdata.received", "info", "fetch_homesdata: received %d homes", len(homes))
        if homes:
            home = homes[0]
            rooms = home.get("rooms", [])
            modules = home.get("modules", [])
            log_once("fetch_homesdata.home_summary", "info", "fetch_homesdata: home has %d rooms and %d modules", len(rooms), len(modules))
            for rm in rooms:
                logger.debug("fetch_homesdata: room id=%s name=%s module_ids=%s", rm.get("id"), rm.get("name"), rm.get("module_ids"))
    except Exception:
        logger.exception("fetch_homesdata: error summarizing payload")
    return data


def fetch_homestatus() -> Dict[str, Any]:
    url = f"{SOURCE_BASE_URL}/homestatus"
    logger.debug("fetch_homestatus: GET %s", url)
    try:
        r = _make_request_with_retry("GET", url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except (ConnectionError, Timeout) as e:
        logger.error("fetch_homestatus: connection failed after retries: %s", str(e)[:150])
        raise
    except Exception as e:
        logger.exception("fetch_homestatus error: %s", e)
        raise
    logger.debug("fetch_homestatus: status=%s", r.status_code)
    data = r.json()
    # verbose summary
    try:
        home = data.get("body", {}).get("home", {})
        rooms = home.get("rooms", [])
        modules = home.get("modules", [])
        log_once("fetch_homestatus.home_summary", "info", "fetch_homestatus: home has %d rooms and %d modules", len(rooms), len(modules))
        for m in modules:
            logger.debug("fetch_homestatus: module id=%s type=%s bridge=%s firmware=%s", m.get("id"), m.get("type"), m.get("bridge"), m.get("firmware_revision"))
        for rm in rooms:
            logger.debug("fetch_homestatus: room id=%s reachable=%s heating_power_request=%s measured=%s therm_setpoint_mode=%s", rm.get("id"), rm.get("reachable"), rm.get("heating_power_request"), rm.get("therm_measured_temperature"), rm.get("therm_setpoint_mode"))
    except Exception:
        logger.exception("fetch_homestatus: error summarizing payload")
    return data


def map_modules_from_homesdata(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    homes = payload.get("body", {}).get("homes", [])
    if not homes:
        return result
    home = homes[0]
    for room in home.get("rooms", []):
        room_id = room.get("id")
        modules = room.get("module_ids") or []
        result[str(room_id)] = {"module_ids": list(modules), "name": room.get("name")}
    log_once("map_modules_from_homesdata.count", "info", "map_modules_from_homesdata: mapped %d rooms", len(result))
    for rid, info in result.items():
        logger.debug("map_modules_from_homesdata: room=%s name=%s modules=%s", rid, info.get("name"), info.get("module_ids"))
    return result


def start_monitor_if_needed(room_id: str, initial_temp: float) -> None:
    if room_id in STATE["monitors"]:
        return

    monitor = {
        "room_id": room_id,
        "initial_temp": float(initial_temp),
        "attempts": 0,
        "started_at": _now_iso(),
    }
    STATE["monitors"][room_id] = monitor

    job_id = f"monitor_{room_id}"
    logger.info("start_monitor_if_needed: room=%s initial_temp=%s job_id=%s", room_id, initial_temp, job_id)

    def monitor_step():
        try:
            m = STATE["monitors"].get(room_id)
            if not m:
                return
            logger.debug("monitor_step: room=%s attempt=%s", room_id, m.get("attempts"))
            logger.debug("monitor_step: monitor state=%s", m)
            homestatus = fetch_homestatus()
            rooms = homestatus.get("body", {}).get("home", {}).get("rooms", [])
            modules = homestatus.get("body", {}).get("home", {}).get("modules", [])
            modules_map = {mm.get("id"): mm for mm in modules}
            cur_room = next((r for r in rooms if str(r.get("id")) == str(room_id)), None)
            if not cur_room:
                # increment attempts and continue
                m["attempts"] += 1
            else:
                cur_temp = cur_room.get("therm_measured_temperature")
                m["attempts"] += 1
                logger.info("monitor_step: room=%s cur_temp=%s initial=%s attempts=%s", room_id, cur_temp, m.get("initial_temp"), m.get("attempts"))
                # log boiler status for BNS modules associated to this room (if present)
                room_module_ids = STATE.get("rooms_map", {}).get(room_id, {}).get("module_ids", [])
                for rid in room_module_ids:
                    mm = modules_map.get(rid)
                    if mm and str(mm.get("type")).upper() == "BNS":
                        logger.info("monitor_step: room=%s BNS module %s boiler_status=%s", room_id, rid, mm.get("boiler_status"))
                # compute delta
                if cur_temp is not None:
                    try:
                        delta = float(cur_temp) - float(m.get("initial_temp"))
                    except Exception:
                        delta = None
                else:
                    delta = None
                logger.info("monitor_step: room=%s temp_delta=%s (threshold=%s)", room_id, delta, TEMP_DELTA)
                if cur_temp is not None and (delta is not None and delta >= TEMP_DELTA):
                    # success: temperature increased enough -> stop monitoring
                    logger.info("monitor success: room=%s temp rose by %s >= %s", room_id, float(cur_temp) - float(m["initial_temp"]), TEMP_DELTA)
                    STATE["monitors"].pop(room_id, None)
                    try:
                        scheduler.remove_job(job_id)
                    except Exception:
                        pass
                    return

            # if reached max attempts -> take action
            if m["attempts"] >= CHECK_ROUNDS:
                # perform PUT to setthermode?mode=away
                try:
                    url = f"{SOURCE_BASE_URL}/setthermode?mode=away"
                    headers = {"accept": "application/json"}
                    logger.warning("monitor action: room=%s reached attempts=%s -> PUT %s", room_id, m["attempts"], url)
                    resp = _make_request_with_retry("PUT", url, headers=headers, timeout=REQUEST_TIMEOUT)
                    logger.info("PUT setthermode response: status=%s text=%s", resp.status_code, (resp.text or "")[:200])
                except (ConnectionError, Timeout) as e:
                    logger.error("setthermode connection failed after retries for room=%s: %s", room_id, str(e)[:150])
                except Exception as e:
                    logger.exception("error calling setthermode for room=%s: %s", room_id, e)
                # cleanup
                STATE["monitors"].pop(room_id, None)
                try:
                    scheduler.remove_job(job_id)
                except Exception:
                    pass
            else:
                logger.debug("monitor_step: room=%s not reached max attempts yet (%s/%s)", room_id, m.get("attempts"), CHECK_ROUNDS)

        except Exception:
            # On unexpected error remove monitor to avoid infinite loops
            STATE["monitors"].pop(room_id, None)
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass

    # schedule interval job every CHECK_INTERVAL_MIN minutes and start after the first interval
    # This ensures the monitor window covers the full 30 minutes (checks at 5,10,...,30)
    next_run = datetime.now(timezone.utc) + timedelta(minutes=CHECK_INTERVAL_MIN)
    scheduler.add_job(monitor_step, "interval", minutes=CHECK_INTERVAL_MIN, id=job_id, next_run_time=next_run)
    logger.info("monitor job scheduled: %s next_run=%s interval_min=%s (starts after first interval)", job_id, next_run.isoformat(), CHECK_INTERVAL_MIN)


def process_homestatus_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"checked_rooms": [], "monitors_started": []}
    rooms = payload.get("body", {}).get("home", {}).get("rooms", [])
    # build module map from homestatus payload for quick lookup
    modules = payload.get("body", {}).get("home", {}).get("modules", [])
    modules_map = {m.get("id"): m for m in modules}

    logger.debug("process_homestatus_payload: modules_map keys=%s", list(modules_map.keys()))

    # Detect global BNS modules and determine global boiler status
    bns_modules = [m for m in modules if str(m.get("type", "")).upper() == "BNS"]
    if bns_modules:
        global_bns_status = any(bool(m.get("boiler_status")) for m in bns_modules)
        STATE["global_boiler_status"] = bool(global_bns_status)
        logger.info("process_homestatus: detected %d BNS module(s) global_boiler_status=%s", len(bns_modules), global_bns_status)
        # If boiler is OFF globally, stop all monitors and skip starting new ones
        if not global_bns_status:
            logger.warning("process_homestatus: global BNS.boiler_status is False -> stopping all monitors and skipping start")
            # cleanup existing monitors
            for running_room in list(STATE.get("monitors", {}).keys()):
                job_id = f"monitor_{running_room}"
                try:
                    scheduler.remove_job(job_id)
                    logger.info("process_homestatus: removed monitor job %s due to boiler OFF", job_id)
                except Exception:
                    logger.debug("process_homestatus: could not remove job %s (may not exist)", job_id)
                STATE["monitors"].pop(running_room, None)
            return result
    else:
        # No BNS modules present in homestatus: keep previous per-room logic
        STATE["global_boiler_status"] = None
        logger.debug("process_homestatus: no BNS modules found; falling back to per-room heating_req behavior")

    for room in rooms:
        room_id = str(room.get("id"))
        heating_req = room.get("heating_power_request", 0)
        measured = room.get("therm_measured_temperature")
        checked = {"room_id": room_id, "heating_power_request": heating_req, "measured": measured}
        result["checked_rooms"].append(checked)

        try:
            logger.debug("process_homestatus_payload: room=%s mapped_module_ids=%s", room_id, STATE.get("rooms_map", {}).get(room_id, {}).get("module_ids", []))

            # Determine if the room is actively requesting heat.
            heat_active = False
            if heating_req and float(heating_req) > 0:
                heat_active = True
            else:
                # If heating_req == 0, inspect valve modules (NRV) in the room as they may indicate active demand
                room_module_ids = STATE.get("rooms_map", {}).get(room_id, {}).get("module_ids", [])
                for mid in room_module_ids:
                    mm = modules_map.get(mid)
                    if not mm:
                        continue
                    mtype = str(mm.get("type", "")).upper()
                    if mtype in VALVE_MODULE_TYPES:
                        # heuristic: check several keys that valve modules may expose
                        for key in VALVE_ACTIVE_KEYS:
                            if key in mm:
                                try:
                                    val = mm.get(key)
                                    if val is None:
                                        continue
                                    # numeric positive values indicate valve opening
                                    if isinstance(val, (int, float)) and float(val) > 0:
                                        heat_active = True
                                        logger.info("process_homestatus: room=%s valve module %s indicates active (key=%s val=%s)", room_id, mid, key, val)
                                        break
                                    # boolean true-like
                                    if isinstance(val, bool) and val:
                                        heat_active = True
                                        logger.info("process_homestatus: room=%s valve module %s indicates active (key=%s val=%s)", room_id, mid, key, val)
                                        break
                                    # string that can be interpreted as numeric
                                    if isinstance(val, str):
                                        try:
                                            if float(val) > 0:
                                                heat_active = True
                                                logger.info("process_homestatus: room=%s valve module %s indicates active (key=%s val=%s)", room_id, mid, key, val)
                                                break
                                        except Exception:
                                            # non-numeric string (e.g., 'open') treat common tokens
                                            if str(val).lower() in ("open", "opened", "on", "active"):
                                                heat_active = True
                                                logger.info("process_homestatus: room=%s valve module %s indicates active (key=%s val=%s)", room_id, mid, key, val)
                                                break
                                except Exception:
                                    continue
                        if heat_active:
                            break

                # Fallback heuristic: if room has both a BNS and a valve module according to homesdata
                # and the global boiler is on, consider the room active even if valve keys are not present
                if not heat_active:
                    try:
                        has_bns = False
                        has_valve = False
                        room_module_ids = STATE.get("rooms_map", {}).get(room_id, {}).get("module_ids", [])
                        for mid in room_module_ids:
                            mm2 = modules_map.get(mid) or {}
                            t2 = str(mm2.get("type", "")).upper()
                            if t2 == "BNS":
                                has_bns = True
                            if t2 in VALVE_MODULE_TYPES:
                                has_valve = True
                        if has_bns and has_valve and STATE.get("global_boiler_status"):
                            heat_active = True
                            logger.info("process_homestatus: room=%s has BNS+VALVE and global boiler on -> treating as active (heuristic)", room_id)
                    except Exception:
                        logger.debug("process_homestatus: heuristic check failed for room %s", room_id)

            if heat_active:
                logger.info("process_homestatus: room=%s determined active -> starting monitor", room_id)
                start_monitor_if_needed(room_id, float(measured) if measured is not None else 0.0)
                result["monitors_started"].append(room_id)
        except Exception:
            logger.exception("process_homestatus: error processing room %s", room_id)

        logger.debug("process_homestatus: room=%s heating_req=%s measured=%s", room_id, heating_req, measured)

    return result


@app.get("/healthz")
def healthz():
    return "ok", 200


@app.get("/status")
def status():
    return jsonify({
        "ok": True,
        "config": {
            "SOURCE_BASE_URL": SOURCE_BASE_URL,
            "CHECK_INTERVAL_MIN": CHECK_INTERVAL_MIN,
            "CHECK_ROUNDS": CHECK_ROUNDS,
            "TEMP_DELTA": TEMP_DELTA,
        },
        "state": {
            "rooms_map": STATE["rooms_map"],
            "monitors": STATE["monitors"],
        },
    }), 200


# Background poller to refresh homesdata map and homestatus processing
def poll_once():
    try:
        # homesdata is fetched only once at startup (it rarely changes)
        logger.debug("poll_once: fetching homestatus")
        homestatus = fetch_homestatus()
        process_homestatus_payload(homestatus)
    except (ConnectionError, Timeout) as e:
        # Log connection errors but continue polling - service may recover
        log_once("poll_connection_error", "warning", 
                 "poll_once: cannot reach upstream service (will retry on next poll): %s", 
                 str(e)[:150], window=300)
    except Exception:
        logger.exception("poll_once: unexpected error fetching homestatus")


# Start a safe background thread that polls every minute
def _start_poll_thread():
    def starter():
        # Fetch homesdata once at startup and build rooms_map
        try:
            logger.info("initial startup: fetching homesdata (only once)")
            homes = fetch_homesdata()
            STATE["rooms_map"] = map_modules_from_homesdata(homes)
        except (ConnectionError, Timeout) as e:
            logger.warning("startup: cannot reach upstream service for homesdata (will retry later): %s", str(e)[:150])
            # Continue with empty rooms_map - it will be populated when service becomes available
        except Exception:
            logger.exception("startup: unexpected error fetching homesdata")

        # initial homestatus poll to detect heating requests immediately
        try:
            logger.info("initial startup: fetching homestatus")
            homestatus = fetch_homestatus()
            process_homestatus_payload(homestatus)
        except (ConnectionError, Timeout) as e:
            logger.warning("startup: cannot reach upstream service for homestatus (will retry later): %s", str(e)[:150])
        except Exception:
            logger.exception("startup: unexpected error fetching homestatus")

        # schedule periodic poll (homestatus only)
        scheduler.add_job(poll_once, "interval", seconds=POLL_INTERVAL_SECONDS, id="poll_once", replace_existing=True)
        logger.info("poll thread started: polling homestatus every %.2f minutes (%s seconds)", POLL_INTERVAL_SECONDS/60.0, POLL_INTERVAL_SECONDS)

    t = threading.Thread(target=starter, daemon=True)
    t.start()


_start_poll_thread()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5050")), debug=False)
