#!/usr/bin/env python3
"""
Temperature Corrector Script
Compares Home Assistant sensor temperatures with climate thermostat temperatures
and corrects Netatmo true temperature when delta exceeds threshold.

Automatically fetches room IDs from Netatmo API at startup.
"""

import os
import sys
import time
import logging
import threading
from typing import Dict, Any, Optional, List
import requests
from flask import Flask, jsonify

# Configuration from environment variables
HOMEASSISTANT_URL = os.getenv("HOMEASSISTANT_URL", "http://192.168.1.102:8123")
HOMEASSISTANT_TOKEN = os.getenv("HOMEASSISTANT_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI3YmZjY2MyZDg5YmQ0M2JlOWI1MjMxMDUyMTRkZGY2OSIsImlhdCI6MTc2NjEwNTgyOCwiZXhwIjoyMDgxNDY1ODI4fQ.eNUNY0_0f4vpCfVy2C_cPruidQl-Ghu2yJ73w31rtSU")
NETATMO_API_URL = os.getenv("NETATMO_API_URL", "http://netatmo-tt-system-netatmo-system.apps-crc.testing")
TEMP_DELTA_THRESHOLD = float(os.getenv("TEMP_DELTA_THRESHOLD", "0.8"))
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))  # 5 minutes
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10"))
FLASK_PORT = int(os.getenv("FLASK_PORT", "8080"))

# Room name mappings: room_name_lowercase -> (sensor_entity_id, climate_entity_id)
# Maps Netatmo room names to Home Assistant entities
ROOM_NAME_MAPPINGS = {
    "soggiorno": ("sensor.sonoff_soggiorno_temperatura", "climate.soggiorno"),
    "ufficio": ("sensor.sonoff_studio_temperatura", "climate.ufficio"),
    "bagno": ("sensor.sonoff_bagno_temperatura", "climate.bagno"),
    "camera da letto": ("sensor.sonoff_camera_da_letto_temperatura", "climate.camera_da_letto"),
}

# Logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [temperature-corrector] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("temperature-corrector")

# Flask app
app = Flask(__name__)

# Silence Werkzeug access logs (health/liveness probes flood the logs at INFO level)
try:
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
except Exception:
    pass

# Global room mappings: sensor_id -> (climate_id, room_id, room_name)
ROOM_MAPPINGS: Dict[str, tuple] = {}

# Health status tracking
last_check_time = None
last_check_success = False
total_checks = 0
total_corrections = 0


def fetch_homestatus() -> Dict[str, Any]:
    """Fetch homestatus from Netatmo API to get module information"""
    url = f"{NETATMO_API_URL}/homestatus"
    
    try:
        logger.info("Fetching homestatus from Netatmo API: %s", url)
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        logger.error("Failed to fetch homestatus: %s", str(e)[:200])
        return {}


def get_bns_module_ids(homestatus_data: Dict[str, Any]) -> List[str]:
    """Extract BNS module IDs from homestatus data"""
    modules = homestatus_data.get("body", {}).get("home", {}).get("modules", [])
    bns_ids = [module["id"] for module in modules if module.get("type") == "BNS"]
    logger.info("Found %d BNS modules: %s", len(bns_ids), bns_ids)
    return bns_ids


def fetch_netatmo_rooms() -> List[Dict[str, Any]]:
    """Fetch rooms from Netatmo API"""
    url = f"{NETATMO_API_URL}/homesdata"
    
    try:
        logger.info("Fetching room data from Netatmo API: %s", url)
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        homes = data.get("body", {}).get("homes", [])
        if not homes:
            logger.error("No homes found in Netatmo response")
            return []
        
        home = homes[0]
        rooms = home.get("rooms", [])
        logger.info("Found %d rooms in Netatmo home", len(rooms))
        
        return rooms
    except requests.exceptions.RequestException as e:
        logger.error("Failed to fetch Netatmo rooms: %s", str(e)[:200])
        return []


