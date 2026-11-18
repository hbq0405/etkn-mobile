"""Mirror Alumos' published APKs without building or changing their bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

SOURCE = "Alumos/etkn-mobile"
MARKER = "\n\n<!-- etkn-mobile-sync:"


def api(path, method="GET", payload=None, missing_ok=False):
    command = ["gh", "api", path, "--method", method]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        if missing_ok and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(f"GitHub {method} {path} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def releases(repo):
    found = []
    page = 1
    while True:
        batch = api(f"repos/{repo}/releases?per_page=100&page={page}")
        found.extend(batch)
        if len(batch) < 100:
            return found
        page += 1


def selected_assets(release):
    assets = [a for a in release["assets"]
              if a["name"].lower().endswith(".apk") or a["name"] == "SHA256SUMS.txt"]
    if not any(a["name"].lower().endswith(".apk") for a in assets):
        raise RuntimeError(f"No published APK for {release['tag_name']}; retry later")
    for asset in assets:
        if Path(asset["name"]).name != asset["name"] or "\\" in asset["name"]:
            raise RuntimeError("Unsafe upstream asset filename")
        digest = asset.get("digest") or ""
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise RuntimeError(f"Upstream SHA-256 unavailable for {asset['name']}; retry later")
    return assets


def download(asset, folder):
    path = Path(folder) / asset["name"]
    digest = hashlib.sha256()
    with urllib.request.urlopen(asset["browser_download_url"], timeout=120) as response, path.open("wb") as out:
        while block := response.read(1024 * 1024):
            digest.update(block)
            out.write(block)
    if path.stat().st_size != asset["size"] or "sha256:" + digest.hexdigest() != asset["digest"]:
        raise RuntimeError(f"Upstream asset integrity failed: {asset['name']}")
    return path


def state_for(source, mirror, notify_from):
    body = mirror.get("body") or ""
    if MARKER in body:
        state = json.loads(body.rsplit(MARKER, 1)[1].removesuffix(" -->"))
        if state.get("source_id") == source["id"]:
            return state
    return {"source_id": source["id"],
            "telegram": "pending" if source["published_at"] >= notify_from else "historical"}


def release_body(source, state):
    tag = urllib.parse.quote(source["tag_name"], safe="")
    text = (f"原作者与项目：[Alumos/etkn-mobile](https://github.com/{SOURCE})\n\n"
            f"上游发布：{source['html_url']}\n\n"
            f"对应版本源码（GPL-3.0）：https://github.com/{SOURCE}/archive/refs/tags/{tag}.tar.gz\n\n"
            "本仓库仅同步上游原始 APK 与校验文件，不重新编译或重新签名。\n\n---\n\n"
            + (source.get("body") or "发布说明详见上游发布页面。"))
    return text + MARKER + json.dumps(state, ensure_ascii=False, sort_keys=True) + " -->"


def message_text(source, mirror):
    heading = "ETKN 安卓手机端新版本\n\n版本：" + (source["name"] or source["tag_name"])
    footer = f"\n\n下载：{mirror['html_url']}\n原作者：Alumos\n上游：{source['html_url']}"
    notes = "\n\n更新日志：\n" + (source.get("body") or "详见下载页面")
    remaining = 4000 - len((heading + footer).encode("utf-16-le")) // 2
    if remaining < 1:
        raise RuntimeError("Release title or URL is too long for Telegram")
    if len(notes.encode("utf-16-le")) // 2 > remaining:
        notes = notes.encode("utf-16-le")[:(remaining - 1) * 2].decode("utf-16-le", errors="ignore") + "…"
    return heading + notes + footer


def notify(source, mirror):
    token, chat = os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_TO"]
    payload = {"chat_id": chat, "text": message_text(source, mirror),
               "link_preview_options": {"is_disabled": True}}
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Telegram delivery failed (HTTP {error.code})") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Telegram delivery connection failed") from None
    message_id = result.get("result", {}).get("message_id")
    if not result.get("ok") or not message_id:
        raise RuntimeError("Telegram did not confirm delivery")
    return message_id


def sync_one(repo, source, latest_tag, notify_from):
    assets = selected_assets(source)
    tag = source["tag_name"]
    base = f"repos/{repo}/releases"
    mirror = api(f"{base}/tags/{urllib.parse.quote(tag, safe='')}", missing_ok=True) or {}
    state = state_for(source, mirror, notify_from)
    body = release_body(source, state)
    if not mirror:
        mirror = api(base, "POST", {"tag_name": tag, "name": source["name"] or tag,
                                   "body": body, "draft": True, "prerelease": source["prerelease"]})
    existing = {a["name"]: a for a in mirror["assets"]}
    with tempfile.TemporaryDirectory(prefix="etkn-mobile-sync-") as folder:
        for asset in assets:
            current = existing.get(asset["name"], {})
            if current.get("digest") == asset["digest"] and current.get("size") == asset["size"]:
                continue
            path = download(asset, folder)
            subprocess.run(["gh", "release", "upload", tag, str(path), "--repo", repo, "--clobber"], check=True)
            print(f"Verified and uploaded {tag}/{asset['name']}")
    mirror = api(f"{base}/{mirror['id']}")
    uploaded = {a["name"]: a for a in mirror["assets"]}
    if any(uploaded.get(a["name"], {}).get("digest") != a["digest"]
           or uploaded.get(a["name"], {}).get("size") != a["size"] for a in assets):
        raise RuntimeError(f"Mirror integrity check failed for {tag}")
    if (mirror.get("body") != body or mirror["draft"] or mirror["name"] != (source["name"] or tag)
            or mirror["prerelease"] != source["prerelease"]):
        mirror = api(f"{base}/{mirror['id']}", "PATCH",
                     {"name": source["name"] or tag, "body": body, "draft": False,
                      "prerelease": source["prerelease"], "make_latest": "true" if tag == latest_tag else "false"})
    if state["telegram"] == "pending":
        state["message_id"] = notify(source, mirror)
        state["telegram"] = "sent"
        api(f"{base}/{mirror['id']}", "PATCH", {"body": release_body(source, state)})
        print(f"Telegram delivered {tag}; message_id={state['message_id']}")
    print(f"Synchronized {tag}; Telegram={state['telegram']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = os.environ["GITHUB_REPOSITORY"]
    if repo == SOURCE:
        raise RuntimeError("Destination must differ from upstream")
    notify_from = os.environ["NOTIFY_FROM"]
    if not args.dry_run and not all(os.environ.get(k) for k in ("TELEGRAM_TOKEN", "TELEGRAM_TO")):
        raise RuntimeError("Configure TELEGRAM_TOKEN and TELEGRAM_TO repository secrets")
    source = sorted((r for r in releases(SOURCE) if not r["draft"]), key=lambda r: r["published_at"])
    stable = [r for r in source if not r["prerelease"]]
    latest_tag = stable[-1]["tag_name"] if stable else None
    for release in source:
        if args.dry_run:
            print(f"{release['tag_name']}: {len(selected_assets(release))} assets; "
                  f"notify={release['published_at'] >= notify_from}")
        else:
            sync_one(repo, release, latest_tag, notify_from)


if __name__ == "__main__":
    main()