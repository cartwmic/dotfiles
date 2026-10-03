"""Current native popup canvas and wrapped human-card assertions (no raw IDs)."""
import re
import unicodedata
from wcwidth import wcwidth
import proof


def cell_slice(text, left, right):
    result = ''; column = 0
    for char in text:
        width = max(0, wcwidth(char))
        if left <= column < right or width == 0 and result:
            result += char
        column += width
        if column >= right and width:
            break
    return result


def compact(text):
    return ''.join(unicodedata.normalize('NFC', text).split())


def canvas(frame):
    lines = frame.splitlines()
    if lines and lines[0].startswith('Herdr Overview') and 'Esc/q' in lines[-1]:
        return lines
    for row, line in enumerate(lines):
        match = re.search(r'│Herdr Overview\s', line)
        if match:
            left = match.start() + 1
            right = line.rfind('│')
            if right <= left:
                break
            rows = []
            for current in lines[row:]:
                if cell_slice(current,left-1,left) != '│':
                    break
                rows.append(cell_slice(current,left,right))
            while rows and not rows[-1].strip():
                rows.pop()
            if rows and 'Esc/q' in rows[-1]:
                return rows
    raise proof.ProofFailure('no completed current native popup canvas with header and Esc/q footer')


def prose(frame):
    # Only remove borders and layout whitespace from completed current cells.
    return compact(''.join(canvas(frame)).replace('│', '').replace('┃', ''))


def contains(frame, marker):
    return compact(marker) in prose(frame)


def card(frame, target, snapshot):
    pane = next((p for p in snapshot['panes'] if p['pane_id'] == target), None)
    if not pane:
        raise proof.ProofFailure(f'selection target no longer native: {target}')
    tab = next(t for t in snapshot['tabs'] if t['tab_id'] == pane['tab_id'])
    multi = sum(p['tab_id'] == pane['tab_id'] for p in snapshot['panes']) > 1
    subject = pane.get('label') if multi else tab.get('label')
    if not subject:
        raise proof.ProofFailure('fixture target lacks an observable native human subject')
    rows = canvas(frame)
    found = []
    for n, line in enumerate(rows):
        marker = 'Pane' if multi else f'Tab {tab["number"]}'
        for match in re.finditer(re.escape(marker) + r'(?![0-9])', line):
            at = match.start()
            edge = line.rfind('│', 0, at)
            end = line.find('│', at)
            if edge < 0 or end < 0:
                continue
            expected = compact(subject)
            # The title block is one or two rows (paired cards share its height).
            def titled(count):
                titles = [cell_slice(row,edge+1,end) for row in rows[n+1:n+1+count]]
                title = compact(''.join(titles)).rstrip('…')
                return title and (expected == title or expected.startswith(title) and '…' in ''.join(titles))
            if titled(1) or titled(2):
                contents = []
                for row in rows[n:]:
                    contents.append(cell_slice(row,edge+1,end))
                    if row[edge:edge+1] == '└':
                        break
                found.append({'row': n, 'col': edge, 'rows': contents, 'selected': '›' in line[edge+1:end]})
    if len(found) > 1:
        raise proof.ProofFailure('ambiguous human card attribution; fixture needs distinct native subjects')
    return found[0] if found else None


def selected_in_frame(frame, target, snapshot):
    value = card(frame, target, snapshot)
    return bool(value and value['selected'])


def wait_frame(client, *markers, timeout=20):
    def ready():
        frame = client.frame()
        try:
            return frame if all(contains(frame, marker) for marker in markers) else None
        except proof.ProofFailure:
            return None
    return proof.wait_for(ready, 'completed current canvas: ' + ', '.join(markers), timeout=timeout)
