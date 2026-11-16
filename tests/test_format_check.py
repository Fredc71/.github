from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import format_check as checker

OK = {'pass': True, 'severity': 'ok', 'summary': 'Conforme', 'findings': []}
FAIL = {'pass': False, 'severity': 'fail', 'summary': 'Missing priority',
        'findings': [{'rule': 'priority', 'severity': 'fail', 'message': 'Missing label'}]}


def events(content, exit_code=0):
    return '\n'.join(map(json.dumps, [
        {'type': 'assistant.message', 'data': {'content': content}},
        {'type': 'result', 'exitCode': exit_code},
    ]))


class FormatCheckTransportTests(unittest.TestCase):
    def setUp(self):
        # The old implementation must fail these tests, never call a live API.
        mock = patch('urllib.request.urlopen', side_effect=AssertionError('Retired transport called'))
        mock.start()
        self.addCleanup(mock.stop)

    def call(self, output=None, code=0, error=None, model='auto'):
        result = subprocess.CompletedProcess([], code, output, 'private-token private-prompt')
        with patch.object(checker.subprocess, 'run', return_value=result, side_effect=error) as run:
            verdict = checker.call_llm('private-token', 'rules', 'private-prompt', model)
        self.assertEqual(run.call_count, 1)
        return verdict, run.call_args

    def test_valid_verdict_and_isolated_jsonl_invocation(self):
        verdict, call = self.call(events(json.dumps(OK)))
        self.assertEqual(verdict, OK)
        command = call.args[0]
        self.assertEqual(command[command.index('--output-format') + 1], 'json')
        self.assertEqual(command[command.index('--available-tools') + 1], '--disable-builtin-mcps')
        self.assertIn('--no-custom-instructions', command)
        self.assertNotIn('private-token', ' '.join(command))
        self.assertNotIn('GH_TOKEN', call.kwargs['env'])
        self.assertEqual(call.kwargs['env']['GITHUB_TOKEN'], 'private-token')
        self.assertEqual(call.kwargs['timeout'], 180)
        self.assertEqual(call.kwargs['cwd'], str(Path(call.kwargs['env']['COPILOT_HOME']).parent))

    def test_legacy_model_ids_are_mapped_to_auto(self):
        for model in ('openai/gpt-4o', 'openai/gpt-4o-mini'):
            verdict, call = self.call(events(json.dumps(OK)), model=model)
            command = call.args[0]
            self.assertEqual(command[command.index('--model') + 1], 'auto')
            self.assertEqual(verdict, OK)

    def test_fenced_verdicts_and_escaped_line_breaks(self):
        expected = dict(OK, summary='A long summary\nwith an intentional line break')
        for opening in ('', '```json\n', '```\n'):
            text = opening + json.dumps(expected) + ('\n```' if opening else '')
            self.assertEqual(self.call(events(text))[0], expected)

    def test_invalid_streams_never_claim_validation(self):
        bad = ['', 'OK', '<html>private-prompt</html>', '[]',
               json.dumps({'type': 'result', 'exitCode': 1}),
               json.dumps({'type': 'assistant.message', 'data': {'content': json.dumps(OK)}}),
               events('private-token private-prompt')]
        for output in bad:
            with self.subTest(output=output):
                verdict, _ = self.call(output)
                self.assertEqual(verdict['status'], 'unavailable')
                self.assertIsNone(verdict['pass'])
                self.assertNotIn('private', json.dumps(verdict))

    def test_invalid_verdict_schema_is_unavailable(self):
        bad = [[], {}, dict(OK, **{'pass': 'true'}), dict(OK, severity='unknown'),
               dict(OK, severity=[]), dict(OK, summary=''), dict(OK, findings=[{}]),
               dict(OK, severity='fail'), dict(OK, findings=FAIL['findings'])]
        for value in bad:
            with self.subTest(value=value):
                verdict, _ = self.call(events(json.dumps(value)))
                self.assertEqual(verdict['status'], 'unavailable')

    def test_failed_call_or_timeout_is_redacted_and_not_retried(self):
        for error in (None, subprocess.TimeoutExpired('private-prompt', 180), OSError('private-token'),
                      UnicodeDecodeError('utf-8', b'private-token\xff', 13, 14, 'invalid byte')):
            with self.subTest(error=error):
                verdict, _ = self.call('private-prompt', code=1, error=error)
                self.assertEqual(verdict['status'], 'unavailable')
                self.assertNotIn('private', json.dumps(verdict))

    def test_unexpected_tool_execution_or_session_error_cannot_pass(self):
        for kind in ('tool.execution_start', 'session.error'):
            output = json.dumps({'type': kind}) + '\n' + events(json.dumps(OK))
            self.assertEqual(self.call(output)[0]['status'], 'unavailable')

    def test_valid_format_rejection_is_preserved(self):
        self.assertEqual(self.call(events(json.dumps(FAIL)))[0], FAIL)

    def test_main_unavailable_fails_both_policies_and_never_claims_validation(self):
        for blocking in ('false', 'true'):
            with self.subTest(blocking=blocking):
                code, comment, output = self.main_case('', blocking)
                self.assertEqual(code, 1)
                self.assertIn('UNAVAILABLE', comment)
                self.assertNotIn('Validated against', comment)
                self.assertNotIn('Format check OK', output)
                self.assertNotIn('private', comment + output)

    def test_main_preserves_valid_advisory_and_blocking_rejections(self):
        for blocking, expected in (('false', 0), ('true', 1)):
            self.assertEqual(self.main_case(events(json.dumps(FAIL)), blocking)[0], expected)

    def test_main_valid_success_names_copilot(self):
        code, comment, output = self.main_case(events(json.dumps(OK)), 'false')
        self.assertEqual(code, 0)
        self.assertIn('via GitHub Copilot CLI', comment)
        self.assertIn('Format check OK', output)

    def main_case(self, output, blocking):
        artifact = {'title': 'fix: repair format check', 'labels': [{'name': 'type:bug'}, {'name': 'priority:p2'}]}
        result = subprocess.CompletedProcess([], 0, output, '')
        stdout = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', ['format_check.py', '--repo', 'owner/repo', '--pr', '1', '--blocking', blocking, '--governance-root', str(ROOT)]))
            stack.enter_context(patch.dict(os.environ, {'GITHUB_TOKEN': 'private-token'}, clear=True))
            stack.enter_context(patch.object(checker, 'fetch_artifact', return_value=artifact))
            stack.enter_context(patch.object(checker.subprocess, 'run', return_value=result))
            comment = stack.enter_context(patch.object(checker, 'upsert_comment'))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            code = checker.main()
        return code, comment.call_args.args[3], stdout.getvalue()


