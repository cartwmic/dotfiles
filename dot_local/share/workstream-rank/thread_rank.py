"""thread_rank.py THREAD: which workstream thread does THREAD belong to? Used by workstream-rank.

stdin: the PANE column of the rank file, one value per line. Prints the first of those values, of the form
`t3:<thread id>`, that names the nearest thread at or above THREAD (its parent, its parent's parent, ...)
in T3's thread tree, and nothing when there is none. The nearest wins, so a builder a lead launched takes
the lead's rank. The walk is t3_lineage.nearest, the one token-efficiency/workstreams.py uses.

T3 database: $WORKSTREAM_RANK_T3_DB, else $T3CODE_HOME/userdata/statev2.sqlite, else ~/.t3/userdata/statev2.sqlite.
Exit 0 when it could look (found or not); exit 3, with a line on stderr, when it could not read the database.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t3_lineage  # noqa: E402


def db_path():
    given = os.environ.get('WORKSTREAM_RANK_T3_DB')
    if given:
        return given
    home = os.environ.get('T3CODE_HOME') or os.path.join(os.path.expanduser('~'), '.t3')
    return os.path.join(home, 'userdata', 'statev2.sqlite')


def main(argv):
    if len(argv) != 2:
        sys.stderr.write('usage: thread_rank.py THREAD  (rank-file PANE values on stdin)\n')
        return 2
    owners = {}
    for line in sys.stdin:
        ref = line.rstrip('\r\n')
        if ref.startswith('t3:') and len(ref) > 3:
            owners.setdefault(ref[3:], ref)
    path = db_path()
    try:
        parents = t3_lineage.Parents(path)
        try:
            found = t3_lineage.nearest(argv[1], parents, owners)
        finally:
            parents.close()
    except Exception as e:  # an unreadable or changed database: say so, never guess
        sys.stderr.write('thread_rank: cannot read %s: %s\n' % (path, e))
        return 3
    if found:
        print(found)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
