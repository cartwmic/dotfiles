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


def build_repo(repo):
    git(repo, 'init', '-q', '-b', 'main')
    # Commit 1: 15 tracked files (not more than 15, so it is used by co-change).
    write(repo, 'src/ledger/a.ts', "import { b } from './b';\nimport { c } from '../core/c';\n\nexport const a = () => b() + c();\n")
    write(repo, 'src/ledger/b.ts', "import { a } from './a';\n\nexport const b = () => 1;\n")
    write(repo, 'src/ledger/a.test.ts', "import { a } from './a';\n\ntest('a', () => a());\n")
    write(repo, 'src/ledger/fixtures/big.ts', "import { a } from '../a';\nexport const big = a;\n")
    write(repo, 'src/core/c.ts', "import { b } from '../ledger/b';\n\nexport const c = () => 2;\n")
    write(repo, 'src/ui/view.tsx', "import { a } from '../ledger/a.js';\n\nexport const lazy = () => import('../core/c');\n")
    write(repo, 'tests/smoke.ts', "import { a } from '../src/ledger/a';\n\nexport const smoke = a;\n")
    write(repo, 'tools/main.py', 'import json\nfrom tools.lib.helper import run\nfrom .lib import helper\n\nprint(json.dumps(run(helper)))\n')
    write(repo, 'tools/lib/__init__.py', '# pkg\n')
    write(repo, 'tools/lib/helper.py', 'def run(x):\n    return x\n')
    write(repo, 'package-lock.json', '{}\n')
    write(repo, '.dependency-cruiser.js', 'module.exports = {};\n')
    write(repo, 'README.md', '# repo\n')
    write(repo, 'docs/adr/0001-x.md', '# ADR\n')
    write(repo, 'PRD.md', '# PRD\n')
    c1 = commit(repo, 'initial layout')
    # Commit 2: 16 files, above the default cap of 15, so skipped by co-change.
    for i in range(1, 17):
        write(repo, f'src/bulk/f{i:02d}.ts', f'export const f{i:02d} = 1;\n')
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
    # A feature branch ahead of main, checked out in a second worktree.
    wt = os.path.join(os.path.dirname(repo), os.path.basename(repo) + '-wt')
    git(repo, 'worktree', 'add', '-q', '-b', 'feature/lane-x', wt, c1)
    write(wt, 'src/ext.ts', 'export const e = 1;\n')
    commit(wt, 'lane one: add ext')
    # Untracked scratch file: must be ignored, because the rev is analysed, not the working tree.
    write(repo, 'scratch/untracked.ts', "import { a } from '../src/ledger/a';\n")
    return c1, wt


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
        cls.before = (git(cls.repo, 'status', '--porcelain'), git(cls.repo, 'rev-parse', 'HEAD'))
        cls.head = git(cls.repo, 'rev-parse', 'HEAD')
        res = run_script(cls.repo)
        assert res.returncode == 0, res.stderr
        cls.facts = json.loads(res.stdout)
        res = run_script(cls.repo, '--parts', cls.parts_file)
        assert res.returncode == 0, res.stderr
        cls.parts = json.loads(res.stdout)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_head_and_rev(self):
        self.assertEqual(self.facts['head_start'], self.head)
        self.assertEqual(self.facts['head_end'], self.head)
        self.assertEqual(self.facts['rev'], 'HEAD')
        self.assertIn('generated_at', self.facts)

    def test_languages_and_parsed(self):
        self.assertEqual(self.facts['languages']['.py'], 3)
        self.assertEqual(self.facts['languages']['.md'], 3)
        self.assertEqual(self.facts['languages']['.tsx'], 1)
        self.assertEqual(self.facts['parsed'], ['.js', '.py', '.ts', '.tsx'])
        self.assertEqual(self.facts['unparsed'], ['.md'])

    def test_excluded_names_fixtures_and_lockfile(self):
        self.assertEqual(self.facts['excluded'], {
            'src/ledger/fixtures': {'reason': 'fixtures directory', 'files': 1},
            'package-lock.json': {'reason': 'lockfile', 'files': 1},
        })
        self.assertNotIn('src/ledger/fixtures/big.ts', [e[0] for e in self.facts['edges']])

    def test_sizes_test_vs_code_lines(self):
        s = self.facts['sizes']
        self.assertEqual(s['src/ledger'], {'files': 3, 'code_lines': 8, 'test_lines': 2})
        self.assertEqual(s['src/core'], {'files': 1, 'code_lines': 3, 'test_lines': 0})
        self.assertEqual(s['tests'], {'files': 1, 'code_lines': 0, 'test_lines': 2})
        self.assertEqual(s['tools'], {'files': 1, 'code_lines': 4, 'test_lines': 0})
        self.assertEqual(s['tools/lib'], {'files': 2, 'code_lines': 3, 'test_lines': 0})
        self.assertEqual(s['src/bulk']['files'], 16)

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

    def test_external_packages(self):
        self.assertEqual(self.facts['external_packages']['tools'], {'json': 1})

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
        self.assertEqual(self.facts['top_files_by_size'][0]['file'], 'src/ledger/a.ts')

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

    def test_in_flight(self):
        inf = self.facts['in_flight']
        refs = [b['ref'] for b in inf['branches_not_merged_into_rev']]
        self.assertEqual(refs, ['refs/heads/feature/lane-x'])
        self.assertRegex(inf['branches_not_merged_into_rev'][0]['last_commit'], r'^\d{4}-\d{2}-\d{2}T')
        self.assertEqual(len(inf['worktrees']), 2)
        self.assertTrue(any(w['branch'] == 'feature/lane-x' for w in inf['worktrees']))
        subjects = [c['subject'] for c in inf['plan_commits_14d']]
        self.assertEqual(subjects, ['S2: split core helper'])

    def test_gates_and_docs(self):
        self.assertEqual(self.facts['gates'], ['.dependency-cruiser.js'])
        docs = {d['path'] for d in self.facts['docs_found']}
        self.assertEqual(docs, {'README.md', 'docs/adr/0001-x.md', 'PRD.md'})

    def test_skipped_count_present(self):
        self.assertEqual(self.facts['skipped'], {'count': 0, 'by_reason': {}})

    def test_working_tree_ignored(self):
        self.assertNotIn('scratch/untracked.ts', [e[0] for e in self.facts['edges']])
        self.assertNotIn('scratch', self.facts['sizes'])

    def test_parts_only_with_flag(self):
        self.assertNotIn('parts', self.facts)
        self.assertIn('parts', self.parts)

    def test_parts_sizes_matrix_and_unmapped(self):
        bp = self.parts['parts']['by_part']
        self.assertEqual(bp['ledger-tests'], {'files': 1, 'code_lines': 0, 'test_lines': 2})
        self.assertEqual(bp['ledger'], {'files': 2, 'code_lines': 8, 'test_lines': 0})
        self.assertEqual(bp['tools'], {'files': 3, 'code_lines': 7, 'test_lines': 0})
        matrix = {(r['from'], r['to']): r['count'] for r in self.parts['parts']['edges']}
        self.assertEqual(matrix, {
            ('ledger', 'core'): 1,
            ('core', 'ledger'): 1,
            ('ui', 'core'): 1,
            ('ui', 'ledger'): 1,
            ('ledger-tests', 'ledger'): 1,
        })
        unmapped = self.parts['parts']['unmapped']
        self.assertIn('tests/smoke.ts', unmapped)
        self.assertIn('src/bulk/f01.ts', unmapped)
        self.assertNotIn('src/ledger/a.test.ts', unmapped)
        self.assertEqual(len(unmapped), 21)

    def test_pinned_rev_ignores_later_commits(self):
        res = run_script(self.repo, '--rev', self.c1)
        self.assertEqual(res.returncode, 0, res.stderr)
        facts = json.loads(res.stdout)
        self.assertEqual(facts['head_start'], self.c1)
        self.assertEqual(facts['head_end'], self.c1)
        self.assertNotIn('src/bulk', facts['sizes'])
        # At c1, a.ts has 3 non-blank lines (no z/w yet) and b.ts has 2.
        self.assertEqual(facts['sizes']['src/ledger'], {'files': 3, 'code_lines': 5, 'test_lines': 2})
        self.assertNotIn('scratch', facts['sizes'])

    def test_out_flag_writes_file(self):
        out = os.path.join(self.tmp, 'facts.json')
        res = run_script(self.repo, '--out', out)
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(out, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['head_start'], self.head)

    def test_source_repo_untouched(self):
        after = (git(self.repo, 'status', '--porcelain'), git(self.repo, 'rev-parse', 'HEAD'))
        self.assertEqual(self.before, after)

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


if __name__ == '__main__':
    unittest.main()
