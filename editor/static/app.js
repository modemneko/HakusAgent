class EditorApp {
  constructor() {
    this.ws = null
    this.editor = null
    this.term = null
    this.fitAddon = null
    this.tabs = []
    this.activePath = null
    this.models = {}
    this.files = {}
    this.reconnectTimer = null
    this.inlineEdit = { active: false, range: null, original: '', newCode: '' }
    this.ghostDeco = null
    this.ghostText = ''
    this.ghostPos = null
    this.streamMsg = null
    this.streamText = ''
    this.connected = false
    this.gl = null
    this.monacoReady = false
    this.termReady = false

    const extMap = { py:'#3572A5', js:'#F7DF1E', ts:'#3178C6', tsx:'#61DAFB', jsx:'#61DAFB',
      html:'#E34F26', css:'#1572B6', json:'#292929', md:'#519ABA', yaml:'#CB171E',
      yml:'#CB171E', rs:'#DEA584', go:'#00ADD8', java:'#ED8B00',
      c:'#555', cpp:'#00599C', h:'#555', sh:'#89e051', bat:'#C1F12E',
      txt:'', csv:'#207245', xml:'#E37933', svg:'#FFB13B',
      gitignore:'#F05032', env:'#ECD53F' }
    this.extMap = extMap
    this.init()
  }

  init() {
    this.initTerminal()
    this.initMonaco()
    this.connectWS()
    this.bindEvents()
    this.initGoldenLayout()
  }

  initGoldenLayout() {
    const GoldenLayout = window.GoldenLayout
    if (!GoldenLayout) {
      console.error('GoldenLayout not found on window, retrying...')
      setTimeout(() => this.initGoldenLayout(), 100)
      return
    }

    const config = {
      settings: {
        hasHeaders: true,
        constrainDragToContainer: true,
        reorderEnabled: true,
        selectionEnabled: false,
        popoutWholeStack: false,
        blockedPopoutsThrowError: true,
        closePopoutsOnUnload: true,
        showPopoutIcon: false,
        showMaximiseIcon: true,
        showCloseIcon: false,
        responsiveMode: 'onload',
        tabOverlapThreshold: 0.4,
        reorderOnTabMenuClick: true,
        tabControlOffset: 10,
      },
      dimensions: {
        borderWidth: 4,
        minItemHeight: 30,
        minItemWidth: 100,
        headerHeight: 28,
        dragProxyWidth: 300,
        dragProxyHeight: 200,
      },
      labels: {
        close: 'close',
        maximise: 'maximise',
        minimise: 'minimise',
        popout: 'open in new window',
        popin: 'pop in',
        tabDropdown: 'additional tabs',
      },
      content: [
        {
          type: 'row',
          content: [
            {
              type: 'component',
              componentName: 'sidebar',
              title: 'Explorer',
              width: 15,
              minWidth: 100,
            },
            {
              type: 'column',
              width: 65,
              content: [
                {
                  type: 'component',
                  componentName: 'editor',
                  title: 'Editor',
                  height: 70,
                },
                {
                  type: 'component',
                  componentName: 'terminal',
                  title: 'Terminal',
                  height: 30,
                  minHeight: 50,
                },
              ],
            },
            {
              type: 'component',
              componentName: 'aipanel',
              title: 'AI Assistant',
              width: 20,
              minWidth: 180,
            },
          ],
        },
      ],
    }

    this.gl = new GoldenLayout(config, document.getElementById('goldenLayoutContainer'))

    const self = this
    this.gl.registerComponent('sidebar', function(container, state) {
      const $el = container.getElement()
      const el = $el[0]
      if (!el) { console.error('GL sidebar: getElement() returned empty'); return }
      el.innerHTML = self._buildSidebarHTML()
      self._bindSidebarEvents(el)
      container.on('resize', function() {})
    })

    this.gl.registerComponent('editor', function(container, state) {
      const el = container.getElement()[0]
      el.className = 'gl-editor-wrap'
      el.innerHTML = '<div class="gl-tab-bar" id="glTabBar"></div>'
        + '<div class="gl-editor-area" id="glEditorArea">'
        + '<div id="welcomeScreen" class="gl-welcome">'
        + '<div class="welcome-inner"><div class="welcome-logo">&#x26a1;</div>'
        + '<h1>Welcome to HakusAI</h1>'
        + '<p>AI-powered code editor &middot; Real-time assistance</p>'
        + '<div class="welcome-actions">'
        + '<button class="btn primary" id="glNewFile"><b>+</b> New File</button>'
        + '<button class="btn ghost" id="glOpenFiles">Open Files</button></div>'
        + '<div class="welcome-shortcuts">'
        + '<span><kbd>Ctrl+S</kbd> Save</span>'
        + '<span><kbd>Ctrl+K</kbd> AI Edit</span>'
        + '<span><kbd>Enter</kbd> Send</span></div></div></div>'
        + '<div id="glEditorContainer" style="position:absolute;inset:0;"></div></div>'

      const editorContainer = el.querySelector('#glEditorContainer')
      el.querySelector('#glNewFile').onclick = () => self.newFile()
      el.querySelector('#glOpenFiles').onclick = () => self.loadTree()

      self._editorContainer = editorContainer
      self._editorGLContainer = container
      self._editorElement = el

      container.on('resize', () => {
        if (self.editor) self.editor.layout()
      })
      container.on('shown', () => {
        if (self.editor) self.editor.layout()
      })

      if (self.monacoReady && self.editor) {
        self._moveEditorTo(editorContainer)
      }
    })

    this.gl.registerComponent('aipanel', function(container, state) {
      const el = container.getElement()[0]
      el.innerHTML = self._buildAIPanelHTML()
      self._bindAIPanelEvents(el)
      self._aiPanelContainer = el
    })

    this.gl.registerComponent('terminal', function(container, state) {
      const el = container.getElement()[0]
      el.className = 'gl-terminal'
      el.innerHTML = '<div id="glTermContainer"></div>'
      self._termGLContainer = container

      container.on('resize', () => {
        if (self.termReady && self.fitAddon) {
          try { self.fitAddon.fit() } catch(e) {}
        }
      })
      container.on('shown', () => {
        if (self.termReady && self.fitAddon) {
          setTimeout(() => { try { self.fitAddon.fit() } catch(e) {} }, 100)
        }
      })

      if (self.termReady && self.term) {
        self._moveTerminalTo(el.querySelector('#glTermContainer'))
      }
    })

    const container = document.getElementById('goldenLayoutContainer')
    const doInit = () => {
      const rect = container.getBoundingClientRect()
      console.log('GL container rect:', rect.width, 'x', rect.height)
      if (rect.height > 50 && rect.width > 100) {
        console.log('GL init starting...')
        try {
          this.gl.init()
          console.log('GL init done, root element:', container.querySelector('.lm_root') ? 'found' : 'NOT FOUND')
        } catch(e) {
          console.error('GL init error:', e)
        }
      } else {
        setTimeout(doInit, 50)
      }
    }
    setTimeout(doInit, 100)
    setTimeout(() => { console.log('GL updateSize'); this.gl.updateSize() }, 1000)
  }

  _buildSidebarHTML() {
    return '<div class="gl-sidebar">'
      + '<div class="sb-header"><span>EXPLORER</span>'
      + '<button class="sb-new-btn" id="glNewFileBtn2" title="New File">+</button></div>'
      + '<div class="file-tree" id="glFileTree"><div class="ft-loading">Loading...</div></div>'
      + '</div>'
  }

  _buildAIPanelHTML() {
    return '<div class="gl-ai-panel">'
      + '<div class="ap-header"><span>&#x1f916; AI Assistant</span>'
      + '<button class="ap-clear" id="glClearChatBtn" title="Clear">&#x1f5d1;</button></div>'
      + '<div class="chat-scroll"><div class="chat-msgs" id="glChatMsgs">'
      + '<div class="msg msg-ai"><div class="msg-bubble">'
      + 'Hi! I\'m your AI coding assistant.<br><br>'
      + 'I can help you:<br>'
      + '&bull; Write or modify code<br>'
      + '&bull; Explain code<br>'
      + '&bull; Debug issues<br>'
      + '&bull; Start long-running tasks<br><br>'
      + 'Select code and press <kbd>Ctrl+K</kbd> for inline editing.'
      + '</div></div></div></div>'
      + '<div class="chat-input-wrap">'
      + '<textarea id="glChatInput" placeholder="Ask AI... (@ to reference)" rows="2"></textarea>'
      + '<button id="glSendBtn" class="send-btn">Send &#x21a9;</button></div></div>'
  }

  _bindSidebarEvents(el) {
    const newBtn = el.querySelector('#glNewFileBtn2')
    if (newBtn) newBtn.onclick = () => this.newFile()
  }

  _bindAIPanelEvents(el) {
    const sendBtn = el.querySelector('#glSendBtn')
    const chatInput = el.querySelector('#glChatInput')
    const clearBtn = el.querySelector('#glClearChatBtn')
    if (sendBtn) sendBtn.onclick = () => this.sendChat()
    if (chatInput) {
      chatInput.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.sendChat() } }
      chatInput.oninput = (e) => this._atMenu(e)
    }
    if (clearBtn) clearBtn.onclick = () => this.clearChat()
  }

  _createEditor(container) {
    if (!container || !this.monacoReady || this.editor) return

    this.editor = monaco.editor.create(container, {
      theme: 'hakus-dark', fontSize: 14,
      fontFamily: "'Cascadia Code','JetBrains Mono',Consolas,monospace",
      fontLigatures: true, minimap: { enabled: true, maxColumn: 80 },
      smoothScrolling: true, cursorBlinking: 'smooth', cursorSmoothCaretAnimation: 'on',
      padding: { top: 12, bottom: 10 }, automaticLayout: true,
      scrollBeyondLastLine: false, renderLineHighlight: 'all',
      suggestOnTriggerCharacters: true, quickSuggestions: true, wordBasedSuggestions: 'all',
      guides: { indentation: true, bracketPairs: true },
      bracketPairColorization: { enabled: true, independentColorPoolPerBracketType: true },
    })

    this.editor.addAction({ id: 'save', keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS], label: 'Save File', run: () => this.saveFile() })
    this.editor.addAction({ id: 'inline-edit', keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyK], label: 'AI Inline Edit', run: () => this.startInline() })
    this.editor.onDidChangeModelContent(() => {
      if (this.ghostDeco) { this.editor.deltaDecorations([this.ghostDeco], []); this.ghostDeco = null }
    })

    setTimeout(() => this.editor.layout(), 100)
  }

  _moveEditorTo(container) {
    this._editorContainer = container
    if (this.monacoReady) {
      this._createEditor(container)
    }
  }

  _moveTerminalTo(container) {
    const termNode = this.term.element
    if (termNode) {
      container.appendChild(termNode)
      setTimeout(() => { try { this.fitAddon.fit() } catch(e) {} }, 100)
    }
  }

  connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    try {
      this.ws = new WebSocket(`${proto}://${location.host}/ws`)
      this.ws.onopen = () => { this.connected = true; this.setStatus(true); this.loadTree() }
      this.ws.onclose = () => { this.connected = false; this.setStatus(false); this._reconnect() }
      this.ws.onerror = () => { this.connected = false; this.setStatus(false) }
      this.ws.onmessage = (e) => { try { this._handle(JSON.parse(e.data)) } catch(ex) {} }
    } catch(e) { this._reconnect() }
  }

  _reconnect() {
    if (this.reconnectTimer) return
    this.reconnectTimer = setTimeout(() => { this.reconnectTimer = null; this.connectWS() }, 3000)
  }

  setStatus(on) {
    document.getElementById('wsDot').className = 'ws-dot-sm' + (on ? ' on' : '')
    document.getElementById('statusDot').className = 'ws-dot-sm' + (on ? ' on' : '')
    document.getElementById('wsLabel').textContent = on ? 'Connected' : 'Disconnected'
    document.getElementById('statusText').textContent = on ? 'Connected' : 'Disconnected'
  }

  send(m) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(m))
  }

  _handle(msg) {
    console.log('WS msg:', msg.type, msg.data)
    const handlers = {
      file_tree: (d) => { console.log('file_tree received, nodes:', d ? d.length : 0); this.renderTree(d) },
      file_content: (d) => this.openFile(d.path, d.content),
      file_saved: (d) => this.onSaved(d.path),
      file_created: (d) => this.onCreated(d.path),
      ai_stream: (d) => this._aiStream(d.text || ''),
      ai_done: (d) => this._aiDone(d.content || ''),
      inline_edit: (d) => this._inlineResult(d.code, d.error),
      terminal_output: (d) => this._termOut(d),
      task_update: (d) => this._taskUpdate(d),
      settings: (d) => this._settings(d),
      error: (d) => this._error(d.message)
    }
    const fn = handlers[msg.type]
    if (fn) fn(msg.data)
    else console.log('Unknown msg type:', msg.type)
  }

  initMonaco() {
    require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' } })
    require(['vs/editor/editor.main'], () => {
      monaco.editor.defineTheme('hakus-dark', {
        base: 'vs-dark', inherit: true,
        rules: [
          { token: 'comment', foreground: '6c7086', fontStyle: 'italic' },
          { token: 'keyword', foreground: 'cba6f7' },
          { token: 'string', foreground: 'a6e3a1' },
          { token: 'number', foreground: 'fab387' },
          { token: 'type', foreground: '89dceb' },
          { token: 'function', foreground: '89b4fa' },
        ],
        colors: {
          'editor.background': '#1e1e2e', 'editor.foreground': '#cdd6f4',
          'editor.lineHighlightBackground': '#313244', 'editor.selectionBackground': '#45475a',
          'editorCursor.foreground': '#89dceb', 'editorLineNumber.foreground': '#585b70',
          'editorLineNumber.activeForeground': '#a6adc8',
        },
      })

      this.monacoReady = true

      if (this._editorContainer) {
        this._createEditor(this._editorContainer)
        if (this.activePath && this.models[this.activePath]) {
          this.editor.setModel(this.models[this.activePath])
        }
      }
    })
  }

  initTerminal() {
    if (typeof Terminal === 'undefined') return
    this.term = new Terminal({
      theme: { background: '#11111b', foreground: '#cdd6f4', cursor: '#89dceb', selectionBackground: 'rgba(137,220,235,.3)' },
      fontSize: 13, fontFamily: "'Cascadia Code',Consolas,monospace", cursorBlink: true,
    })
    this.fitAddon = new FitAddon.FitAddon()
    this.term.loadAddon(this.fitAddon)
    this.term.onData((d) => this.send({ type: 'terminal_input', data: d }))
    this.termReady = true
  }

  bindEvents() {
    document.getElementById('newFileBtn').onclick = () => this.newFile()
    document.getElementById('refreshTreeBtn').onclick = () => this.loadTree()
    document.getElementById('voiceBtn').onclick = (e) => { e.currentTarget.classList.toggle('active'); this.send({ type: 'voice_toggle', enabled: e.currentTarget.classList.contains('active') }) }
    document.getElementById('ilSubmit').onclick = () => this.submitInline()
    document.getElementById('ilCancel').onclick = () => this.cancelInline()
    document.getElementById('ilAccept').onclick = () => this.acceptInline()
    document.getElementById('ilReject').onclick = () => this.rejectInline()
    document.addEventListener('keydown', (e) => { if ((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();this.saveFile()} })

    if (this._editorElement) {
      const nf = this._editorElement.querySelector('#glNewFile')
      const of = this._editorElement.querySelector('#glOpenFiles')
      if (nf) nf.onclick = () => this.newFile()
      if (of) of.onclick = () => this.loadTree()
    }
  }

  loadTree() { this.send({ type: 'get_file_tree', path: '.' }) }

  renderTree(nodes) {
    this._lastFileTree = nodes
    const el = document.getElementById('glFileTree') || document.getElementById('fileTree')
    if (!el) {
      console.log('fileTree element not found, retrying in 100ms...')
      setTimeout(() => this.renderTree(nodes), 100)
      return
    }
    el.innerHTML = ''
    if (!nodes || !nodes.length) { el.innerHTML = '<div class="ft-loading">No files</div>'; return }
    nodes.forEach(n => this._renderNode(n, el, 0))
    console.log('File tree rendered with', nodes.length, 'nodes')
  }

  _renderNode(node, parent, depth) {
    const row = document.createElement('div')
    row.className = 'tree-row'
    row.style.paddingLeft = (depth * 20) + 'px'

    if (node.type === 'directory') {
      const isOpen = false
      row.innerHTML = '<span class="tree-twist'+(isOpen?' open':'')+'">\u25B6</span>'
              + '<span class="tree-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="'+(isOpen?'#cba6f7':'#89b4fa')+'" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg></span>'
              + '<span class="tree-name">' + this.esc(node.name) + '</span>'

      const kids = document.createElement('div')
      kids.className = 'tree-children'
      kids.style.display = 'none'

      let state = isOpen
      row.onclick = (e) => {
        e.stopPropagation()
        state = !state
        row.querySelector('.tree-twist').classList.toggle('open', state)
        kids.style.display = state ? '' : 'none'
        const svg = row.querySelector('.tree-icon svg')
        if (svg) svg.setAttribute('stroke', state ? '#cba6f7' : '#89b4fa')
      }

      parent.appendChild(row)
      parent.appendChild(kids)

      if (node.children) node.children.forEach(c => this._renderNode(c, kids, depth + 1))
    } else {
      const ext = node.name.split('.').pop().toLowerCase()
      const color = this.extMap[ext] || ''
      const iconHtml = color
        ? '<span class="tree-ext" style="background:'+color+'22;color:'+color+';border-color:'+color+'44">'+ext+'</span>'
        : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#6c7086" stroke-width="2"><path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>'

      row.innerHTML = '<span class="tree-twist"></span><span class="tree-icon">'+iconHtml+'</span><span class="tree-name">'+this.esc(node.name)+'</span>'
      row.onclick = (e) => { e.stopPropagation(); this.openFile(node.path); this.selectRow(row) }
      parent.appendChild(row)
    }
  }

  selectRow(row) {
    document.querySelectorAll('.tree-row.selected').forEach(r => r.classList.remove('selected'))
    row.classList.add('selected')
  }

  getLang(path) {
    const m = { py:'python',js:'javascript',ts:'typescript',tsx:'typescriptreact',jsx:'javascriptreact',
      html:'html',css:'css',json:'json',md:'markdown',yaml:'yaml',yml:'yaml',
      rs:'rust',go:'go',java:'java',c:'cpp',cpp:'cpp',h:'cpp',sh:'shellscript',
      bat:'shellscript',sql:'sql',toml:'ini',ini:'ini',dockerfile:'dockerfile' }
    return m[path.split('.').pop().toLowerCase()] || 'plaintext'
  }

  openFile(path) {
    if (this.models[path]) { this.activateTab(path); return }
    this.hideWelcome()
    this.send({ type: 'get_file', path })
  }

  openFile(path, content) {
    if (content !== undefined) {
      if (this.models[path]) return this.activateTab(path)
      const lang = this.getLang(path)
      const model = monaco.editor.createModel(content, lang)
      model.onDidChangeContent(() => {
        const t = this.tabs.find(t => t.path === path)
        if (t && !t.modified) { t.modified = true; this.renderTabs() }
      })
      this.models[path] = model
      this.files[path] = content
      this.tabs.push({ path, name: path.split(/[/\\]/).pop(), modified: false })
      this.activateTab(path)
      this.hideWelcome()
    }
  }

  activateTab(path) {
    this.activePath = path
    const m = this.models[path]
    if (m && this.editor) {
      this.editor.setModel(m)
    }
    this.renderTabs()

    document.querySelectorAll('.tree-row.selected').forEach(r => r.classList.remove('selected'))
    const name = path.split(/[/\\]/).pop()
    document.querySelectorAll('.tree-name').forEach(el => {
      if (el.textContent === name) {
        const row = el.closest('.tree-row')
        if (row) row.classList.add('selected')
      }
    })
  }

  renderTabs() {
    const bar = document.getElementById('glTabBar') || document.getElementById('tabBar')
    if (!bar) return
    bar.innerHTML = ''
    this.tabs.forEach(t => {
      const d = document.createElement('div')
      d.className = 'gl-tab' + (t.path===this.activePath?' active':'') + (t.modified?' modified':'')
      d.innerHTML = '<span class="tab-name">'+this.esc(t.name)+'</span><span class="tab-close">\u2715</span>'
      d.onclick = (e) => { if(e.target.classList.contains('tab-close')){this.closeTab(t.path)}else{this.activateTab(t.path)} }
      bar.appendChild(d)
    })
  }

  closeTab(path) {
    const i = this.tabs.findIndex(t=>t.path===path); if(i<0)return
    this.tabs.splice(i,1)
    this.models[path]?.dispose(); delete this.models[path]; delete this.files[path]
    if(this.activePath===path){
      if(this.tabs.length){const n=this.tabs[Math.min(i,this.tabs.length-1)];this.activateTab(n.path)}
      else{this.editor.setModel(null);this.activePath=null;this.showWelcome()}
    }
    this.renderTabs()
  }

  saveFile() {
    if(!this.activePath)return
    const c=this.models[this.activePath].getValue()
    this.send({type:'save_file',path:this.activePath,content:c})
    this.showStatus('Saved '+this.activePath)
  }

  onSaved(p){const t=this.tabs.find(t=>t.path===p);if(t){t.modified=false;this.renderTabs()}}
  onCreated(p){this.loadTree();this.openFile(p,'');this.showStatus('Created '+p)}

  newFile(){
    const n=prompt('File name:')
    if(!n)return;this.hideWelcome();this.openFile(n,'');this.send({type:'create_file',path:n,content:''})
  }

  showStatus(t){
    const s=document.getElementById('statusInfo');if(s){s.textContent=t;setTimeout(()=>{s.textContent=''},3000)}
  }

  hideWelcome(){const w=document.getElementById('welcomeScreen')||document.querySelector('#glEditorArea .gl-welcome');if(w)w.classList.add('hidden')}
  showWelcome(){const w=document.getElementById('welcomeScreen')||document.querySelector('#glEditorArea .gl-welcome');if(w)w.classList.remove('hidden')}

  sendChat(){
    const input=document.getElementById('glChatInput')||document.getElementById('chatInput')
    if(!input)return
    const text=input.value.trim()
    if(!text||!this.connected)return
    this.addMsg('user',text);input.value='';this.typing()
    this.send({type:'ai_chat',message:text,model:document.getElementById('modelSelect').value})
  }

  addMsg(role,text){
    const c=document.getElementById('glChatMsgs')||document.getElementById('chatMsgs')
    if(!c)return null
    const m=document.createElement('div')
    m.className='msg msg-'+role
    const b=document.createElement('div');b.className='msg-bubble'
    b.innerHTML=role==='ai'?this.md(text):this.esc(text)
    m.appendChild(b);c.appendChild(m);c.scrollTop=c.scrollHeight;return m
  }

  md(text){
    if(typeof marked==='undefined')return this.esc(text)
    const r=new marked.Renderer()
    r.code=(c,l)=>{
      let hl=c
      try{hl=typeof hljs!=='undefined'&&hl.getLanguage(l)?hl.highlight(c,{language:l}).value:this.esc(c)}catch{hl=this.esc(c)}
      return'<div class="code-blk"><div class="code-blk-hdr"><code>'+l+'</code><button class="code-blk-apply" data-code="'+this.esc(c.replace(/"/g,'&quot;'))+'">Apply</button></div><div class="code-blk-body"><pre><code>'+hl+'</code></pre></div></div>'
    }
    marked.setOptions({renderer:r,breaks:true,gfm:true})
    return marked.parse(text)
  }

  esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

  typing(){
    const c=document.getElementById('glChatMsgs')||document.getElementById('chatMsgs')
    if(!c)return
    const el=document.createElement('div')
    el.className='msg msg-ai';el.id='typing'
    el.innerHTML='<div class="msg-bubble typing"><span></span><span></span><span></span></div>'
    c.appendChild(el);c.scrollTop=c.scrollHeight
  }
  unTyping(){const el=document.getElementById('typing');if(el)el.remove()}

  _aiStream(tok){
    this.unTyping()
    if(!this.streamMsg)this.streamMsg=this.addMsg('ai','')
    this.streamText+=tok
    const bubble=this.streamMsg?.querySelector('.msg-bubble')
    if(bubble)bubble.innerHTML=this.md(this.streamText)
    this._bindApply(this.streamMsg)
    const c=document.getElementById('glChatMsgs')||document.getElementById('chatMsgs')
    if(c)c.scrollTop=c.scrollHeight
  }
  _aiDone(content){this.streamMsg=null;this.streamText='';this.unTyping()}
  _bindApply(el){if(!el)return;el.querySelectorAll('.code-blk-apply').forEach(b=>{b.onclick=()=>this.applyCode(b)})}
  applyCode(btn){
    const code=btn.dataset.code||btn.closest('.code-blk')?.querySelector('code')?.textContent
    if(code&&this.editor&&this.activePath){
      const p=this.editor.getPosition()
      this.editor.executeEdits('apply',[{range:new monaco.Range(p.lineNumber,p.column,p.lineNumber,p.column),text:'\n'+code+'\n'}])
      this.editor.focus()
    }
  }

  clearChat(){
    const c=document.getElementById('glChatMsgs')||document.getElementById('chatMsgs')
    if(c)c.innerHTML=''
  }

  _termOut(data){if(this.term)try{this.term.write(data)}catch{}}

  startInline(){
    if(!this.editor||!this.activePath)return
    const sel=this.editor.getSelection()
    const range=sel.isEmpty()?new monaco.Range(sel.startLineNumber,1,sel.startLineNumber,this.editor.getModel().getLineMaxColumn(sel.startLineNumber)):sel
    const orig=this.editor.getModel().getValueInRange(range)
    this.inlineEdit={active:true,range,original:orig,newCode:''}
    const ov=document.getElementById('inlineOverlay')
    ov.classList.remove('hidden')
    const er=this.editor.getDomNode().getBoundingClientRect()
    ov.style.top=Math.min(er.height/2,180)+'px';ov.style.left=(er.width/2-200)+'px'
    document.getElementById('ilInput').value=''
    document.getElementById('diffView').classList.add('hidden')
    document.getElementById('ilActions').classList.add('hidden')
    document.getElementById('ilInput').focus()
  }
  submitInline(){
    const inst=document.getElementById('ilInput').value.trim()
    if(!inst)return
    this.send({type:'inline_edit',instruction:inst,code:this.inlineEdit.original,path:this.activePath,
      range:{startLine:this.inlineEdit.range.startLineNumber,startCol:this.inlineEdit.range.startColumn,
             endLine:this.inlineEdit.range.endLineNumber,endCol:this.inlineEdit.range.endColumn}})
    document.getElementById('ilInput').value=''
  }
  _inlineResult(code,err){
    const dv=document.getElementById('diffView'),ac=document.getElementById('ilActions')
    const origLines=this.inlineEdit.original.split('\n'),newLines=(code||'').split('\n')
    let html=''
    const max=Math.max(origLines.length,newLines.length)
    for(let i=0;i<max;i++){
      const o=i<origLines.length?origLines[i]:undefined,n=i<newLines.length?newLines[i]:undefined
      if(n!==undefined&&(o===undefined||o!==n))html+='<div class="diff-add">+ '+this.esc(n)+'</div>'
      if(o!==undefined&&(n===undefined||o!==n))html+='<div class="diff-del">- '+this.esc(o)+'</div>'
      if(o!==undefined&&n!==undefined&&o===n)html+='<div class="diff-same">&nbsp; '+this.esc(o)+'</div>'
    }
    dv.innerHTML=html;dv.classList.remove('hidden');ac.classList.remove('hidden')
    this.inlineEdit.newCode=code
  }
  acceptInline(){
    if(this.inlineEdit.newCode!==undefined){
      this.editor.executeEdits('inline',[{range:this.inlineEdit.range,text:this.inlineEdit.newCode}])
    }
    this.cancelInline()
  }
  rejectInline(){this.cancelInline()}
  cancelInline(){
    this.inlineEdit={active:false,range:null,original:'',newCode:''}
    document.getElementById('inlineOverlay').classList.add('hidden')
  }

  _atMenu(e){
    const v=e.target.value,idx=v.lastIndexOf('@')
    if(idx>=0&&(idx===0||v[idx-1]===' ')){
      const q=v.substring(idx+1)
      const items=[{l:'@file - Reference a file',v:'@file '},{l:'@web - Search the web',v:'@web '}]
      const f=items.filter(i=>i.l.toLowerCase().includes(q.toLowerCase()))
      if(!f.length)return
      let menu=document.getElementById('glAtMenu')||document.getElementById('atMenu')
      if(!menu){
        menu=document.createElement('div')
        menu.id='glAtMenu'
        menu.style.cssText='position:fixed;z-index:200;background:#313244;border:1px solid #45475a;border-radius:6px;max-height:200px;overflow-y:auto;box-shadow:0 4px 12px rgba(0,0,0,.4);min-width:220px;'
        document.body.appendChild(menu)
      }
      menu.innerHTML=''
      f.forEach(item=>{
        const d=document.createElement('div')
        d.style.cssText='padding:6px 10px;font-size:12px;color:#cdd6f4;cursor:pointer;'
        d.textContent=item.l
        d.onmouseenter=()=>d.style.background='#45475a'
        d.onmouseleave=()=>d.style.background='transparent'
        d.onclick=()=>{
          const inp=document.getElementById('glChatInput')||document.getElementById('chatInput')
          inp.value=inp.value.substring(0,idx)+item.v;menu.classList.add('hidden');inp.focus()
        }
        menu.appendChild(d)
      })
      const rect=e.target.getBoundingClientRect()
      menu.style.top=(rect.bottom+4)+'px'
      menu.style.left=rect.left+'px'
      menu.classList.remove('hidden')
    }else{
      const menu=document.getElementById('glAtMenu')||document.getElementById('atMenu')
      if(menu)menu.classList.add('hidden')
    }
  }

  _settings(d){
    const s=document.getElementById('modelSelect')
    if(s&&d.models){s.innerHTML='';d.models.forEach(m=>{
      const o=document.createElement('option');o.value=m;o.textContent=m.charAt(0).toUpperCase()+m.slice(1)
      if(m===d.default_model)o.selected=true;s.appendChild(o)
    })}
  }

  _error(msg){this.unTyping();if(msg)this.addMsg('ai','**Error**: '+msg)}

  _taskUpdate(d){}
}

let app
document.addEventListener('DOMContentLoaded',()=>{app=new EditorApp()})
