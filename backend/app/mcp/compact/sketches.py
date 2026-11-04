"""Conservative Arduino source sanity checks; no compiler or macro evaluation."""
import re


def lex(source):
    """Mask comments/literals while preserving offsets and physical newlines."""
    masked = list(source)
    comments, empty_characters = [], []
    index, size = 0, len(source)
    while index < size:
        start, end = index, None
        if source.startswith('//', index):
            end = source.find('\n', index)
            while end > 0 and source[end - 1] == '\\':
                end = source.find('\n', end + 1)
            end = size if end < 0 else end
            comments.append(start)
        elif source.startswith('/*', index):
            stop = source.find('*/', index + 2)
            end = size if stop < 0 else stop + 2
            comments.append(start)
        elif source.startswith('R"', index):
            raw = re.match(r'R"([^\s()\\]{0,16})\(', source[index:index + 20])
            if raw:
                closing = ')' + raw[1] + '"'
                stop = source.find(closing, index + len(raw[0]))
                end = size if stop < 0 else stop + len(closing)
        elif source[index] in ('"', "'"):
            quote = source[index]
            if source.startswith("''", index):
                empty_characters.append(index)
            end = index + 1
            while end < size:
                if source[end] == '\\':
                    end += 2
                elif source[end] == quote:
                    end += 1
                    break
                else:
                    end += 1
            end = min(end, size)
        if end is None:
            index += 1
            continue
        for position in range(start, end):
            if source[position] not in '\r\n':
                masked[position] = ' '
        index = end
    return ''.join(masked), comments, empty_characters


def sketch_issues(files, group_path):
    """Return actionable errors for obvious corruption, not a C++ validity proof."""
    sources = [(index, item) for index, item in enumerate(files)
               if item['name'].endswith(('.ino', '.cpp', '.cc', '.cxx', '.h', '.hpp'))]
    if not sources:
        return [{'code': 'sketch_sources_missing', 'severity': 'error', 'path': group_path,
                 'file': 'sketch.ino', 'message': 'No Arduino or C++ source file is present.',
                 'observed': 'No Arduino or C++ source file is present.',
                 'expected': 'Add sketch.ino with active void setup() and void loop() definitions.',
                 'next_action': 'Add sketch.ino to this file group, save a new project version and call check_project.'}]
    primary = next(((index, item) for index, item in sources if item['name'] == 'sketch.ino'),
                   next(((index, item) for index, item in sources if item['name'].endswith('.ino')), None))
    if not primary:
        primary = sources[0] if sources else (0, {'name': 'sketch.ino', 'content': ''})
    issues, active, any_comments = [], [], False
    def issue(index, item, code, observed, expected):
        issues.append({'code': code, 'severity': 'error', 'path': f'{group_path}/{index}/content',
                       'file': item['name'][:240], 'message': observed[:240], 'observed': observed[:240],
                       'expected': expected, 'next_action': f"Repair {item['name'][:240]}, save a new project version, then call check_project before building."})
    for index, item in sources:
        source = item['content']
        clean, comments, empty = lex(source)
        any_comments |= bool(comments)
        lines = source.strip('\r\n').splitlines()
        if (item['name'].endswith('.ino') or index == primary[0]) and len(lines) <= 1 and ((comments and clean.strip()) or re.search(r'#\s*[a-zA-Z_]', clean)):
            issue(index, item, 'sketch_collapsed_lines', 'A single physical line contains a comment or preprocessor directive.',
                  'Preserve real newlines after // comments and around preprocessor directives.')
        if empty:
            issue(index, item, 'sketch_empty_character_literal', "An empty character literal ('') appears outside comments and strings.",
                  'Use double quotes for strings, e.g. Serial.println("Hello"), not two single quotes.')
        # Macro bodies are not function definitions. Preserve newlines in the
        # mask, including directives continued with a backslash.
        continuation = False
        body = []
        for line in clean.splitlines(keepends=True):
            if continuation or line.lstrip().startswith('#'):
                continuation = line.rstrip('\r\n').endswith('\\')
                body.append('\n' if line.endswith('\n') else '')
            else:
                body.append(line)
        active.append(''.join(body))
    program = '\n'.join(active)
    index, item = primary
    if not program.strip() and any_comments:
        issue(index, item, 'sketch_comment_only', 'All Arduino source code is inside comments.',
              'Provide active void setup() and void loop() definitions outside comments.')
    missing = [name for name in ('setup', 'loop')
               if not re.search(r'\bvoid\s+' + name + r'\s*\(\s*(?:void\s*)?\)\s*(?:noexcept\s*)?\{', program)]
    if missing:
        issue(index, item, 'sketch_missing_entry_points', 'Missing active function definitions: ' + ', '.join(name + '()' for name in missing),
              'Define void setup() { ... } and void loop() { ... }; declarations and text in comments/strings do not count.')
    return issues
