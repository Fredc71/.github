import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bump_prs', ROOT / 'scripts/open-bump-prs.py')
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)

CALLER = '''name: format-check
on: [pull_request, issues]
# Keep this comment and the unrelated job.
jobs:
  check:
    uses: Malakof/.github/.github/workflows/format-check.yml@v1.2.7
    permissions:
      contents: read
      pull-requests: write
      issues: write
      models: read
    with:
      blocking: false
      model: openai/gpt-4o
  other:
    runs-on: ubuntu-latest
    permissions:
      models: read
    steps:
      - run: echo unchanged
'''


class FormatCheckRolloutTests(unittest.TestCase):
    def update(self, content):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / '.github/workflows/format-check.yml'
            path.parent.mkdir(parents=True)
            path.write_text(content)
            changed = bump.bump_workflow_refs(root, 'v2.0.0')
            updated = path.read_text()
            self.assertEqual(bump.bump_workflow_refs(root, 'v2.0.0'), [])
        return updated, changed

    def test_existing_call_migrates_ref_permissions_model_and_preserves_other_job(self):
        updated, changed = self.update(CALLER)
        self.assertEqual(changed, ['.github/workflows/format-check.yml'])
        job = yaml.safe_load(updated)['jobs']['check']
        self.assertTrue(job['uses'].endswith('@v2.0.0'))
        self.assertEqual(job['permissions']['copilot-requests'], 'write')
        self.assertNotIn('models', job['permissions'])
        self.assertEqual(job['with']['model'], 'auto')
        self.assertIs(job['with']['blocking'], False)
        self.assertEqual(updated.split('  other:')[1], CALLER.split('  other:')[1])
        self.assertIn('# Keep this comment', updated)
        self.assertIn('on: [pull_request, issues]', updated)

    def test_inherited_permissions_are_preserved_when_job_has_none(self):
        content = CALLER.replace('    permissions:\n      contents: read\n      pull-requests: write\n      issues: write\n      models: read\n', '')
        content = content.replace('jobs:\n', 'permissions:\n  contents: read\n  packages: read\njobs:\n')
        updated, _ = self.update(content)
        permissions = yaml.safe_load(updated)['jobs']['check']['permissions']
        self.assertEqual(permissions['packages'], 'read')
        self.assertEqual(permissions['copilot-requests'], 'write')
        self.assertEqual(permissions['pull-requests'], 'write')

    def test_explicit_copilot_model_is_preserved(self):
        updated, _ = self.update(CALLER.replace('openai/gpt-4o', 'claude-haiku-4.5'))
        self.assertEqual(yaml.safe_load(updated)['jobs']['check']['with']['model'], 'claude-haiku-4.5')

    def test_inline_permission_map_and_missing_model_are_supported(self):
        content = CALLER.replace('    permissions:\n      contents: read\n      pull-requests: write\n      issues: write\n      models: read\n', '    permissions: {contents: read, issues: write, pull-requests: write, models: read}\n')
        content = content.replace('      model: openai/gpt-4o\n', '')
        updated, _ = self.update(content)
        self.assertEqual(yaml.safe_load(updated)['jobs']['check']['permissions']['copilot-requests'], 'write')

    def test_local_adapter_is_not_replaced(self):
        content = 'name: local\non: [pull_request]\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python3 .github/scripts/format_check_copilot.py\n'
        self.assertEqual(self.update(content), (content, []))

    def test_inline_job_fails_before_writing_the_workflow(self):
        content = 'jobs: {check: {uses: Malakof/.github/.github/workflows/format-check.yml@v1.2.7}}\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.github/workflows/format-check.yml'
            path.parent.mkdir(parents=True)
            path.write_text(content)
            with self.assertRaisesRegex(ValueError, 'manual migration'):
                bump.bump_workflow_refs(Path(directory), 'v2.0.0')
            self.assertEqual(path.read_text(), content)

    def test_permission_alias_does_not_mutate_its_anchor(self):
        anchor = 'permissions: &shared\n  contents: read\n  issues: write\n  pull-requests: write\n  models: read\n'
        content = CALLER.replace('jobs:\n', anchor + 'jobs:\n')
        content = content.replace('    permissions:\n      contents: read\n      pull-requests: write\n      issues: write\n      models: read\n', '    permissions: *shared\n')
        updated, _ = self.update(content)
        self.assertIn(anchor, updated)
        self.assertEqual(yaml.safe_load(updated)['jobs']['check']['permissions']['copilot-requests'], 'write')

    def test_local_adapter_blocks_pin_bump_before_any_git_mutation(self):
        def clone_only(command, **kwargs):
            self.assertEqual(command[:3], ['gh', 'repo', 'clone'])
            repo = Path(command[4])
            (repo / '.github/scripts').mkdir(parents=True)
            (repo / '.github/scripts/format_check_copilot.py').write_text('# local adapter')
            (repo / '.github/workflows').mkdir()
            (repo / '.github/workflows/format-check.yml').write_text('run: python3 .github/scripts/format_check_copilot.py')
            (repo / '.crystal-governance.yaml').write_text('governance_version: v1.2.7\n')
        with patch.object(bump.subprocess, 'run', side_effect=clone_only) as run:
            result = bump.open_bump_pr('owner/specs', 'v2.0.0', False)
        self.assertEqual(result['action'], 'manual-migration-required')
        self.assertEqual(run.call_count, 1)

    def test_write_all_permissions_remain_unchanged(self):
        content = CALLER.replace('    permissions:\n      contents: read\n      pull-requests: write\n      issues: write\n      models: read\n', '    permissions: write-all\n')
        updated, _ = self.update(content)
        self.assertEqual(yaml.safe_load(updated)['jobs']['check']['permissions'], 'write-all')


if __name__ == '__main__':
    unittest.main()
