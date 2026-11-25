"""Clients for the services jobs read: Prometheus, Pi-hole, LogLook, ulmo, Home Assistant, plain HTTP probes and the Uptime Kuma
heartbeat. Every call returns data or {'error': ...}; nothing here raises, so one broken source never stops a run."""
import json

import httpx

import config

_client = None


def client():
    global _client
    if _client is None:
        _client = httpx.Client(follow_redirects=True, headers={"User-Agent": "mandos"})
    return _client


def _err(e):
    return {"error": str(e)[:300]}


def get_json(url, params=None, headers=None, timeout=30):
    try:
        r = client().get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}", "statusCode": r.status_code}
        if not r.content.strip():
            return {}          # an empty body: LogLook answers a log with no lines like this ("checked, empty")
        return r.json()
    except Exception as e:  # noqa: BLE001
        return _err(e)


def full(method, url, params=None, headers=None, json_body=None, timeout=30, text=False):
    """{statusCode, body|data} or {error}; never raises."""
    try:
        r = client().request(method, url, params=params, headers=headers, json=json_body, timeout=timeout)
        out = {"statusCode": r.status_code}
        if text:
            out["data"] = r.text
        else:
            try:
                out["body"] = r.json()
            except ValueError:
                out["body"] = r.text
        return out
    except Exception as e:  # noqa: BLE001
        return _err(e)


# ---------------------------------------------------------------- Prometheus
def prom(query, timeout=30):
    return get_json(config.PROM_URL + "/api/v1/query", {"query": query}, timeout=timeout)


# ---------------------------------------------------------------- Pi-hole v6 (read-only API, no auth)
def pihole(path, params=None, timeout=10):
    return get_json(config.PIHOLE_URL + "/api/" + path, params, timeout=timeout)


# ---------------------------------------------------------------- LogLook
def loglook(path, query=None, timeout=60):
    return get_json(config.LOGLOOK_URL + "/v1/" + path, query or {},
                    headers={"Authorization": "Bearer " + config.LOGLOOK_TOKEN}, timeout=timeout)


# ---------------------------------------------------------------- plain HTTP probe
def probe(url, timeout=8):
    return full("GET", url, timeout=timeout, text=True)


# ---------------------------------------------------------------- ulmo agent API (read-only commands, catalog, runs, approvals)
def _ulmo_h():
    return {"Authorization": "Bearer " + config.ULMO_TOKEN}


def ulmo_command(command, host, params=None, wait=55, note=None, timeout=65):
    body = {"command": command, "host": host, "params": params or {}}
    if note:
        body["note"] = note
    return full("POST", f"{config.ULMO_URL}/api/v1/commands?wait={wait}", headers=_ulmo_h(), json_body=body, timeout=timeout)


def ulmo_get(path, params=None, timeout=10):
    return get_json(config.ULMO_URL + path, params, headers=_ulmo_h(), timeout=timeout)


def ulmo_full(method, path, params=None, json_body=None, timeout=30):
    return full(method, config.ULMO_URL + path, params=params, headers=_ulmo_h(), json_body=json_body, timeout=timeout)


def ulmo_admin(method, path, params=None, json_body=None, timeout=30):
    return full(method, config.ULMO_URL + path, params=params, json_body=json_body, timeout=timeout,
                headers={"Authorization": "Bearer " + config.ULMO_CHANGE_TOKEN})


# ---------------------------------------------------------------- Home Assistant (admin token; fixed calls only, never an LLM)
def _ha_h(extra=None):
    h = {"Authorization": "Bearer " + config.HA_TOKEN}
    h.update(extra or {})
    return h


def ha(method, path, json_body=None, headers=None, timeout=60):
    return full(method, config.HA_URL + path, headers=_ha_h(headers), json_body=json_body, timeout=timeout, text=True)


# ---------------------------------------------------------------- heartbeat
def heartbeat():
    if config.SHADOW or not config.KUMA_PUSH_URL:
        return {"skipped": True}
    return get_json(config.KUMA_PUSH_URL, timeout=10)
