import json
import subprocess
from pathlib import Path

LABELS = {
    'data': ('データ不整合', 'd93f0b', '交代記録の不整合で公開を保留している試合'),
    'structure': ('出典の構造変化', 'b60205', '出典のページを想定どおりに読み取れない'),
}


class GitHub:
    def __init__(self, repo: str, dry_run: bool):
        self.repo = repo
        self.dry_run = dry_run

    def run(self, *args: str, read_only: bool = False) -> str:
        cmd = ['gh', *args, '--repo', self.repo]
        if self.dry_run and not read_only:
            print('[dry-run]', ' '.join(cmd[:4]), '...')
            return ''
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout

    def open_issues(self) -> list[dict]:
        issues = []
        for name, _, _ in LABELS.values():
            out = self.run('issue', 'list', '--state', 'open', '--label', name, '--limit', '200',
                           '--json', 'number,title', read_only=True)
            issues += json.loads(out or '[]')
        return issues


def _find(issues: list[dict], key: str) -> dict | None:
    return next((i for i in issues if f'（{key}）' in i['title']), None)


def notify(report_path: Path, repo: str, dry_run: bool = False) -> None:
    report = json.loads(report_path.read_text(encoding='utf-8'))
    gh = GitHub(repo, dry_run)
    try:
        issues = gh.open_issues()
    except subprocess.CalledProcessError:
        if not dry_run:
            raise
        issues = []
    for p in report['problems']:
        found = _find(issues, p['key'])
        if found:
            print(f"既存のissue #{found['number']} があるので作成しない: {p['title']}")
            continue
        name, color, description = LABELS[p['kind']]
        gh.run('label', 'create', name, '--color', color, '--description', description, '--force')
        gh.run('issue', 'create', '--title', p['title'], '--body', p['body'], '--label', name)
        print(f"issueを作成: {p['title']}")
    for r in report['resolved']:
        found = _find(issues, r['key'])
        if not found:
            continue
        num = str(found['number'])
        gh.run('issue', 'comment', num, '--body', '再取得したデータで検証を通過したため、試合ページを公開しました。')
        gh.run('issue', 'close', num)
        print(f"issue #{num} を閉じた: {found['title']}")
