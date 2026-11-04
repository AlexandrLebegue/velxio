"""Bounded compiler diagnostics. Errors and warnings are distinct channels."""
import re
from pathlib import PurePosixPath

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def suggestion(message, severity='error'):
    if severity != 'error':
        return 'Review this warning separately; it does not establish build failure or success.'
    if re.search(r'No such file|file not found', message, re.I):
        return 'Check the include name and declare the required installed library. Do not assume a dependency is installed.'
    if re.search(r'empty character|multi-character|character constant', message, re.I):
        return 'Use double quotes for strings and a single character inside single quotes.'
    if re.search(r'not declared|undeclared|no member named', message, re.I):
        return 'Check the symbol spelling, includes and actual library API before rebuilding.'
    if re.search(r'undefined reference', message, re.I):
        return 'Provide the missing definition or library; Arduino requires real setup() and loop() definitions.'
    return 'Fix this first error, save a new project version and rebuild; warnings are secondary.'


def parse_line(line):
    line = ANSI.sub('', line[:4096]).strip()
    match = re.match(r'(.+?):([0-9]{1,10})(?::([0-9]{1,10}))?:\s*(fatal error|error|warning|note):\s*(.*)', line)
    if match:
        name, number, column, severity, message = match.groups()
    else:
        bare = re.match(r'(fatal error|error|warning|note):\s*(.*)', line)
        match = re.match(r'(.+?):\s*(fatal error|error|warning|note):\s*(.*)', line) if not bare else None
        if bare:
            name = None
            severity, message = bare.groups()
        elif match:
            name, severity, message = match.groups()
        elif 'undefined reference to' in line:
            name, severity, message = None, 'error', line
        else:
            return None
        number = column = None
    severity = 'error' if severity == 'fatal error' else severity
    return {'file': PurePosixPath(name.replace('\\', '/')).name[:240] if name else None,
            'line': int(number) if number else None, 'column': int(column) if column else None,
            'severity': severity, 'message': (message.strip() or 'Compiler reported ' + severity + ' without a message.')[:240],
            'suggestion': suggestion(message, severity)}


def first_error(row):
    return {key: row[key] for key in ('file', 'line', 'message', 'suggestion')}


def capture(job, chunk, *, final=False):
    """Retain the first real streamed error even if the log tail is truncated."""
    if job.get('first_error'):
        return
    text = job.pop('_diagnostic_carry', '') + chunk
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(('\n', '\r')) and not final:
        job['_diagnostic_carry'] = lines.pop()[:4096]
    for line in lines:
        row = parse_line(line)
        if row and row['severity'] == 'error':
            job['first_error'] = first_error(row)
            job.pop('_diagnostic_carry', None)
            break


def diagnostics(raw, artifact, request):
    errors, notes, warnings, counts = [], [], [], {'error': 0, 'note': 0, 'warning': 0}
    files = request['files']
    inos = [item for item in files if item['name'].endswith('.ino')]
    primary = next((item['name'] for item in inos if item['name'] == 'sketch.ino'), inos[0]['name'] if inos else files[0]['name'] if files else None)
    for index, line in enumerate(raw.decode('utf8').splitlines(), 1):
        row = parse_line(line)
        if not row:
            continue
        severity = row['severity']
        counts[severity] += 1
        rows = errors if severity == 'error' else warnings if severity == 'warning' else notes
        if len(rows) >= (5 if severity == 'warning' else 10):
            continue
        known = next((item['name'] for item in files if item['name'] == row['file']), None)
        row.update(file_known=known is not None, source='compiler_log', log_line=index,
                   artifact_id=artifact['id'], log_sha256=artifact['sha256'],
                   source_file_hint=primary if row['file'] == 'sketch.ino.cpp' else known, line_mapping_verified=False)
        rows.append(row)
    rows = (errors + notes)[:10]
    return rows, counts['error'] + counts['note'] > len(rows), warnings, counts['warning'] > len(warnings)
