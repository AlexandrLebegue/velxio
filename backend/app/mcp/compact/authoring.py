"""Plain-text sketch authoring; never decode escapes or normalize source text."""
import copy
from .catalog import CatalogError
from .sketches import lex


def sketch_document(catalog, arguments, document=None):
    if document is None:
        reference = catalog.get_reference(id='board:' + arguments.get('board', 'arduino-uno'), section='project')
        if not reference.get('ok'):
            raise CatalogError('unsupported_board', 'Select a known catalog board before saving a sketch')
        document = reference['data']
    else:
        document = copy.deepcopy(document)
    board_id = arguments.get('board_id', document['activeBoardId'])
    board = next((item for item in document['boards'] if item['id'] == board_id), None)
    if board is None:
        raise CatalogError('invalid_argument', 'board_id must select an existing board')
    entry = catalog.get_reference(id='board:' + board['boardKind'])
    if (not entry.get('ok') or 'arduino' not in entry['data'].get('languages', [])
            or board.get('languageMode', 'arduino') != 'arduino'):
        raise CatalogError('unsupported', 'Plain sketches require an Arduino board/mode; language is never changed implicitly')
    board.setdefault('libraries', [])
    if 'libraries' in arguments:
        board['libraries'] = copy.deepcopy(arguments['libraries'])
    group = document['fileGroups'][board['activeFileGroupId']]
    target = next((item for item in group if item['name'] == 'sketch.ino'),
                  next((item for item in group if item['name'].endswith('.ino')), None))
    if target is None:
        target = {'name': 'sketch.ino', 'content': ''}
        group.append(target)
    target['content'] = arguments['sketch']
    return document, board_id, target['name']


def sketch_warnings(source, name):
    if len(source.strip('\r\n').splitlines()) > 1:
        return []
    _, comments, empty = lex(source)
    warnings = []
    if any(source.startswith('//', index) for index in comments):
        warnings.append({'file': name, 'observed': 'A single physical line contains a // comment; following code may be hidden.',
                         'correction': 'Resend real newlines after comments. Literal backslash-n is not a newline.'})
    if empty:
        warnings.append({'file': name, 'observed': "A single-line sketch contains empty character literals ('').",
                         'correction': 'Use double quotes for strings, e.g. Serial.println("Hello"), not two single quotes.'})
    return warnings
