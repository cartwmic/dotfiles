#!/usr/bin/env python3
"""Real Pi /recap view and history viewer render recap narratives as markdown.

Requires a private Python with pyte/wcwidth (see current_screen.py)."""
import json
import os
from pathlib import Path
import tempfile
from public_helpers import PublicPi
from current_screen import CurrentScreen

screen = CurrentScreen()
observed = []


def check(label):
    frame = screen.capture(label)
    lines = [line.rstrip() for line in frame['lines']]
    top = next((i for i, line in enumerate(lines) if 'Esc close' in line), None)
    assert top is not None, (label, 'viewer not open', lines)
    # Only the viewer region; the compact widget above is a separate dim excerpt.
    text = '\n'.join(lines[top:])
    assert 'Orchard status' in text and '## Orchard' not in text, (label, 'heading marker shown')
    assert '**' not in text and '`abc1234`' not in text and 'abc1234' in text, (label, 'inline markers shown')
    assert any(line.startswith('- first follow-up item') for line in lines[top:]), (label, 'bullet not rendered')
    row = next(i for i, line in enumerate(lines) if i > top and 'Complete:' in line)
    x = lines[row].index('Complete:')
    assert all(frame['cells'][row][x + i]['bold'] for i in range(len('Complete:'))), (label, 'bold not applied')
    assert not frame['cells'][row][x + len('Complete: ') + 1]['bold'], (label, 'bold leaked')
    observed.append(label)


with tempfile.TemporaryDirectory(prefix='recap-viewer-markdown-') as temporary:
    root = Path(temporary)
    pi = PublicPi(root, terminal=screen, environment={'RECAP_PROOF_MARKDOWN': '1'})
    try:
        if 'Trust project folder?' in pi.visible():
            os.write(pi.master, b'\x1b[B\r'); pi.collect(3)
        pi.send('Inspect orchard')
        pi.wait(lambda: any(e.get('event') == 'settled' for e in pi.events()), 'scripted work did not settle')
        pi.send('/recap', 1)
        pi.wait(lambda: any(r['status'] == 'published' for r in pi.records()), 'recap not saved')
        pi.collect(1)
        saved = next(r for r in pi.records() if r['status'] == 'published')
        assert '**Complete:**' in saved['summary'], 'stored narrative must keep raw markdown'
        # Widget: dim markdown, markers gone, bold kept, own line breaks, max 3 rows.
        frame = screen.capture('widget')
        lines = [line.rstrip().removeprefix('▎ ') for line in frame['lines']]
        head = next(i for i, line in enumerate(lines) if line.startswith('Recap updated'))
        rule = next(i for i in range(head + 1, head + 6) if lines[i].startswith('─'))
        rows = lines[head + 1:rule]
        assert rows[0] == 'Orchard status' and rows[1].startswith('Complete:') and len(rows) == 3, ('widget', rows)
        assert rows[2].endswith('...') and not any('**' in r or '##' in r or '`' in r for r in rows), ('widget', rows)
        cells = frame['cells'][head + 2][2:]
        assert all(cells[i]['bold'] and cells[i].get('faint') for i in range(len('Complete:'))), ('widget', 'bold not dim-bold')
        assert all(c.get('faint') for y in range(head, rule) for c in frame['cells'][y][2:] if c['data'].strip()), ('widget', 'not all dim')
        assert len({c['fg'] for y in range(head, rule) for c in frame['cells'][y][2:] if c['data'].strip()}) == 1, ('widget', 'colored')
        assert len({frame['cells'][y][0]['fg'] for y in range(head, rule)}) == 1 and frame['cells'][head][0]['data'] == '▎', ('widget', 'bar')
        observed.append('widget')
        calls = len(pi.calls())
        pi.send('/recap view', 1.5)
        check('recap-view')
        os.write(pi.master, b'\x1b'); pi.collect(1)
        pi.send('/recap history', 1.5)
        pi.send('', 1.5)
        check('history-view')
        os.write(pi.master, b'\x1b'); pi.collect(1)
        assert pi.process.poll() is None, 'Pi exited'
        assert len(pi.calls()) == calls, 'viewing generated a recap'
    except Exception:
        print('\n'.join(screen.screen.display), file=__import__('sys').stderr)
        raise
    finally:
        pi.close()
print(json.dumps({'status': 'PASS', 'cases': observed}))
