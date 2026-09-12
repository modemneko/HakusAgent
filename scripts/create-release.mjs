// 发布 v0.3.0：创建 Release 并上传安装包/签名/latest.json
// 认证使用本机 git 凭据（不打印任何令牌）。
import https from 'node:https'
import { execSync } from 'node:child_process'
import fs from 'node:fs'

            const cred = execSync('printf "protocol=https\\nhost=github.com\\n" | git credential fill', { encoding: 'utf-8', shell: 'bash' })
const token = cred.split('\n').find(l => l.startsWith('password='))?.slice('password='.length)
if (!token) { console.error('未找到 git 凭据'); process.exit(1) }

const api = (path, method = 'GET', body = null, isBinary = false) => new Promise((resolve, reject) => {
  const data = body ? (isBinary ? body : JSON.stringify(body)) : null
  const req = https.request({
    host: 'uploads.github.com' , path: path.replace('__UPLOADS__', 'api.github.com'), method,
  }, () => {})
  req.on('error', reject)
  req.end(data)
})
// ↑ 占位；实际逻辑在下方 repo/host 分离版本

function repoApi(path, method = 'GET', body = null) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null
    const req = https.request({
      host: 'api.github.com',
      path,
      method,
      headers: {
        'User-Agent': 'hakus-release',
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/vnd.github+json',
        ...(data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {}),
      },
    }, res => {
      let b = ''
      res.on('data', c => b += c)
      res.on('end', () => { try { resolve({ status: res.statusCode, json: b ? JSON.parse(b) : null }) } catch { resolve({ status: res.statusCode, json: null }) } })
    })
    req.on('error', reject)
    if (data) req.write(data)
    req.end()
  })
}

function uploadAsset(uploadUrl, name, filePath, contentType) {
  return new Promise((resolve, reject) => {
    const base = uploadUrl.split('{')[0]
    const data = fs.readFileSync(filePath)
    const req = https.request({
      host: 'uploads.github.com',
      path: `${base}?name=${encodeURIComponent(name)}`,
      method: 'POST',
      headers: {
        'User-Agent': 'hakus-release',
        'Authorization': `Bearer ${token}`,
        'Content-Type': contentType,
        'Content-Length': data.length,
      },
    }, res => {
      let b = ''
      res.on('data', c => b += c)
      res.on('end', () => resolve({ status: res.statusCode, body: b.slice(0, 120) }))
    })
    req.on('error', reject)
    req.write(data)
    req.end()
  })
}

const tag = 'v0.3.0'
// 幂等：已存在则复用
let release = (await repoApi(`/repos/modemneko/HakusAgent/releases/tags/${tag}`)).json
if (!release) {
  const created = await repoApi('/repos/modemneko/HakusAgent/releases', 'POST', {
    tag_name: tag,
    target_commitish: 'master',
    name: 'HakusAI v0.3.0',
    body: [
      '## 修复',
      '- 发送消息导致后端栈溢出崩溃（桌面 Runtime 栈提升至 16MB）',
      '- 切换供应商后在旧对话发消息 400（线程路由跟随当前默认供应商）',
      '- 保存自定义供应商后编辑器黑屏（配置落盘竞态）',
      '- 自定义供应商开关报 Unknown provider id（大小写不敏感解析）',
      '- 失败轮次现在在聊天气泡中显示错误详情（此前为空气泡）',
      '- 偶发白屏：新增全局错误边界与崩溃留痕，可恢复可追溯',
      '- 安卓 CI 清单补丁步骤失败',
      '',
      '## 新增 / 改进',
      '- 模型相关设置自动保存（无需手动保存按钮）',
      '- 内置模型商可删除（重置并隐藏，可随时重新启用），删除使用内置确认弹窗',
      '- 紧凑侧栏重新设计为功能按钮轨道',
      '- 模型商选择等下拉列表统一液态玻璃风格',
      '- 品牌化安装/卸载向导（中文向导 + 开机自启勾选）',
      '',
      '**SHA256:** 见下方 assets 说明；Windows 安装包已用更新签名密钥签名，应用内可自动更新。',
    ].join('\n'),
    draft: false,
    prerelease: false,
  })
  release = created.json
  console.log('release created:', release.id)
} else {
  console.log('release exists:', release.id)
}

const dir = 'HakusAgent/frontend/desktop-tauri/src-tauri/target/release/bundle/nsis'
console.log('upload setup.exe:', JSON.stringify(await uploadAsset(release.upload_url, 'HakusAI_0.3.0_x64-setup.exe', `${dir}/HakusAI_0.3.0_x64-setup.exe`, 'application/octet-stream')))
console.log('upload .sig:', JSON.stringify(await uploadAsset(release.upload_url, 'HakusAI_0.3.0_x64-setup.exe.sig', `${dir}/HakusAI_0.3.0_x64-setup.exe.sig`, 'text/plain')))
console.log('upload latest.json:', JSON.stringify(await uploadAsset(release.upload_url, 'latest.json', `${dir}/latest.json`, 'application/json')))
console.log('DONE')
