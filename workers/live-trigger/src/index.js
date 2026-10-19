// Actions の schedule は間引かれ・遅れるため、Cron Trigger から live.yml を workflow_dispatch で起動する
export default {
  async scheduled(controller, env, ctx) {
    const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${env.WORKFLOW}/dispatches`;
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        'User-Agent': 'bleague-rotation-live-trigger',
        'X-GitHub-Api-Version': '2022-11-28',
      },
      body: JSON.stringify({ ref: env.REF }),
    });
    if (!res.ok) {
      // 失敗はダッシュボードの Cron Events に残す
      throw new Error(`dispatch failed: ${res.status} ${await res.text()}`);
    }
  },
};
