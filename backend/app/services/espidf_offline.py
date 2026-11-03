"""ESP32 approved-template policy: no automatic acquisition, not an OS sandbox."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import stat

TEMPLATE_SHA256 = '666ebe7e75bab82d0164755a74a1cc56353ff5e513599a8e75ff94a442e56182'
SOURCE_SUFFIXES = {'.ino', '.c', '.cpp', '.h', '.hpp'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def tree_manifest(root):
    """Pin every regular file; reject links/special files and unbounded trees."""
    root = Path(root)
    if not root.is_absolute() or any(p in ('.', '..') for p in root.parts):
        raise ValueError('Cache root must be absolute')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    result, total = {}, 0
    try:
        for part in root.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        def walk(directory, prefix=''):
            nonlocal total
            for name in sorted(os.listdir(directory)):
                if name in ('.', '..') or '/' in name or '\\' in name:
                    raise ValueError('Unsafe cache name')
                relative = prefix + name
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                try:
                    st = os.fstat(child)
                    if stat.S_ISDIR(st.st_mode):
                        walk(child, relative + '/')
                    elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
                        total += st.st_size
                        if total > 64 * 1024 * 1024 or len(result) >= 8192:
                            raise ValueError('Cache tree quota exceeded')
                        with os.fdopen(child, 'rb', closefd=False) as stream:
                            raw = stream.read(64 * 1024 * 1024 + 1)
                        result[relative] = hashlib.sha256(raw).hexdigest()
                    else:
                        raise ValueError('Cache links/special files are forbidden')
                finally:
                    os.close(child)
        walk(fd)
    finally:
        os.close(fd)
    return result


def approved_template(root):
    try:
        return digest(tree_manifest(Path(root).absolute())) == TEMPLATE_SHA256
    except (OSError, ValueError):
        return False


def verify_sdk(evidence, idf, arduino=None):
    """Bind already verified member hashes to the SDK paths actually selected."""
    root = evidence['inventory_root']
    members = {str(Path(root) / m['path']): m['sha256'] for m in evidence['members']}
    required = [Path(idf) / 'tools/idf.py', Path(idf) / 'tools/cmake/project.cmake']
    if arduino is not None:
        required.append(Path(arduino) / 'CMakeLists.txt')
    for path in required:
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('SDK proof path must be absolute and contained')
        if str(path) not in members:
            raise ValueError('Selected SDK file is not pinned: ' + str(path))
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            source = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                st = os.fstat(source)
                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > 32 * 1024 * 1024:
                    raise ValueError('Unsafe SDK proof file')
                with os.fdopen(source, 'rb', closefd=False) as stream:
                    raw = stream.read(32 * 1024 * 1024 + 1)
                if hashlib.sha256(raw).hexdigest() != members[str(path)]:
                    raise ValueError('SDK proof changed')
            finally:
                os.close(source)
        finally:
            os.close(fd)


def validate_sources(files):
    if not files or len(files) > 128:
        raise ValueError('1..128 source files required')
    seen = set()
    for item in files:
        name = item['name']
        if (not isinstance(name, str) or '\\' in name or re.search(r'[\x00-\x1f:"<>|?*]', name)
                or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))
                or Path(name).suffix not in SOURCE_SUFFIXES):
            raise ValueError('Only relative C/C++/Arduino sources are supported; build scripts/manifests forbidden')
        base = Path(name).name.casefold()
        if base in seen:
            raise ValueError('Flattened source filename collision')
        seen.add(base)
        code = item['content']
        if not isinstance(code, str) or len(code.encode()) > 256 * 1024:
            raise ValueError('Source quota/type invalid')
        if '\\\n' in code or '%:' in code or '??=' in code:
            raise ValueError('Preprocessor continuations/digraphs/trigraphs are unsupported')
        code = re.sub(r'/\*.*?\*/', ' ', code, flags=re.S)
        if re.search(r'#\s*(include_next|embed)\b|\.(incbin|include)\b', code):
            raise ValueError('External inclusion/embedded file reads are unsupported')
        for line in code.splitlines():
            if re.match(r'\s*#\s*include\b', line):
                match = re.match(r'\s*#\s*include\s*[<"]([^>"\n]+)[>"]', line)
                if not match:
                    raise ValueError('Computed includes are unsupported in offline sources')
                path = match[1]
                if path.startswith('/') or '\\' in path or ':' in path or '..' in path.split('/'):
                    raise ValueError('Outgoing include paths are forbidden')


class OfflinePlan:
    def __init__(self, template, evidence, libraries, required, managed):
        if not approved_template(template):
            raise ValueError('Template differs from reviewed bytes')
        self.evidence, self.libraries, self.managed = evidence, libraries, managed
        self.managed_names = {item['name'] for item in managed}
        self.check_managed(required)

    def check_managed(self, dependencies):
        if set(dependencies) - self.managed_names:
            raise ValueError('Required managed components are not cached and verified: ' + ','.join(sorted(set(dependencies) - self.managed_names)))
        return False

    def stage(self, project, scope):
        """Only already verified cache content; never download or sync manifests."""
        for name, proof in self.libraries.items():
            self._copy_tree(proof, scope / hashlib.sha256(name.encode()).hexdigest()[:16], scripts=False)
        for item in self.managed:
            name = item['name'].replace('/', '__')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
                raise ValueError('Invalid managed component name')
            self._copy_tree(item, project / 'components' / name, scripts=True)

    @staticmethod
    def _copy_tree(proof, target, scripts):
        root = Path(proof['source_root'])
        before = tree_manifest(root)
        if digest(before) != proof['tree_sha256']:
            raise ValueError('Cached dependency tree hash differs')
        # Cached managed CMake is limited to registration primitives. SDK/core
        # recipes remain trusted local installation; no OS isolation is claimed.
        for path in before:
            if Path(path).suffix in ('.cmake', '.py', '.sh', '.bat', '.ps1') or Path(path).name == 'CMakeLists.txt':
                if not scripts:
                    continue  # Never stage/execute a library's own build recipes.
                if Path(path).suffix in ('.py', '.sh', '.bat', '.ps1'):
                    raise ValueError('External dependency build hooks/scripts are unsupported')
                text = '\n'.join(line.split('#', 1)[0] for line in (root / path).read_text().splitlines())
                # Deliberately narrow: no set/include/function/variables, hooks,
                # generator expressions, or extra commands from cache recipes.
                match = re.fullmatch(r'\s*idf_component_register\s*\(([^()]*)\)\s*', text, re.I)
                if not match or re.search(r'[^A-Za-z0-9_./\s\"\'-]', match[1]):
                    raise ValueError('Cached component requires unaudited CMake primitives')
                for token in shlex.split(match[1]):
                    if token.startswith('/') or '..' in token.split('/'):
                        raise ValueError('Outgoing cached component path')
        def ignore(_directory, names):
            return {name for name in names if not scripts and (name == 'CMakeLists.txt' or Path(name).suffix in ('.cmake', '.py', '.sh', '.bat', '.ps1'))}
        expected = {p: h for p, h in before.items() if scripts or not (Path(p).name == 'CMakeLists.txt' or Path(p).suffix in ('.cmake', '.py', '.sh', '.bat', '.ps1'))}
        shutil.copytree(root, target, symlinks=True, ignore=ignore)
        if tree_manifest(root) != before or tree_manifest(target) != expected:
            raise ValueError('Dependency changed while staging')

    @staticmethod
    def environment(env):
        env = dict(env)
        env.update(IDF_COMPONENT_MANAGER='0', IDF_COMPONENT_MANAGER_ENABLED='0',
                   FETCHCONTENT_FULLY_DISCONNECTED='ON', PIP_NO_INDEX='1', GIT_TERMINAL_PROMPT='0', CCACHE_DISABLE='1')
        env.pop('CCACHE_REMOTE_STORAGE', None)
        return env
