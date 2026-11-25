"""Pushover, the only alert channel. In shadow mode every title starts with '[mandos shadow]' so the two systems can be told apart."""
import config
import sources

API = "https://api.pushover.net/1/messages.json"
sent = []   # tests read this


def push(title, message, priority=0, url=None, url_title=None, retries=3):
    if config.SHADOW:
        title = "[mandos shadow] " + title
    data = {"token": config.PUSHOVER_TOKEN, "user": config.PUSHOVER_USER, "title": title[:250], "message": message[:1024], "priority": priority}
    if url:
        data["url"] = url
        data["url_title"] = url_title or "Open"
    sent.append(data)
    if not config.PUSHOVER_TOKEN:
        return {"skipped": "no PUSHOVER_TOKEN"}
    last = None
    for _ in range(retries):
        try:
            r = sources.client().post(API, data=data, timeout=20)
            if r.status_code < 500:
                return r.json()
            last = r.text[:200]
        except Exception as e:  # noqa: BLE001
            last = str(e)[:200]
    return {"error": last}
