import os

base = 'D:/项目/Armavoke'
total = 0
for root, dirs, files in os.walk(base):
    if '.git' in root.split(os.sep):
        continue
    for f in files:
        if f.endswith('.java'):
            total += 1
            print(os.path.relpath(os.path.join(root, f), base))
print(f'\nTotal: {total} Java files')
