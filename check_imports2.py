"""Check for non-wildcard static imports and any special import patterns."""
import os

base = r'D:\项目\Armavoke'
found_any = False

for root, dirs, files in os.walk(base):
    if '.git' in root.split(os.sep):
        continue
    for f in files:
        if f.endswith('.java'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                for i, line in enumerate(fp, 1):
                    s = line.strip()
                    if s.startswith('import '):
                        # Check for non-wildcard
                        if not s.endswith('.*;') and not s.endswith('*;'):
                            print(f'NON-WILDCARD: {os.path.relpath(path, base)}:{i}: {s}')
                            found_any = True
                        # Also show static imports for review
                        if s.startswith('import static '):
                            print(f'  STATIC: {os.path.relpath(path, base)}:{i}: {s}')

if not found_any:
    print('All Java files already use wildcard imports.')
