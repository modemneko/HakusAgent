"""Check for non-wildcard imports in Java files."""
import os

base = r'D:\项目\Armavoke'
found = False

for root, dirs, files in os.walk(base):
    if '.git' in root.split(os.sep):
        continue
    for f in files:
        if f.endswith('.java'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                for i, line in enumerate(fp, 1):
                    s = line.strip()
                    if s.startswith('import ') and ';' in s and not s.endswith('.*;') and not s.endswith('*;'):
                        print(f'{os.path.relpath(path, base)}:{i}: {s}')
                        found = True

if not found:
    print('All Java files already use wildcard imports (import ...*;). No conversion needed.')
else:
    print('\nSome non-wildcard imports found above.')