def build_room_mappings() -> bool:
    """Build room mappings from Netatmo API, excluding rooms with BNS devices"""
    global ROOM_MAPPINGS
    
    logger.info("=== Building Room Mappings ===")
    
    # Fetch homestatus to get BNS module IDs
    homestatus_data = fetch_homestatus()
    if not homestatus_data:
        logger.error("Could not fetch homestatus")
        return False
    
    bns_module_ids = get_bns_module_ids(homestatus_data)
    
    # Fetch rooms from Netatmo
    netatmo_rooms = fetch_netatmo_rooms()
    if not netatmo_rooms:
        logger.error("Could not fetch Netatmo rooms")
        return False
    
    # Build mappings
    mapped_count = 0
    excluded_count = 0
    
    for room in netatmo_rooms:
        room_id = room.get("id")
        room_name = room.get("name", "")
        room_name_lower = room_name.lower()
        module_ids = room.get("module_ids", [])
        
        logger.debug("Processing Netatmo room: id=%s name='%s' modules=%s", room_id, room_name, module_ids)
        
        # Check if room has a BNS module
        has_bns = any(module_id in bns_module_ids for module_id in module_ids)
        
        if has_bns:
            logger.info("⊗ Excluding room '%s' (id=%s) - has BNS device (accurate temperature)", 
                       room_name, room_id)
            excluded_count += 1
            continue
        
        # Try to find matching HA entities
        if room_name_lower in ROOM_NAME_MAPPINGS:
            sensor_id, climate_id = ROOM_NAME_MAPPINGS[room_name_lower]
            ROOM_MAPPINGS[sensor_id] = (climate_id, str(room_id), room_name)
            logger.info("✓ Mapped room '%s': sensor=%s climate=%s room_id=%s", 
                       room_name, sensor_id, climate_id, room_id)
            mapped_count += 1
        else:
            logger.warning("✗ No mapping found for Netatmo room '%s' (id=%s)", room_name, room_id)
    
    logger.info("=== Mapping Complete: %d rooms mapped, %d rooms excluded (BNS) ===", 
                mapped_count, excluded_count)
    
    if mapped_count == 0:
        logger.warning("No rooms were mapped! All rooms may have BNS devices or check ROOM_NAME_MAPPINGS configuration")
    
    return True


