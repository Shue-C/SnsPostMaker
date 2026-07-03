# 自動投稿スクリプト（Bluesky / X）

`sns_post.py` で Bluesky と X に投稿できます。外部ライブラリ不要（Python 3.8+）。
Instagram / Threads は API が有料・審査制のため、引き続き手動コピペ運用です。

## セットアップ（初回のみ）

1. `scripts/.env.example` をコピーして `scripts/.env` を作る。
2. **Bluesky**: アプリ → 設定 → プライバシーとセキュリティ → **アプリパスワード**で
   新規発行し、`BSKY_APP_PASSWORD` に記入（本パスワードは使わない）。
3. **X**: [developer.x.com](https://developer.x.com/) のアプリ設定で
   権限を **Read and write** にし、**API Key/Secret** と
   **Access Token/Secret** を発行して記入。
   ※権限を変更した場合、Access Token は再生成が必要です。

`scripts/.env` は `.gitignore` に登録済みです。**GitHubにアップしないでください。**

## 使い方

```bash
# まず dry-run で文字数と内容を確認（投稿されません）
python3 scripts/sns_post.py bluesky --text "投稿文" --dry-run

# Bluesky に投稿（URL・ハッシュタグは自動でリンク化されます）
python3 scripts/sns_post.py bluesky --text "新作できました✨ https://cir.booth.pm/"

# X に投稿
python3 scripts/sns_post.py x --text "投稿文"

# 画像付き（最大4枚。--alt は目の不自由な方向けの説明文）
python3 scripts/sns_post.py x --image photo.jpg --alt "真鍮の懐中時計型ペンダント" --text "..."

# 長文はファイルから
python3 scripts/sns_post.py bluesky --file draft.txt
```

## X 無料枠の制限（2026年7月時点）

| 項目 | 上限 |
|---|---|
| 投稿数 | **500件/月**、**17件/24時間** |
| 画像アップロード | 可（initialize/finalize 各17回/24時間） |
| 読み取り | 100件/月（実質書き込み専用） |

- 週2〜3回の運用（月10〜15投稿）なら余裕で収まります。
- 無料枠は既存アカウントの継続提供です（新規受付は終了し、従量課金制に移行）。
  プラン変更の案内が来た場合は researcher に最新状況を調べさせてください。

## 制限・注意

- Bluesky の画像は1枚あたり約976KBまで。超える場合は縮小してから。
- X の文字数は全角=2・半角=1・URL=23字換算で280まで（日本語なら約140字）。
  スクリプトが投稿前に自動チェックします。
- 投稿の削除はスクリプトからはできません。各SNSのアプリから行ってください。
