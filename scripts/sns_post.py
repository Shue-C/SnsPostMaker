#!/usr/bin/env python3
"""Ceria fi Ixtigna SNS自動投稿スクリプト（Bluesky / X）

外部ライブラリ不要（Python 3.8+ 標準ライブラリのみ）。
認証情報は scripts/.env に置く（書式は scripts/.env.example 参照）。

使い方:
  python3 scripts/sns_post.py bluesky --text "投稿文" [--image 写真.jpg --alt "説明"]
  python3 scripts/sns_post.py x       --text "投稿文" [--image 写真.jpg]
  python3 scripts/sns_post.py bluesky --file post.txt --dry-run

  --file      投稿文をファイルから読む（複数行に便利。--text と排他）
  --image     添付画像（複数指定可、最大4枚）
  --alt       画像の代替テキスト（--image と同じ順で複数指定可）
  --dry-run   投稿せず、文字数チェックと内容確認だけ行う
"""

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"

URL_RE = re.compile(r"https?://[^\s)\]」』】>]+")
TAG_RE = re.compile(r"#[^\s#＃.,、。!?！？()（）\[\]「」]+")

BSKY_PDS = "https://bsky.social"
BSKY_MAX_GRAPHEMES = 300
BSKY_MAX_IMAGE_BYTES = 1_000_000  # 約976KB制限（余裕をみて1MB弱で警告）
X_API = "https://api.x.com"
X_MAX_WEIGHTED = 280  # 全角=2, 半角=1, URL=23換算
MAX_IMAGES = 4


# ---------------------------------------------------------------- 共通
def load_env():
    """scripts/.env を読み込む（環境変数が既にあればそちらを優先）"""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def require_env(keys):
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        die(
            f"認証情報が不足しています: {', '.join(missing)}\n"
            f"scripts/.env.example をコピーして scripts/.env を作成してください。"
        )


def die(msg):
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(1)


def http_json(req):
    """urllib Request を送り、JSONレスポンスを返す。失敗時は本文を表示して終了"""
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        die(f"APIエラー HTTP {e.code}\nURL: {req.full_url}\n応答: {detail}")
    except urllib.error.URLError as e:
        die(f"接続エラー: {e.reason}\nURL: {req.full_url}")


def read_text(args):
    if args.text and args.file:
        die("--text と --file は同時に指定できません")
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8").rstrip("\n")
    elif args.text:
        text = args.text
    else:
        die("--text または --file で投稿文を指定してください")
    if not text.strip():
        die("投稿文が空です")
    return text


def load_images(args):
    images = []
    if not args.image:
        return images
    if len(args.image) > MAX_IMAGES:
        die(f"画像は最大{MAX_IMAGES}枚までです")
    alts = args.alt or []
    for i, path in enumerate(args.image):
        p = Path(path)
        if not p.exists():
            die(f"画像が見つかりません: {path}")
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        if not mime.startswith("image/"):
            die(f"画像ファイルではありません: {path}")
        images.append(
            {
                "path": p,
                "bytes": p.read_bytes(),
                "mime": mime,
                "alt": alts[i] if i < len(alts) else "",
            }
        )
    return images


# ---------------------------------------------------------------- 文字数
def x_weighted_length(text):
    """Xの重み付き文字数。CJK等=2、半角等=1、URL=23固定"""
    urls = URL_RE.findall(text)
    stripped = URL_RE.sub("", text)
    light_ranges = (
        (0x0000, 0x10FF),
        (0x2000, 0x200D),
        (0x2010, 0x201F),
        (0x2032, 0x2037),
    )
    total = 0
    for ch in stripped:
        cp = ord(ch)
        total += 1 if any(lo <= cp <= hi for lo, hi in light_ranges) else 2
    total += 23 * len(urls)
    return total


def check_length(platform, text):
    if platform == "x":
        n = x_weighted_length(text)
        limit = X_MAX_WEIGHTED
        label = f"重み付き {n}/{limit}（全角=2換算）"
    else:
        n = len(text)
        limit = BSKY_MAX_GRAPHEMES
        label = f"{n}/{limit} 字"
    print(f"文字数: {label}")
    if n > limit:
        die(f"{platform} の文字数制限を超えています。削ってから再実行してください。")