def get_homeassistant_state(entity_id: str) -> Optional[Dict[str, Any]]:
    """Fetch entity state from Home Assistant API"""
    url = f"{HOMEASSISTANT_URL}/api/states/{entity_id}"
    headers = {
        "Authorization": f"Bearer {HOMEASSISTANT_TOKEN}",
        "Content-Type": "application/json",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error("Failed to get state for %s: %s", entity_id, str(e)[:200])
        return None


def get_temperature(entity_id: str, is_climate: bool = False) -> Optional[float]:
    """Get temperature value from Home Assistant entity"""
    state_data = get_homeassistant_state(entity_id)
    if not state_data:
        return None
    
    try:
        if is_climate:
            # For climate entities, temperature is in attributes.current_temperature
            temp = state_data.get("attributes", {}).get("current_temperature")
        else:
            # For sensor entities, temperature is in state
            temp = state_data.get("state")
        
        if temp is None or temp == "unavailable" or temp == "unknown":
            return None
        
        return float(temp)
    except (ValueError, TypeError) as e:
        logger.warning("Invalid temperature value for %s: %s", entity_id, e)
        return None


def set_true_temperature(room_id: str, corrected_temperature: float) -> bool:
    """Send corrected temperature to Netatmo API"""
    url = f"{NETATMO_API_URL}/truetemperature/{room_id}"
    params = {"corrected_temperature": corrected_temperature}
    headers = {"accept": "application/json"}
    
    try:
        logger.info("Setting true temperature for room %s to %.1f°C", room_id, corrected_temperature)
        response = requests.put(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        logger.info("✓ Successfully set true temperature: status=%s", response.status_code)
        return True
    except requests.exceptions.RequestException as e:
        logger.error("Failed to set true temperature for room %s: %s", room_id, str(e)[:200])
        return False


def check_and_correct_room(sensor_id: str, climate_id: str, room_id: str, room_name: str) -> None:
    """Check temperature delta and correct if needed"""
    logger.debug("Checking room '%s': sensor=%s climate=%s room_id=%s", room_name, sensor_id, climate_id, room_id)
    
    # Get sensor temperature (true/accurate temperature)
    sensor_temp = get_temperature(sensor_id, is_climate=False)
    if sensor_temp is None:
        logger.warning("Could not get sensor temperature for %s (%s)", sensor_id, room_name)
        return
    
    # Get climate temperature (Netatmo thermostat temperature)
    climate_temp = get_temperature(climate_id, is_climate=True)
    if climate_temp is None:
        logger.warning("Could not get climate temperature for %s (%s)", climate_id, room_name)
        return
    
    # Calculate delta (absolute value)
    delta = abs(sensor_temp - climate_temp)
    
    logger.info(
        "Room '%s': sensor=%.1f°C climate=%.1f°C delta=%.1f°C (threshold=%.1f°C)",
        room_name, sensor_temp, climate_temp, delta, TEMP_DELTA_THRESHOLD
    )
    
    # Check if correction is needed
    if delta > TEMP_DELTA_THRESHOLD:
        global total_corrections
        logger.warning(
            "⚠ Temperature delta %.1f°C exceeds threshold %.1f°C - correcting room '%s'",
            delta, TEMP_DELTA_THRESHOLD, room_name
        )
        if set_true_temperature(room_id, sensor_temp):
            total_corrections += 1
    else:
        logger.debug("✓ Temperature delta within threshold - no correction needed for '%s'", room_name)


def run_check_cycle() -> None:
    """Run one check cycle for all configured rooms"""
    global last_check_time, last_check_success, total_checks
    
    logger.info("=== Starting temperature check cycle ===")
    
    if not ROOM_MAPPINGS:
        logger.error("No room mappings configured - cannot perform checks")
        last_check_success = False
        return
    
    try:
        for sensor_id, (climate_id, room_id, room_name) in ROOM_MAPPINGS.items():
            try:
                check_and_correct_room(sensor_id, climate_id, room_id, room_name)
            except Exception as e:
                logger.exception("Error checking room '%s' (sensor=%s): %s", room_name, sensor_id, e)
        
        last_check_success = True
        total_checks += 1
    except Exception as e:
        logger.exception("Error in check cycle: %s", e)
        last_check_success = False
    finally:
        last_check_time = time.time()
    
    logger.info("=== Check cycle completed ===")


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    status = {
        "status": "healthy" if last_check_success else "unhealthy",
        "service": "temperature-corrector",
        "mapped_rooms": len(ROOM_MAPPINGS),
        "total_checks": total_checks,
        "total_corrections": total_corrections,
        "last_check_time": last_check_time,
        "check_interval_seconds": CHECK_INTERVAL_SECONDS,
    }
    
    return jsonify(status), 200 if last_check_success else 503


def run_check_loop():
    """Run the temperature check loop in a separate thread"""
    logger.info("Temperature Corrector check loop starting...")
    logger.info("Home Assistant URL: %s", HOMEASSISTANT_URL)
    logger.info("Netatmo API URL: %s", NETATMO_API_URL)
    logger.info("Temperature delta threshold: %.1f°C", TEMP_DELTA_THRESHOLD)
    logger.info("Check interval: %d seconds", CHECK_INTERVAL_SECONDS)
    
    if not HOMEASSISTANT_TOKEN:
        logger.warning("HOMEASSISTANT_TOKEN not set - Home Assistant authentication may fail")
    
    # Build room mappings from Netatmo API
    if not build_room_mappings():
        logger.error("Failed to build room mappings - exiting")
        sys.exit(1)
    
    logger.info("Configured rooms: %d", len(ROOM_MAPPINGS))
    
    # Run continuous loop
    while True:
        try:
            run_check_cycle()
        except Exception as e:
            logger.exception("Unexpected error in check cycle: %s", e)
        
        # Wait for next cycle
        logger.debug("Sleeping for %d seconds until next check", CHECK_INTERVAL_SECONDS)
        time.sleep(CHECK_INTERVAL_SECONDS)


def main():
    """Main entry point"""
    logger.info("Temperature Corrector starting...")
    logger.info("Home Assistant URL: %s", HOMEASSISTANT_URL)
    logger.info("Netatmo API URL: %s", NETATMO_API_URL)
    logger.info("Temperature delta threshold: %.1f°C", TEMP_DELTA_THRESHOLD)
    logger.info("Check interval: %d seconds", CHECK_INTERVAL_SECONDS)
    logger.info("Flask port: %d", FLASK_PORT)
    
    if not HOMEASSISTANT_TOKEN:
        logger.warning("HOMEASSISTANT_TOKEN not set - Home Assistant authentication may fail")
    
    # Build room mappings from Netatmo API
    if not build_room_mappings():
        logger.error("Failed to build room mappings - exiting")
        sys.exit(1)
    
    logger.info("Configured rooms: %d", len(ROOM_MAPPINGS))
    
    # Start check loop in separate thread
    check_thread = threading.Thread(target=run_check_loop, daemon=True)
    check_thread.start()
    logger.info("Check loop thread started")
    
    # Start Flask app
    logger.info("Starting Flask server on port %d", FLASK_PORT)
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Temperature Corrector stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        sys.exit(1)
