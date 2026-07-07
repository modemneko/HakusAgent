export function format(urlObj: any): string {
  if (typeof urlObj === 'string') return urlObj
  let result = ''
  if (urlObj.protocol) result += urlObj.protocol
  if (urlObj.hostname) {
    result += '//'
    if (urlObj.auth) result += urlObj.auth + '@'
    result += urlObj.hostname
    if (urlObj.port) result += ':' + urlObj.port
  }
  if (urlObj.pathname) result += urlObj.pathname
  if (urlObj.search || urlObj.query) {
    const search = typeof urlObj.search === 'string' ? urlObj.search : urlObj.query
    if (search && !search.startsWith('?')) result += '?' + search
    else result += search
  }
  if (urlObj.hash) result += urlObj.hash
  return result
}

export function parse(urlStr: string): any {
  try {
    return new URL(urlStr)
  } catch {
    return { href: urlStr, pathname: urlStr }
  }
}

export function resolve(from: string, to: string): string {
  try {
    return new URL(to, from).href
  } catch {
    return to
  }
}

export default { format, parse, resolve }
