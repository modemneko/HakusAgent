import subprocess, os
os.chdir('D:/项目/Armavoke')
result = subprocess.run(['git', 'pull'], capture_output=True, text=True)
print('STDOUT:', result.stdout)
print('STDERR:', result.stderr)
print('Return:', result.returncode)