class FormatCheckWorkflowTests(unittest.TestCase):
    def test_checkout_order_permissions_and_token_transport(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/format-check.yml').read_text())
        job = workflow['jobs']['check']
        steps = job['steps']
        self.assertEqual(steps[0]['uses'], 'actions/checkout@v5')
        self.assertFalse(steps[0]['with']['persist-credentials'])
        pin = next(i for i, step in enumerate(steps) if step.get('id') == 'pin')
        governance = next(i for i, step in enumerate(steps) if step.get('with', {}).get('repository') == 'Malakof/.github')
        self.assertLess(0, pin)
        self.assertLess(pin, governance)
        self.assertEqual(steps[governance]['with']['ref'], '${{ steps.pin.outputs.version }}')
        self.assertEqual(job['permissions']['copilot-requests'], 'write')
        self.assertNotIn('models', job['permissions'])
        self.assertTrue(any('@github/copilot@1.0.112' in step.get('run', '') for step in steps))
        run_steps = [step for step in steps if 'scripts/format_check.py' in step.get('run', '')]
        self.assertEqual(len(run_steps), 2)
        for step in run_steps:
            self.assertEqual(step['env']['GITHUB_TOKEN'], '${{ github.token }}')
            self.assertNotIn('${{ inputs.model }}', step['run'])


if __name__ == '__main__':
    unittest.main()
