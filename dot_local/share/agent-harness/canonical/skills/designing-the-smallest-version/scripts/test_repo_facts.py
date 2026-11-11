"""Contract tests for repo_facts.py, run through its real CLI.

Builds a throwaway git repo, runs the script as a subprocess, and asserts on
the JSON. Run: python3 -B test_repo_facts.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'repo_facts.py')
ENV = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
           GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid',
           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], check=True, capture_output=True,
                          text=True, env=ENV).stdout.strip()


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


def commit(repo, msg):
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', msg)
    return git(repo, 'rev-parse', 'HEAD')


def run_script(*args):
    return subprocess.run([sys.executable, '-B', SCRIPT, *args], capture_output=True, text=True)


def run_json(*args):
    res = run_script(*args)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def build_refs_repo(repo):
    git(repo, 'init', '-q', '-b', 'main')
    write(repo, 'argocd/app.yaml', 'spec:\n  source:\n    path: k8s/app\n')
    write(repo, 'k8s/app/kustomization.yaml', 'resources:\n  - ../base\n  - ./storage.yaml\n  - deploy.yaml\n')
    write(repo, 'k8s/app/storage.yaml', 'kind: PersistentVolumeClaim\n# self: k8s/app/storage.yaml\n# dir: k8s/app/\n')
    write(repo, 'k8s/base/deploy.yaml', 'kind: Deployment\n# see ../app/storage.yaml\n')
    write(repo, 'scripts/check_manifests.py', "import os\nPATH = 'k8s/app/kustomization.yaml'\n# see scripts/check_manifests.py\n")
    write(repo, 'scripts/gate.sh', '#!/bin/sh\npython3 scripts/check_manifests.py\n')
    write(repo, 'scripts/test_check.py', 'import os\n')
    write(repo, 'scripts/manifest_test.py', 'import os\n')
    write(repo, 'Makefile', 'check:\n\tpython3 scripts/check_manifests.py\n')
    write(repo, 'package.json', json.dumps({'scripts': {'test': 'node test.js', 'build': 'tsc',
                                                        'lint': 'eslint .', 'gate': 'sh scripts/gate.sh'}}) + '\n')
    write(repo, 'kgate.toml', '[gate]\nscript = "scripts/gate.sh"\n')
    write(repo, 'docs/readme.md', 'see k8s/app/storage.yaml\n')
    write(repo, 'eval/run.sh', 'cat k8s/base/deploy.yaml\n')
    write(repo, '.github/workflows/ci.yml', 'jobs:\n  check:\n    run: make check\n')
    write(repo, 'k8s/app/charts/check.sh', 'echo hi\n')
    write(repo, 'openspec/changes/archive/verify.md', '# verify\n')
    return commit(repo, 'refs fixture')


def build_repo(repo):
    git(repo, 'init', '-q', '-b', 'main')
    # Commit 1: 15 tracked files (not more than 15, so it is used by co-change).
    write(repo, 'src/ledger/a.ts', "import { b } from './b';\nimport { c } from '../core/c';\n\nexport const a = () => b() + c();\n")
    write(repo, 'src/ledger/b.ts', "import { a } from './a';\n\nexport const b = () => 1;\n")
    write(repo, 'src/ledger/a.test.ts', "import { a } from './a';\n\ntest('a', () => a());\n")
    write(repo, 'src/ledger/fixtures/big.ts', "import { a } from '../a';\nexport const big = a;\n")
    write(repo, 'src/core/c.ts', "import { b } from '../ledger/b';\n\nexport const c = () => 2;\n")
    write(repo, 'src/ui/view.tsx', "import { a } from '../ledger/a.js';\nimport { r } from 'react';\n"
                                   "// import { z } from 'commented-pkg';\n\n"
                                   "export const lazy = () => import('../core/c');\n"
                                   "export const msg = \"import { q } from 'not-a-real-pkg'\";\n")
    write(repo, 'tests/smoke.ts', "import { a } from '../src/ledger/a';\nimport { expect } from 'vitest';\n\n"
                                  "// covers src/ledger/b\nexport const smoke = a;\n")
    write(repo, 'tools/main.py', 'import json\nfrom tools.lib.helper import run\nfrom .lib import helper\n\nprint(json.dumps(run(helper)))\n')
    write(repo, 'tools/lib/__init__.py', '# pkg\n')
    write(repo, 'tools/lib/helper.py', 'def run(x):\n    return x\n')
    write(repo, 'package-lock.json', '{}\n')
    write(repo, '.dependency-cruiser.js', 'module.exports = {};\n')
    write(repo, 'README.md', '# repo\n')
    write(repo, 'docs/adr/0001-x.md', '# ADR\n')
    write(repo, 'PRD.md', '# PRD\n')
    c1 = commit(repo, 'initial layout')
    # Commit 2: 22 files, above the default cap of 15, so skipped by co-change.
    for i in range(1, 17):
        write(repo, f'src/bulk/f{i:02d}.ts', f'export const f{i:02d} = 1;\n')
    write(repo, 'src/boundaries.test.ts', "// Boundary checks: core must not import ledger.\n"
                                          "// Enforced by dependency-cruiser.\n\ntest('boundaries', () => {});\n")
    write(repo, 'src/ledger/CONTRACT.md', '# Contract\n\nRules.\n')
    write(repo, 'eval/architecture-boundary.ts', 'export const cases = [];\n')
    write(repo, 'eval/CONTRACT.md', '# Eval contract\n')
    write(repo, 'tach.toml', '[project]\nname = "x"\n')
    write(repo, '.eslintrc.json', '{}\n')
    commit(repo, 'bulk add')
    # Commit 3: a and b change together.
    write(repo, 'src/ledger/a.ts', "import { b } from './b';\nimport { c } from '../core/c';\n\nexport const a = () => b() + c();\nexport const z = 0;\n")
    write(repo, 'src/ledger/b.ts', "import { a } from './a';\n\nexport const b = () => 1;\nexport const y = 0;\n")
    commit(repo, 'update ledger')
    # Commit 4: plan-word subject, core only.
    write(repo, 'src/core/c.ts', "import { b } from '../ledger/b';\n\nexport const c = () => 2;\nexport const k = 3;\n")
    commit(repo, 'S2: split core helper')
    # Commits 5 and 6: a file that is deleted by HEAD must not appear in co-change.
    write(repo, 'src/gone.ts', 'export const g = 1;\n')
    commit(repo, 'add gone')
    write(repo, 'src/ledger/a.ts', "import { b } from './b';\nimport { c } from '../core/c';\n\nexport const a = () => b() + c();\nexport const z = 0;\nexport const w = 1;\n")
    git(repo, 'rm', '-q', 'src/gone.ts')
    commit(repo, 'remove gone')
    # A feature branch ahead of main (touches no scope), checked out in a second worktree.
    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + '-wt')
    git(repo, 'worktree', 'add', '-q', '-b', 'feature/lane-x', wt, c1)
    write(wt, 'src/ext.ts', 'export const e = 1;\n')
    commit(wt, 'lane one: add ext')
    # A branch that touches src/ledger/b.ts, plus a remote ref at the same commit.
    wt2 = os.path.join(os.path.dirname(repo), os.path.basename(repo) + '-wt2')
    git(repo, 'worktree', 'add', '-q', '-b', 'bend-ledger', wt2, c1)
    write(wt2, 'src/ledger/b.ts', "import { a } from './a';\n\nexport const b = () => 1;\nexport const q = 2;\n")
    bend = commit(wt2, 'bend ledger b')
    git(repo, 'update-ref', 'refs/remotes/origin/lane/a10', bend)
    # A remote-tracking twin of bend-ledger at the same commit: one entry in branches_touching_scope.
    git(repo, 'update-ref', 'refs/remotes/origin/bend-ledger', bend)
    # Untracked scratch file: must be ignored, because the rev is analysed, not the working tree.
    write(repo, 'scratch/untracked.ts', "import { a } from '../src/ledger/a';\n")
    return c1, wt


class PathRefsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='repo_refs_test-')
        cls.repo = os.path.join(cls.tmp, 'refs-repo')
        os.mkdir(cls.repo)
        build_refs_repo(cls.repo)
        cls.facts = run_json(cls.repo)
        cls.scoped = run_json(cls.repo, '--scope', 'scripts/**')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_proof_commands_ranked_with_first_line_and_skips(self):
        proof = self.facts['proof_commands']
        self.assertEqual([(p['rank'], p['file']) for p in proof], [
            (1, 'Makefile'), (1, 'kgate.toml'), (1, 'package.json'), (1, 'package.json'),
            (1, 'package.json'), (1, 'scripts/check_manifests.py'), (1, 'scripts/gate.sh'),
            (1, 'scripts/test_check.py'), (2, '.github/workflows/ci.yml'),
        ])
        by_file = {p['file']: p for p in proof if 'script' not in p}
        self.assertEqual(by_file['Makefile']['first_line'], 'check')
        self.assertEqual(by_file['.github/workflows/ci.yml']['first_line'], 'check')
        self.assertEqual(by_file['scripts/check_manifests.py']['first_line'], 'see scripts/check_manifests.py')
        self.assertEqual(by_file['scripts/gate.sh']['first_line'], '')
        self.assertIn({'file': 'scripts/gate.sh', 'rank': 1, 'first_line': ''}, proof)
        self.assertIn({'file': 'kgate.toml', 'rank': 1, 'first_line': ''}, proof)
        scripts = [p for p in proof if 'script' in p]
        self.assertEqual(scripts, [
            {'file': 'package.json', 'rank': 1, 'script': 'gate', 'command': 'sh scripts/gate.sh',
             'first_line': 'sh scripts/gate.sh'},
            {'file': 'package.json', 'rank': 1, 'script': 'lint', 'command': 'eslint .',
             'first_line': 'eslint .'},
            {'file': 'package.json', 'rank': 1, 'script': 'test', 'command': 'node test.js',
             'first_line': 'node test.js'},
        ])
        # charts/ and openspec/changes/archive/ matches are skipped and counted.
        self.assertEqual(self.facts['proof_commands_skipped'], 2)
        self.assertFalse(any('charts' in p['file'] or 'archive' in p['file'] for p in proof))

    def test_gates_empty_has_note(self):
        self.assertEqual(self.facts['gates'], [])
        self.assertEqual(self.facts['gates_note'], 'no architecture gate found; see proof_commands')

    def test_globs_matched_counts_tracked_files(self):
        self.assertEqual(self.scoped['scope']['globs_matched'], {'scripts/**': 4})
        both = run_json(self.repo, '--scope', 'scripts/**', 'nothing/**')
        self.assertEqual(both['scope']['globs_matched'], {'scripts/**': 4, 'nothing/**': 0})

    def test_test_lines_count_test_prefixed_python(self):
        self.assertEqual(self.facts['sizes']['scripts']['test_lines'], 2)

    def test_path_refs_edges_exact(self):
        refs = self.facts['path_refs']
        got = {(e['from'], e['to']): e['count'] for e in refs['edges']}
        self.assertEqual(got, {
            ('argocd/app.yaml', 'k8s/app/'): 1,
            ('k8s/app/kustomization.yaml', 'k8s/base/'): 1,
            ('k8s/app/kustomization.yaml', 'k8s/app/storage.yaml'): 1,
            ('k8s/base/deploy.yaml', 'k8s/app/storage.yaml'): 1,
            ('scripts/check_manifests.py', 'k8s/app/kustomization.yaml'): 1,
            ('scripts/gate.sh', 'scripts/check_manifests.py'): 1,
            ('Makefile', 'scripts/check_manifests.py'): 1,
            ('package.json', 'scripts/gate.sh'): 1,
            ('kgate.toml', 'scripts/gate.sh'): 1,
        })
        self.assertEqual(refs['edge_count'], 9)
        self.assertEqual(refs['edge_cap'], 200)

    def test_path_refs_dir_pairs_and_cycles(self):
        refs = self.facts['path_refs']
        pairs = {(r['from'], r['to']): r for r in refs['dir_pairs']}
        self.assertEqual({k: r['count'] for k, r in pairs.items()}, {
            ('(root)', 'scripts'): 3,
            ('k8s/app', 'k8s/base'): 1,
            ('k8s/base', 'k8s/app'): 1,
            ('argocd', 'k8s/app'): 1,
            ('scripts', 'k8s/app'): 1,
        })
        self.assertEqual(refs['dir_pair_count'], 5)
        self.assertLessEqual(len(pairs[('(root)', 'scripts')]['examples']), 3)
        self.assertEqual([(c['size'], c['members']) for c in refs['cycles']],
                         [(2, ['k8s/app', 'k8s/base'])])

    def test_path_refs_never_self_or_own_dir(self):
        sources = {e['from'] for e in self.facts['path_refs']['edges']}
        self.assertNotIn('k8s/app/storage.yaml', sources)
        self.assertFalse(any(e['from'] == e['to'] for e in self.facts['path_refs']['edges']))
        # Markdown and excluded trees are not scanned.
        self.assertFalse(any(s.startswith(('docs/', 'eval/')) for s in sources))

    def test_path_refs_scope_keeps_touching_edges(self):
        refs = self.scoped['path_refs']
        self.assertEqual(refs['edge_count'], 9)
        self.assertEqual(refs['scope_edge_count'], 5)
        self.assertEqual(len(refs['edges']), 5)
        for e in refs['edges']:
            self.assertTrue(e['from'].startswith('scripts/') or e['to'].startswith('scripts/'), e)
        self.assertEqual(refs['other_edge_count'], 4)
        self.assertEqual(len(refs['other_edges']), 4)
        for e in refs['other_edges']:
            self.assertFalse(e['from'].startswith('scripts/') or e['to'].startswith('scripts/'), e)

    def test_rev_arg_and_resolved_rev(self):
        self.assertEqual(self.facts['rev_arg'], 'HEAD')
        self.assertEqual(self.facts['rev'], git(self.repo, 'rev-parse', 'HEAD'))


class TestsCapTest(unittest.TestCase):
    """More than 30 test files reference one scope file: count plus the 30 closest."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='repo_cap_test-')
        cls.repo = os.path.join(cls.tmp, 'cap-repo')
        os.mkdir(cls.repo)
        git(cls.repo, 'init', '-q', '-b', 'main')
        write(cls.repo, 'src/a.ts', 'export const a = 1;\n')
        write(cls.repo, 'src/a.test.ts', "import { a } from './a';\n")
        for i in range(1, 31):
            write(cls.repo, f'tests/t{i:02d}.test.ts', "import { a } from '../src/a';\n")
        commit(cls.repo, 'cap fixture')
        cls.scoped = run_json(cls.repo, '--scope', 'src/a.ts')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_count_and_closest_first(self):
        s = self.scoped['scope']
        self.assertEqual(s['tests_count'], 31)
        self.assertEqual(len(s['tests']), 30)
        self.assertEqual(s['tests'][0]['file'], 'src/a.test.ts')


class RepoFactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='repo_facts_test-')
        cls.repo = os.path.join(cls.tmp, 'src-repo')
        os.mkdir(cls.repo)
        cls.c1, cls.wt = build_repo(cls.repo)
        cls.parts_file = os.path.join(cls.tmp, 'parts.tsv')
        with open(cls.parts_file, 'w', encoding='utf-8') as fh:
            fh.write('# comment line\n'
                     'src/ledger/*.test.ts\tledger-tests\n'
                     'src/ledger/**\tledger\n'
                     'src/core/**\tcore\n'
                     'src/ui/**\tui\n'
                     'tools/**\ttools\n')
        cls.star_parts = os.path.join(cls.tmp, 'star.tsv')
        with open(cls.star_parts, 'w', encoding='utf-8') as fh:
            fh.write('src/*.ts\ttop\n')
        cls.before = (git(cls.repo, 'status', '--porcelain'), git(cls.repo, 'rev-parse', 'HEAD'))
        cls.head = git(cls.repo, 'rev-parse', 'HEAD')
        cls.facts = run_json(cls.repo)
        cls.parts = run_json(cls.repo, '--parts', cls.parts_file)
        cls.star = run_json(cls.repo, '--parts', cls.star_parts)
        cls.scope_ledger = run_json(cls.repo, '--scope', 'src/ledger/**')
        cls.scope_core = run_json(cls.repo, '--scope', 'src/core/c.ts')
        cls.scope_star = run_json(cls.repo, '--scope', 'src/ledger/*.ts')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_head_and_rev(self):
        self.assertEqual(self.facts['head_start'], self.head)
        self.assertEqual(self.facts['head_end'], self.head)
        self.assertEqual(self.facts['rev_arg'], 'HEAD')
        self.assertEqual(self.facts['rev'], self.head)
        self.assertIn('generated_at', self.facts)

    def test_help_documents_glob_rules(self):
        res = subprocess.run([sys.executable, '-B', SCRIPT, '--help'], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn('**', res.stdout)
        self.assertIn('--scope', res.stdout)
        self.assertIn('before --scope', res.stdout)

    def test_missing_repo_after_scope_exits_2_with_hint(self):
        res = run_script('--scope', 'scripts/**', self.repo)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(len(res.stderr.strip().splitlines()), 1)
        self.assertIn('before --scope', res.stderr)

    def test_summary_one_line_per_key(self):
        res = run_script(self.repo, '--summary')
        self.assertEqual(res.returncode, 0, res.stderr)
        lines = res.stdout.splitlines()
        self.assertEqual([line.split()[0] for line in lines], list(self.facts))
        self.assertTrue(all(len(line) < 140 for line in lines))
        self.assertIn('object', [line.split()[1] for line in lines])

    def test_summary_still_writes_json_to_out(self):
        out = os.path.join(self.tmp, 'summary.json')
        res = run_script(self.repo, '--summary', '--out', out)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(res.stdout.startswith('rev_arg'))
        with open(out, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['rev'], self.facts['rev'])

    def test_notes_explain_line_counts(self):
        self.assertIn('wc -l', self.facts['notes']['lines'])
        self.assertIn('comment-only', self.facts['notes']['code_lines'])

    def test_languages_and_parsed(self):
        self.assertEqual(self.facts['languages']['.py'], 3)
        self.assertEqual(self.facts['languages']['.md'], 4)
        self.assertEqual(self.facts['languages']['.tsx'], 1)
        self.assertEqual(set(self.facts['parsed']), {'.js', '.py', '.ts', '.tsx'})
        self.assertEqual(self.facts['parsed']['.js'], 1)
        self.assertEqual(self.facts['unparsed'], {'.json': 1, '.md': 4, '.toml': 1})

    def test_excluded_names_fixtures_eval_and_lockfile(self):
        self.assertEqual(self.facts['excluded'], {
            'eval': {'reason': 'eval directory', 'files': 2},
            'package-lock.json': {'reason': 'lockfile', 'files': 1},
            'src/ledger/fixtures': {'reason': 'fixtures directory', 'files': 1},
        })
        self.assertNotIn('src/ledger/fixtures/big.ts', [e[0] for e in self.facts['edges']])

    def test_sizes_raw_and_code_lines_by_dir(self):
        s = self.facts['sizes']
        # a.ts, b.ts and CONTRACT.md hold 5 + 3 + 2 code lines; a.test.ts holds 2 test lines.
        self.assertEqual(s['src/ledger'], {'files': 4, 'code_lines': 10, 'test_lines': 2})
        self.assertEqual(s['src/core'], {'files': 1, 'code_lines': 3, 'test_lines': 0})
        # view.tsx: two imports, one export and one export; the comment line is not code.
        self.assertEqual(s['src/ui'], {'files': 1, 'code_lines': 4, 'test_lines': 0})
        # smoke.ts: two imports and one export; the comment line is not code.
        self.assertEqual(s['tests'], {'files': 1, 'code_lines': 0, 'test_lines': 3})
        self.assertEqual(s['tools'], {'files': 1, 'code_lines': 4, 'test_lines': 0})
        # The '# pkg' comment in __init__.py is not code.
        self.assertEqual(s['tools/lib'], {'files': 2, 'code_lines': 2, 'test_lines': 0})
        self.assertEqual(s['src/bulk']['files'], 16)

    def test_top_files_carry_raw_and_code_lines(self):
        top = self.facts['top_files_by_size'][0]
        self.assertEqual(top, {'file': 'src/ledger/a.ts', 'lines': 6, 'code_lines': 5})

    def test_edges_exact(self):
        expected = [
            ['src/core/c.ts', 'src/ledger/b.ts'],
            ['src/ledger/a.test.ts', 'src/ledger/a.ts'],
            ['src/ledger/a.ts', 'src/core/c.ts'],
            ['src/ledger/a.ts', 'src/ledger/b.ts'],
            ['src/ledger/b.ts', 'src/ledger/a.ts'],
            ['src/ui/view.tsx', 'src/core/c.ts'],
            ['src/ui/view.tsx', 'src/ledger/a.ts'],
            ['tests/smoke.ts', 'src/ledger/a.ts'],
            ['tools/main.py', 'tools/lib/__init__.py'],
            ['tools/main.py', 'tools/lib/helper.py'],
        ]
        self.assertEqual(sorted(self.facts['edges']), sorted(expected))

    def test_external_packages_from_real_imports_only(self):
        # react is a real import in a non-test file. The import-looking text inside a string
        # and a comment in view.tsx is ignored. The vitest import in smoke.ts is a test file,
        # so it is only counted in external_test_imports.
        self.assertEqual(self.facts['external_packages'], {'src/ui': {'react': 1}, 'tools': {'json': 1}})
        self.assertEqual(self.facts['external_test_imports'], 1)

    def test_dir_edges_counts_and_examples(self):
        rows = {(r['from'], r['to']): r for r in self.facts['dir_edges']}
        self.assertEqual(rows[('tools', 'tools/lib')]['count'], 2)
        self.assertEqual(rows[('src/ledger', 'src/core')]['count'], 1)
        self.assertEqual(rows[('src/core', 'src/ledger')]['count'], 1)
        self.assertEqual(rows[('src/ui', 'src/ledger')]['examples'], [['src/ui/view.tsx', 'src/ledger/a.ts']])
        self.assertLessEqual(len(rows[('tools', 'tools/lib')]['examples']), 3)

    def test_cycles_found_at_dir_and_file_level(self):
        dir_cycles = self.facts['cycles']['dir']
        self.assertEqual([(c['size'], c['members']) for c in dir_cycles],
                         [(2, ['src/core', 'src/ledger'])])
        file_cycles = self.facts['cycles']['file']
        self.assertEqual(len(file_cycles), 1)
        self.assertEqual(file_cycles[0]['size'], 3)
        self.assertEqual(file_cycles[0]['members'],
                         ['src/core/c.ts', 'src/ledger/a.ts', 'src/ledger/b.ts'])
        self.assertFalse(file_cycles[0]['truncated'])

    def test_fan_in(self):
        top = self.facts['fan_in'][0]
        self.assertEqual(top, {'file': 'src/ledger/a.ts', 'importers': 4})
        self.assertIn({'file': 'src/ledger/b.ts', 'importers': 2}, self.facts['fan_in'])

    def test_cochange_skip_and_present_only(self):
        co = self.facts['cochange']
        self.assertEqual(co['window_days'], 120)
        self.assertEqual(co['commits_skipped'], 1)
        self.assertEqual(co['commits_used'], 5)
        pairs = {(p['a'], p['b']): p['commits'] for p in co['top_file_pairs']}
        self.assertEqual(pairs[('src/ledger/a.ts', 'src/ledger/b.ts')], 2)
        self.assertFalse(any('src/gone.ts' in (p['a'], p['b']) for p in co['top_file_pairs']))
        self.assertFalse(any('src/bulk' in (p['a'], p['b']) for p in co['top_file_pairs']))
        dpairs = {(p['a'], p['b']): p['commits'] for p in co['top_dir_pairs']}
        self.assertEqual(dpairs[('src/core', 'src/ledger')], 1)

    def test_in_flight_full_without_scope(self):
        inf = self.facts['in_flight']
        refs = [b['ref'] for b in inf['branches_not_merged_into_rev']]
        self.assertEqual(refs, ['refs/heads/bend-ledger', 'refs/heads/feature/lane-x',
                                'refs/remotes/origin/bend-ledger', 'refs/remotes/origin/lane/a10'])
        self.assertRegex(inf['branches_not_merged_into_rev'][0]['last_commit'], r'^\d{4}-\d{2}-\d{2}T')
        self.assertEqual(len(inf['worktrees']), 3)
        self.assertTrue(any(w['branch'] == 'feature/lane-x' for w in inf['worktrees']))
        subjects = [c['subject'] for c in inf['plan_commits_14d']]
        self.assertEqual(subjects, ['S2: split core helper'])

    def test_gates_ranked_with_headers_on_top_three(self):
        gates = self.facts['gates']
        self.assertEqual([g['file'] for g in gates],
                         ['.dependency-cruiser.js', 'src/boundaries.test.ts', '.eslintrc.json', 'tach.toml'])
        self.assertEqual(gates[0], {'file': '.dependency-cruiser.js', 'header': 'module.exports = {};'})
        self.assertEqual(gates[1]['header'],
                         '// Boundary checks: core must not import ledger.\n// Enforced by dependency-cruiser.')
        self.assertEqual(gates[2]['header'], '{}')
        self.assertNotIn('header', gates[3])

    def test_gates_present_has_no_note(self):
        self.assertNotIn('gates_note', self.facts)

    def test_gates_and_docs_skip_excluded_trees(self):
        self.assertNotIn('eval/architecture-boundary.ts', [g['file'] for g in self.facts['gates']])

    def test_docs_found_includes_contract_at_depth(self):
        docs = {d['path'] for d in self.facts['docs_found']}
        self.assertEqual(docs, {'README.md', 'docs/adr/0001-x.md', 'PRD.md', 'src/ledger/CONTRACT.md'})

    def test_skipped_count_present(self):
        self.assertEqual(self.facts['skipped'], {'count': 0, 'by_reason': {}})

    def test_working_tree_ignored(self):
        self.assertNotIn('scratch/untracked.ts', [e[0] for e in self.facts['edges']])
        self.assertNotIn('scratch', self.facts['sizes'])

    def test_parts_only_with_flag(self):
        self.assertNotIn('parts', self.facts)
        self.assertIn('parts', self.parts)

    def test_parts_sizes_matrix_and_unmapped_object(self):
        bp = self.parts['parts']['by_part']
        self.assertEqual(bp['ledger-tests'], {'files': 1, 'code_lines': 0, 'test_lines': 2})
        self.assertEqual(bp['ledger'], {'files': 3, 'code_lines': 10, 'test_lines': 0})
        self.assertEqual(bp['tools'], {'files': 3, 'code_lines': 6, 'test_lines': 0})
        matrix = {(r['from'], r['to']): r['count'] for r in self.parts['parts']['edges']}
        self.assertEqual(matrix, {
            ('ledger', 'core'): 1,
            ('core', 'ledger'): 1,
            ('ui', 'core'): 1,
            ('ui', 'ledger'): 1,
            ('ledger-tests', 'ledger'): 1,
        })
        unmapped = self.parts['parts']['unmapped']
        self.assertEqual(unmapped['count'], 24)
        self.assertEqual(len(unmapped['samples']), 20)
        self.assertIn('src/boundaries.test.ts', unmapped['samples'])
        self.assertNotIn('src/ledger/a.test.ts', unmapped['samples'])

    def test_parts_star_does_not_cross_slash(self):
        # `src/*.ts` matches only src/boundaries.test.ts, not src/ledger/a.ts or src/bulk/f01.ts.
        self.assertEqual(self.star['parts']['by_part']['top']['files'], 1)

    def test_pinned_rev_ignores_later_commits(self):
        facts = run_json(self.repo, '--rev', self.c1)
        self.assertEqual(facts['head_start'], self.c1)
        self.assertEqual(facts['head_end'], self.c1)
        self.assertNotIn('src/bulk', facts['sizes'])
        # At c1, a.ts has 3 non-blank code lines and b.ts has 2.
        self.assertEqual(facts['sizes']['src/ledger'], {'files': 3, 'code_lines': 5, 'test_lines': 2})
        self.assertNotIn('scratch', facts['sizes'])

    def test_out_flag_writes_file(self):
        out = os.path.join(self.tmp, 'facts.json')
        res = run_script(self.repo, '--out', out)
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(out, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['head_start'], self.head)

    def test_scope_cochange_only_scope_commits(self):
        co = self.scope_ledger['cochange']
        # Commits touching src/ledger: 1, 2 (skipped, too big), 3 and 6. Commits 4 and 5 are not counted.
        self.assertEqual((co['commits_used'], co['commits_skipped']), (3, 1))
        pairs = {(p['a'], p['b']): p['commits'] for p in co['top_file_pairs']}
        self.assertEqual(pairs[('src/ledger/a.ts', 'src/ledger/b.ts')], 2)
        for a, b in pairs:
            self.assertTrue(a.startswith('src/ledger/') or b.startswith('src/ledger/'), (a, b))

    def test_scope_absent_without_flag(self):
        self.assertNotIn('scope', self.facts)
        self.assertIn('edges', self.facts)

    def test_scope_files_block(self):
        s = self.scope_ledger['scope']
        self.assertEqual(s['globs'], ['src/ledger/**'])
        files = {f['file']: f for f in s['files']}
        # fixtures are excluded from the tree, so they cannot be in scope.
        self.assertEqual(sorted(files), ['src/ledger/CONTRACT.md', 'src/ledger/a.test.ts',
                                         'src/ledger/a.ts', 'src/ledger/b.ts'])
        self.assertEqual((files['src/ledger/a.ts']['lines'], files['src/ledger/a.ts']['code_lines']), (6, 5))
        self.assertEqual((files['src/ledger/b.ts']['lines'], files['src/ledger/b.ts']['code_lines']), (4, 3))
        self.assertEqual(files['src/ledger/a.ts']['imports'], ['src/core/c.ts', 'src/ledger/b.ts'])
        self.assertEqual(files['src/ledger/a.ts']['importers'],
                         ['src/ledger/a.test.ts', 'src/ledger/b.ts', 'src/ui/view.tsx', 'tests/smoke.ts'])
        self.assertEqual(files['src/ledger/b.ts']['imports'], ['src/ledger/a.ts'])
        self.assertEqual(files['src/ledger/b.ts']['importers'], ['src/core/c.ts', 'src/ledger/a.ts'])

    def test_scope_mode_omits_edges_and_gives_counts(self):
        facts = self.scope_ledger
        self.assertNotIn('edges', facts)
        self.assertNotIn('external_packages', facts)
        self.assertEqual(facts['edge_count'], 10)
        self.assertEqual(facts['external_package_count'], 2)
        self.assertEqual(facts['in_flight'], {'branches_not_merged_into_rev': 4,
                                              'worktrees': 3, 'plan_commits_14d': 1})

    def test_scope_tests_import_or_name_scope_files(self):
        self.assertEqual(self.scope_ledger['scope']['tests_count'], 2)
        self.assertEqual(self.scope_ledger['scope']['tests'], [
            {'file': 'src/ledger/a.test.ts', 'scope_files': ['src/ledger/a.ts']},
            # tests/smoke.ts imports a.ts and names b.ts in a comment.
            {'file': 'tests/smoke.ts', 'scope_files': ['src/ledger/a.ts', 'src/ledger/b.ts']},
        ])

    def test_scope_cycles_branches_and_plan_commits_for_ledger(self):
        s = self.scope_ledger['scope']
        self.assertEqual([c['size'] for c in s['cycles']], [3])
        branches = {b['ref']: b for b in s['branches_touching_scope']}
        self.assertEqual(sorted(branches), ['refs/heads/bend-ledger', 'refs/remotes/origin/lane/a10'])
        bend = branches['refs/heads/bend-ledger']
        self.assertEqual((bend['ahead'], bend['behind']), (1, 5))
        self.assertEqual(bend['files_changed'], 1)
        self.assertEqual(bend['files'], ['src/ledger/b.ts'])
        self.assertRegex(bend['last_commit'], r'^\d{4}-\d{2}-\d{2}T')
        self.assertNotIn('plan_commits_touching_scope', s)
        self.assertNotIn('recent_commits_touching_scope', s)
        self.assertEqual(s['plan_word_commits_touching_scope'], [])
        self.assertEqual(bend['remote_ref'], 'refs/remotes/origin/bend-ledger')
        self.assertEqual(bend['unmerged_patches'], 1)
        self.assertEqual(branches['refs/remotes/origin/lane/a10']['unmerged_patches'], 1)

    def test_scope_core_file_sees_plan_commit_and_no_branches(self):
        s = self.scope_core['scope']
        self.assertEqual([f['file'] for f in s['files']], ['src/core/c.ts'])
        self.assertEqual(s['files'][0]['imports'], ['src/ledger/b.ts'])
        self.assertEqual(s['files'][0]['importers'], ['src/ledger/a.ts', 'src/ui/view.tsx'])
        self.assertEqual(s['tests'], [])
        self.assertEqual(len(s['cycles']), 1)
        self.assertEqual(s['branches_touching_scope'], [])
        plan = s['plan_word_commits_touching_scope']
        self.assertEqual([p['subject'] for p in plan], ['S2: split core helper'])
        self.assertEqual(plan[0]['files'], ['src/core/c.ts'])

    def test_repeated_scope_flag_keeps_every_glob(self):
        rep = run_json(self.repo, '--scope', 'src/ledger/a.ts', '--scope', 'src/core/c.ts')
        files = sorted(f['file'] for f in rep['scope']['files'])
        self.assertEqual(files, ['src/core/c.ts', 'src/ledger/a.ts'])
        self.assertEqual(rep['scope']['globs_matched'], {'src/ledger/a.ts': 1, 'src/core/c.ts': 1})

    def test_scope_star_stays_in_one_segment(self):
        files = [f['file'] for f in self.scope_star['scope']['files']]
        self.assertEqual(files, ['src/ledger/a.test.ts', 'src/ledger/a.ts', 'src/ledger/b.ts'])

    def test_bad_args_exit_2_one_line(self):
        res = run_script(self.repo, '--since-days', '-1')
        self.assertEqual(res.returncode, 2)
        self.assertEqual(len(res.stderr.strip().splitlines()), 1)

    def test_not_a_git_repo_exit_2(self):
        plain = os.path.join(self.tmp, 'plain')
        os.mkdir(plain)
        res = run_script(plain)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(len(res.stderr.strip().splitlines()), 1)

    def test_unknown_rev_exit_2(self):
        res = run_script(self.repo, '--rev', 'no-such-rev')
        self.assertEqual(res.returncode, 2)
        self.assertEqual(len(res.stderr.strip().splitlines()), 1)

    def test_source_repo_untouched(self):
        after = (git(self.repo, 'status', '--porcelain'), git(self.repo, 'rev-parse', 'HEAD'))
        self.assertEqual(self.before, after)


if __name__ == '__main__':
    unittest.main()
