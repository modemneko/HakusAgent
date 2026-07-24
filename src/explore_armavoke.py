import os

base = 'D:/项目/Armavoke'

# Count total import lines and non-wildcard import lines
total_imports = 0
non_wildcard = 0
wildcard = 0

for root, dirs, files in os.walk(base):
    if '.git' in root.split(os.sep):
        continue
    for f in files:
        if f.endswith('.java'):
            path = os.path.join(root, f)
            with open(path, encoding='utf-8') as fh:
                for line in fh:
                    stripped = line.strip()
                    if stripped.startswith('import '):
                        total_imports += 1
                        if stripped.endswith('.*;'):
                            wildcard += 1
                        else:
                            non_wildcard += 1
                            print(f'Non-wildcard: {os.path.relpath(path, base)} -> {stripped}')

print(f'\nTotal imports: {total_imports}')
print(f'Wildcard: {wildcard}')
print(f'Non-wildcard: {non_wildcard}')