# ---------------------------------------------------------------- Bluesky
def bsky_facets(text):
    """URLとハッシュタグをリンク化する facets を生成（byteはUTF-8オフセット）"""
    facets = []

    def byte_index(char_index):
        return len(text[:char_index].encode("utf-8"))

    for m in URL_RE.finditer(text):
        facets.append(
            {
                "index": {"byteStart": byte_index(m.start()), "byteEnd": byte_index(m.end())},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}],
            }
        )
    for m in TAG_RE.finditer(text):
        facets.append(
            {
                "index": {"byteStart": byte_index(m.start()), "byteEnd": byte_index(m.end())},
                "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(0)[1:]}],
            }
        )
    return facets


def post_bluesky(text, images, dry_run):
    check_length("bluesky", text)
    facets = bsky_facets(text)
    if facets:
        kinds = [f["features"][0]["$type"].rsplit("#", 1)[-1] for f in facets]
        print(f"リンク化: {len(facets)}箇所（{', '.join(kinds)}）")
    for img in images:
        if len(img["bytes"]) > BSKY_MAX_IMAGE_BYTES:
            die(
                f"Blueskyの画像サイズ上限(約976KB)を超えています: {img['path']}"
                f"（{len(img['bytes'])//1024}KB）。縮小してから再実行してください。"
            )
        if not img["alt"]:
            print(f"注意: {img['path'].name} に --alt（代替テキスト）がありません")

    if dry_run:
        print("--- dry-run（投稿しません）---")
        print(text)
        return

    require_env(["BSKY_HANDLE", "BSKY_APP_PASSWORD"])
    handle = os.environ["BSKY_HANDLE"].lstrip("@")

    session = http_json(
        urllib.request.Request(
            f"{BSKY_PDS}/xrpc/com.atproto.server.createSession",
            data=json.dumps(
                {"identifier": handle, "password": os.environ["BSKY_APP_PASSWORD"]}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    )
    auth = {"Authorization": f"Bearer {session['accessJwt']}"}

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "langs": ["ja"],
    }
    if facets:
        record["facets"] = facets

    if images:
        blobs = []
        for img in images:
            up = http_json(
                urllib.request.Request(
                    f"{BSKY_PDS}/xrpc/com.atproto.repo.uploadBlob",
                    data=img["bytes"],
                    headers={**auth, "Content-Type": img["mime"]},
                    method="POST",
                )
            )
            blobs.append({"image": up["blob"], "alt": img["alt"]})
            print(f"画像アップロード完了: {img['path'].name}")
        record["embed"] = {"$type": "app.bsky.embed.images", "images": blobs}

    result = http_json(
        urllib.request.Request(
            f"{BSKY_PDS}/xrpc/com.atproto.repo.createRecord",
            data=json.dumps(
                {"repo": session["did"], "collection": "app.bsky.feed.post", "record": record}
            ).encode(),
            headers={**auth, "Content-Type": "application/json"},
            method="POST",
        )
    )
    rkey = result["uri"].rsplit("/", 1)[-1]
    print(f"Blueskyに投稿しました: https://bsky.app/profile/{handle}/post/{rkey}")


# ---------------------------------------------------------------- X (OAuth 1.0a)
def oauth1_header(method, url, consumer_key, consumer_secret, token, token_secret):
    def enc(s):
        return urllib.parse.quote(str(s), safe="")

    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    base_url = url.split("?", 1)[0]
    query = urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)
    all_params = sorted([(enc(k), enc(v)) for k, v in list(params.items()) + query])
    param_string = "&".join(f"{k}={v}" for k, v in all_params)
    base = f"{method.upper()}&{enc(base_url)}&{enc(param_string)}"
    key = f"{enc(consumer_secret)}&{enc(token_secret)}"
    sig = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    params["oauth_signature"] = sig
    header = "OAuth " + ", ".join(f'{enc(k)}="{enc(v)}"' for k, v in sorted(params.items()))
    return header


