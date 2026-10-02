"""Real current VT screen for the focused public proof (requires private pyte).

Run the normal proof dispatcher with a Python interpreter containing pyte and
wcwidth. Missing dependencies fail closed; no global installation is performed.
Unknown terminal queries/Kitty controls are handled by pyte's debug no-op, not
by deleting application output. All decoded application text feeds the emulator.
"""
import json
import re
import subprocess
from collections import namedtuple
import pyte
from wcwidth import wcwidth, wcswidth

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def plain(text):
    return ANSI.sub('', text)


def excerpt(text, columns):
    text = ' '.join(plain(text).split())
    if wcswidth(text) <= columns:
        return text
    result = ''
    for char in text:
        if wcswidth(result) + max(0, wcwidth(char)) > columns - 3:
            break
        result += char
    return result + '...'


# pyte models colors/bold but omits ANSI SGR 2 (faint). Extend its cell
# attributes only; cursor movement, erasure, CJK and parsing remain real pyte.
FaintChar = namedtuple('FaintChar', (*pyte.screens.Char._fields, 'faint'), defaults=(*pyte.screens.Char.__new__.__defaults__, False))


class FaintScreen(pyte.Screen):
    @property
    def default_char(self):
        return FaintChar(*super().default_char, False)

    def select_graphic_rendition(self, *attrs):
        faint = getattr(self.cursor.attrs, 'faint', False)
        if not isinstance(self.cursor.attrs, FaintChar):
            self.cursor.attrs = FaintChar(*self.cursor.attrs, faint)
        codes = iter(attrs or (0,))
        for code in codes:
            if code in (0, 22): faint = False
            elif code == 2: faint = True
            elif code in (38, 48):
                mode = next(codes, None)
                for _ in range(3 if mode == 2 else 1): next(codes, None)
        super().select_graphic_rendition(*attrs)
        self.cursor.attrs = self.cursor.attrs._replace(faint=faint)


class CurrentScreen:
    def __init__(self, columns=160, rows=36):
        self.screen = FaintScreen(columns, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.frames = []

    def feed(self, data):
        self.stream.feed(data)

    def resize(self, columns, rows):
        self.screen.resize(lines=rows, columns=columns)

    def capture(self, label):
        frame = {'label': label, 'columns': self.screen.columns, 'rows': self.screen.lines,
                 'lines': self.screen.display,
                 'cells': [[dict(self.screen.buffer[y][x]._asdict()) for x in range(self.screen.columns)]
                           for y in range(self.screen.lines)]}
        self.frames.append(frame)
        return frame

    def absent(self, label):
        frame = self.capture(label)
        assert not any('Recap updated' in line or '観察 ' in line for line in frame['lines']), label

    def widget(self, record, zone, env, label):
        frame = self.capture(label)
        lines = [line.rstrip() for line in frame['lines']]
        heading_rows = [i for i, line in enumerate(lines) if line.startswith('Recap updated ')]
        assert len(heading_rows) == 1, (label, heading_rows, lines)
        row = heading_rows[0]
        timestamp = record.get('published_at', record['created_at'])
        script = '''const [timestamp, zone] = JSON.parse(process.argv[1]);
const f = new Intl.DateTimeFormat('sv-SE', {...(zone === 'local' ? {} : {timeZone: zone}), year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23', timeZoneName:'shortOffset'});
console.log(`${f.format(new Date(timestamp))} [${zone === 'local' ? f.resolvedOptions().timeZone : zone}]`);'''
        display_time = subprocess.check_output(['node', '-e', script, json.dumps([timestamp, zone])], env=env, text=True).strip()
        assert lines[row] == excerpt('Recap updated ' + display_time, frame['columns']), (label, lines[row], display_time)
        assert lines[row + 1] == excerpt(record['summary'], frame['columns']), (label, lines[row + 1], excerpt(record['summary'], frame['columns']))
        # Both widget rows must use the exact muted heading color. Inner model
        # ANSI must not reset it or recolor any visible excerpt character.
        colors = {c['fg'] for c in frame['cells'][row] if c['data'].strip()}
        assert len(colors) == 1, (label, colors)
        assert all(c.get('faint') for c in frame['cells'][row] if c['data'].strip()), (label, 'heading not dim')
        for y in (row, row + 1):
            assert all(c['fg'] in colors and c.get('faint') and not c['bold'] for c in frame['cells'][y] if c['data'].strip()), (label, y, {c['fg'] for c in frame['cells'][y] if c['data'].strip()})
        assert row + 2 < len(lines) and lines[row + 2].startswith('─'), (label, 'widget not immediately above editor', lines[row + 2:])
        # No third excerpt row/partial narrative elsewhere in the current frame.
        assert not any('詳しい' in line or '観察 ' in line for i, line in enumerate(lines) if i != row + 1), (label, 'narrative outside widget')
        return lines[row:row + 2]
