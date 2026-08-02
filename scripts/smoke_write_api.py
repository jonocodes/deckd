"""Smoke test: boot a Server against a throwaway copy of the shipping layouts,
then exercise the layout write API (PUT /layouts/{id}, POST /layouts) end to
end.

Companion to ``scripts/smoke.py`` (which covers the WS action primitives).
This one covers the editor's save/create path: it boots the real ``Server``
code path, runsPUT and POST against the actual ``layouts/firefox.yaml``
comment structure in a temp dir, and prints the resulting files so a human
can eyeball the comment-preservation round-trip that the synthetic pytest
fixtures (``tests/test_layout_write.py``) can't fully represent.

Run with:
    .venv/bin/python scripts/smoke_write_api.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "daemon"))

import aiohttp
from aiohttp.test_utils import TestServer

from deckd.server import Server

LAYOUTS_SRC = Path(__file__).resolve().parent.parent / "layouts"


async def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="deckd-write-smoke-"))
    shutil.copytree(LAYOUTS_SRC, work, dirs_exist_ok=True)
    print(f"layouts copy: {work}")
    before = (work / "firefox.yaml").read_text()
    print(
        f"firefox.yaml before: {sum(1 for _ in before.splitlines())} lines, "
        f"{before.count('#')} comment lines"
    )

    server = Server(layouts_dir=work, host="127.0.0.1", port=0)
    server.start_layouts_watcher()
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    port = ts.port
    print(f"server up on http://127.0.0.1:{port}")
    try:
        async with aiohttp.ClientSession() as http:
            base = f"http://127.0.0.1:{port}"

            print("\n== PUT /layouts/firefox (rename back->back-button, keep forward) ==")
            # `forward` is kept byte-identical to the shipping file so its
            # `# label: Forward` comment (attached to `icon:`) must survive
            # the reconcile — the comment-preservation check at the end.
            async with http.put(
                f"{base}/layouts/firefox",
                json={
                    "match": ["firefox"],
                    "display_name": "Firefox",
                    "theme": "#ff7139",
                    "icon": {"source": "simple-icons", "name": "firefox"},
                    "widgets": [
                        {"id": "back-button", "kind": "button", "label": "Back",
                         "icon": {"source": "lucide", "name": "arrow-left"},
                         "color": "#1e3a8a", "action": {"key": "alt+Left"}},
                        {"id": "forward", "kind": "button",
                         "icon": {"source": "lucide", "name": "arrow-right"},
                         "color": "#1e3a8a", "action": {"key": "alt+Right"}},
                    ],
                },
            ) as r:
                body = await r.json()
                print(f"  status={r.status} ok={body.get('ok')} "
                      f"widget_ids={[w['id'] for w in body.get('layout', {}).get('widgets', [])]}")
                assert r.status == 200 and body.get("ok") is True

            print("\n== PUT 404 unknown id ==")
            async with http.put(f"{base}/layouts/ghost", json={"match": ["ghost"], "widgets": []}) as r:
                print(f"  status={r.status} body={await r.json()}")
                assert r.status == 404

            print("\n== PUT 409 rename (match[0]=chrome via /layouts/firefox) ==")
            async with http.put(f"{base}/layouts/firefox", json={"match": ["chrome"], "widgets": []}) as r:
                print(f"  status={r.status} body={await r.json()}")
                assert r.status == 409

            print("\n== PUT 400 sanitized (duplicate widget id) ==")
            async with http.put(
                f"{base}/layouts/firefox",
                json={"match": ["firefox"], "widgets": [
                    {"id": "x", "kind": "button"}, {"id": "x", "kind": "button"}]},
            ) as r:
                body = await r.json()
                print(f"  status={r.status} body={body}")
                assert r.status == 400
                assert set(body["details"][0].keys()) == {"loc", "msg", "type"}

            print("\n== POST /layouts (create Slack) ==")
            async with http.post(
                f"{base}/layouts",
                json={"match": ["Slack"], "widgets": [
                    {"id": "snooze", "kind": "button", "label": "Snooze", "action": {"shell": "echo hi"}}]},
            ) as r:
                body = await r.json()
                print(f"  status={r.status} ok={body.get('ok')} id={body.get('layout', {}).get('id')}")
                assert r.status == 200 and body.get("ok") is True

            print("\n== POST 409 collision (Slack again) ==")
            async with http.post(f"{base}/layouts", json={"match": ["Slack"], "widgets": []}) as r:
                print(f"  status={r.status} body={await r.json()}")
                assert r.status == 409

            print("\n== POST 400 empty match (structured) ==")
            async with http.post(f"{base}/layouts", json={"match": [], "widgets": []}) as r:
                body = await r.json()
                print(f"  status={r.status} body={body}")
                assert r.status == 400 and body["details"][0]["loc"] == ["match"]

        # watchfiles round-trip: the create should reach the live store.
        for _ in range(40):
            if "Slack" in server.layouts:
                break
            await asyncio.sleep(0.05)
        assert "Slack" in server.layouts, "watchfiles did not reload Slack into the live store"
        print(f"\nlive store: {sorted(l.id for l in server.layouts.layouts)}")
        print(f"slack.yaml on disk: {(work / 'slack.yaml').exists()}")
    finally:
        await server.stop()
        await ts.close()
        await server.scroll.close()

    after = (work / "firefox.yaml").read_text()
    print(f"\nfirefox.yaml after: {sum(1 for _ in after.splitlines())} lines, "
          f"{after.count('#')} comment lines")
    print("first 14 lines:")
    for ln in after.splitlines()[:14]:
        print(f"  {ln}")
    # The unchanged `forward` widget's `# label: Forward` comment (attached
    # to its `icon:` key) must survive at its column — the comment-preservation
    # guarantee that distinguishes the reconcile from a canonical model_dump().
    assert "    # label: Forward\n    icon:\n" in after, (
        "unchanged widget comment lost — reconcile reassigning an unchanged key"
    )
    print("\nslack.yaml:")
    print((work / "slack.yaml").read_text())
    print("OK")


if __name__ == "__main__":
    asyncio.run(main())