def x_request(method, url, creds, json_body=None, multipart=None):
    headers = {
        "Authorization": oauth1_header(
            method, url, creds["key"], creds["secret"], creds["token"], creds["token_secret"]
        )
    }
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif multipart is not None:
        boundary = "----sns" + secrets.token_hex(12)
        parts = []
        for name, value in multipart.items():
            if isinstance(value, tuple):  # (filename, bytes, mime)
                filename, content, mime = value
                parts.append(
                    b"--" + boundary.encode() + b"\r\n"
                    b'Content-Disposition: form-data; name="' + name.encode()
                    + b'"; filename="' + filename.encode() + b'"\r\n'
                    b"Content-Type: " + mime.encode() + b"\r\n\r\n" + content + b"\r\n"
                )
            else:
                parts.append(
                    b"--" + boundary.encode() + b"\r\n"
                    b'Content-Disposition: form-data; name="' + name.encode()
                    + b'"\r\n\r\n' + str(value).encode() + b"\r\n"
                )
        data = b"".join(parts) + b"--" + boundary.encode() + b"--\r\n"
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    return http_json(urllib.request.Request(url, data=data, headers=headers, method=method))


def x_upload_image(img, creds):
    """v2 chunked media upload: initialize → append → finalize"""
    init = x_request(
        "POST",
        f"{X_API}/2/media/upload/initialize",
        creds,
        json_body={
            "media_type": img["mime"],
            "total_bytes": len(img["bytes"]),
            "media_category": "tweet_image",
        },
    )
    media_id = init["data"]["id"]
    x_request(
        "POST",
        f"{X_API}/2/media/upload/{media_id}/append",
        creds,
        multipart={
            "segment_index": 0,
            "media": (img["path"].name, img["bytes"], img["mime"]),
        },
    )
    x_request("POST", f"{X_API}/2/media/upload/{media_id}/finalize", creds)
    print(f"画像アップロード完了: {img['path'].name}")
    return media_id


def post_x(text, images, dry_run):
    check_length("x", text)

    if dry_run:
        print("--- dry-run（投稿しません）---")
        print(text)
        return

    require_env(["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"])
    creds = {
        "key": os.environ["X_API_KEY"],
        "secret": os.environ["X_API_SECRET"],
        "token": os.environ["X_ACCESS_TOKEN"],
        "token_secret": os.environ["X_ACCESS_SECRET"],
    }

    body = {"text": text}
    if images:
        media_ids = [x_upload_image(img, creds) for img in images]
        body["media"] = {"media_ids": media_ids}
        for media_id, img in zip(media_ids, images):
            if img["alt"]:
                x_request(
                    "POST",
                    f"{X_API}/2/media/metadata",
                    creds,
                    json_body={
                        "id": media_id,
                        "metadata": {"alt_text": {"text": img["alt"][:1000]}},
                    },
                )

    result = x_request("POST", f"{X_API}/2/tweets", creds, json_body=body)
    tweet_id = result["data"]["id"]
    print(f"Xに投稿しました: https://x.com/i/web/status/{tweet_id}")
    print("※無料枠の目安: 500投稿/月・17投稿/24時間")


# ---------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description="Bluesky / X 自動投稿")
    parser.add_argument("platform", choices=["bluesky", "x"], help="投稿先SNS")
    parser.add_argument("--text", help="投稿文")
    parser.add_argument("--file", help="投稿文のファイルパス（複数行向け）")
    parser.add_argument("--image", action="append", help="添付画像（複数指定可・最大4枚）")
    parser.add_argument("--alt", action="append", help="画像の代替テキスト（--imageと同順）")
    parser.add_argument("--dry-run", action="store_true", help="投稿せず内容確認のみ")
    args = parser.parse_args()

    load_env()
    text = read_text(args)
    images = load_images(args)

    if args.platform == "bluesky":
        post_bluesky(text, images, args.dry_run)
    else:
        post_x(text, images, args.dry_run)


if __name__ == "__main__":
    main()
