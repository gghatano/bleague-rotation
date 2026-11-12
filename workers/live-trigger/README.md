# live-trigger

Cloudflare Workers の Cron Trigger から、`live.yml` を `workflow_dispatch` で15分毎に起動する。
処理（取得・解析・Pages公開）は従来どおり GitHub Actions で動く。Worker は起動の合図だけを送る。

Actions の `schedule` は1日40回の予定に対して実際には2〜3回しか起動せず、時刻もずれていたため。

## セットアップ

1. GitHub で fine-grained personal access token を作る
   - Repository access: `gghatano/bleague-rotation` のみ
   - Permissions: Actions → Read and write
2. デプロイ

   ```sh
   cd workers/live-trigger
   npx wrangler login
   npx wrangler secret put GITHUB_TOKEN   # 1 のトークンを貼る
   npx wrangler deploy
   ```

3. 動作確認

   ```sh
   npx wrangler dev --test-scheduled
   curl "http://localhost:8787/__scheduled?cron=*/15+4-13+*+*+*"
   ```

   Actions の live に `workflow_dispatch` の実行が増えていれば成功。

Workers 無料プランの範囲（Cron Trigger 対応、1回あたり CPU 10ms 以内）で動く。

## 順序

Worker をデプロイしてから、`live.yml` の `schedule` を削除した変更をマージする。
逆順にすると、その間 live の更新が止まる。
