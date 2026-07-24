import os

base = 'D:/项目/Armavoke'
# Search for Python files with import statements
for root, dirs, files in os.walk(base):
    if '.git' in root.split(os.sep):
        continue
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            print(f'=== {os.path.relpath(path, base)} ===')
            with open(path, encoding='utf-8') as fh:
                content = fh.read()
            print(content)
            print()
