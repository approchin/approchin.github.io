(() => {
  const byId = id => document.getElementById(id);
  const story = byId('note-story');
  if (!story) return;

  for (const math of story.querySelectorAll('span.arithmatex')) {
    const match = math.textContent.match(/^\\\(([\s\S]*)\\\)$/);
    if (match) math.dataset.noteTex = match[1];
  }
  if (typeof renderMathInElement === 'function') {
    renderMathInElement(story, {
      delimiters: [{left: '\\[', right: '\\]', display: true}, {left: '\\(', right: '\\)', display: false}],
      throwOnError: false,
    });
  }

  const source = JSON.parse(byId('note-editor-data').textContent);
  const records = [...story.querySelectorAll(':scope > [data-edit-part]')];
  if (!records.length || !/^[0-9a-f]{40}$/.test(source.sha)) return;
  const toggle = byId('note-edit-toggle');
  const bar = byId('note-edit-bar');
  const notice = byId('note-edit-notice');
  const publish = byId('note-edit-publish');
  const dialog = byId('note-publish-dialog');
  const tokenField = byId('note-token');
  const submit = byId('note-token-submit');
  const returnToEdit = byId('note-token-cancel');
  const message = byId('note-publish-message');
  const articlePath = '/repos/approchin/approchin.github.io/contents/ardy-notes.md';
  const nodeEntries = new WeakMap();
  let focused;
  let editing = false;
  let submitting = false;
  let accessToken = '';
  let dialogMode = 'unlock';

  function entry(group, node, text, saved) {
    const item = {group, node, text, html: node.innerHTML, saved};
    nodeEntries.set(node, item);
    return item;
  }

  const groups = records.map(node => {
    const index = Number(node.dataset.editPart);
    const group = {index, entries: []};
    group.entries.push(entry(group, node, source.parts[index], true));
    return group;
  });
  const entries = () => groups.flatMap(group => group.entries);
  const changed = () => entries().some(item => item.node.innerHTML !== item.html);
  const activeEntry = target => nodeEntries.get(target.closest('[contenteditable="true"]'));
  const updateButton = () => { publish.disabled = submitting || !changed(); };

  function show(node, text) {
    node.textContent = text;
    node.hidden = !text;
  }

  function setEditing(active) {
    editing = active;
    bar.hidden = !active;
    story.classList.toggle('note-editing', active);
    toggle.setAttribute('aria-expanded', String(active));
    toggle.textContent = active ? '结束编辑' : '编辑本文';
    for (const item of entries()) {
      item.node.hidden = !active && !item.text.trim();
      if (active) item.node.contentEditable = 'true';
      else item.node.removeAttribute('contenteditable');
    }
    updateButton();
  }

  function leave() {
    if (changed() && !window.confirm('放弃这次未发布的修改？')) return;
    for (const group of groups) {
      for (const item of group.entries) {
        if (!item.saved) item.node.remove();
        else if (item.node.innerHTML !== item.html) item.node.innerHTML = item.html;
      }
      group.entries = group.entries.filter(item => item.saved);
    }
    focused = undefined;
    accessToken = '';
    setEditing(false);
    show(notice, '');
    toggle.focus({preventScroll: true});
  }

  function insert(after) {
    const paragraph = document.createElement('p');
    paragraph.className = 'note-new-paragraph';
    paragraph.contentEditable = 'true';
    after.node.after(paragraph);
    const item = entry(after.group, paragraph, '', false);
    after.group.entries.splice(after.group.entries.indexOf(after) + 1, 0, item);
    paragraph.focus();
    focused = item;
  }

  for (const math of story.querySelectorAll('[data-note-tex]')) {
    math.contentEditable = 'false';
  }
  for (const item of entries()) item.html = item.node.innerHTML;

  toggle.addEventListener('click', () => {
    if (editing) { leave(); return; }
    openDialog('unlock');
  });
  byId('note-edit-exit').addEventListener('click', leave);
  byId('note-edit-insert').addEventListener('click', () => insert(focused ?? groups[0].entries[0]));
  story.addEventListener('focusin', event => {
    if (editing) focused = activeEntry(event.target) ?? focused;
  });
  story.addEventListener('input', event => {
    if (editing) focused = activeEntry(event.target) ?? focused;
    updateButton();
  });
  story.addEventListener('click', event => {
    const item = editing && activeEntry(event.target);
    if (!item) return;
    focused = item;
    if (event.target.closest('a')) event.preventDefault();
  });
  story.addEventListener('drop', event => {
    if (editing && activeEntry(event.target)) event.preventDefault();
  });
  story.addEventListener('beforeinput', event => {
    const item = editing && activeEntry(event.target);
    if (!item || event.isComposing) return;
    if (event.inputType === 'insertParagraph') {
      event.preventDefault();
      insert(item);
    }
    if (event.inputType === 'insertLineBreak' && item.node.tagName !== 'P') event.preventDefault();
  });
  story.addEventListener('paste', event => {
    const item = editing && activeEntry(event.target);
    if (!item) return;
    event.preventDefault();
    const selection = window.getSelection();
    if (!selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!item.node.contains(range.commonAncestorContainer)) return;
    const text = event.clipboardData.getData('text/plain').replace(/\r\n?/g, '\n');
    const lines = item.node.tagName === 'P' ? text.split('\n') : [text.replaceAll('\n', ' ')];
    const content = document.createDocumentFragment();
    lines.forEach((line, index) => {
      if (index) content.append(document.createElement('br'));
      content.append(document.createTextNode(line));
    });
    const last = content.lastChild;
    range.deleteContents();
    range.insertNode(content);
    range.setStartAfter(last);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    updateButton();
  });

  function escaped(text) {
    return text.replace(/\u00a0/g, ' ')
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('{', '&#123;').replaceAll('}', '&#125;')
      .replace(/[\\`*_~\[\]$]/g, '\\$&');
  }

  function markdown(node) {
    if (node.nodeType === Node.TEXT_NODE) return escaped(node.nodeValue);
    if (node.nodeType !== Node.ELEMENT_NODE) return '';
    if ('noteTex' in node.dataset) return '$' + node.dataset.noteTex + '$';
    const text = [...node.childNodes].map(markdown).join('');
    if (node.tagName === 'BR') return '  \n';
    if (node.tagName === 'CODE') {
      const code = node.textContent.replaceAll('\n', ' ');
      const size = Math.max(0, ...[...code.matchAll(/`+/g)].map(run => run[0].length)) + 1;
      const mark = '`'.repeat(size);
      const pad = code.startsWith('`') || code.endsWith('`') ? ' ' : '';
      return mark + pad + code + pad + mark;
    }
    if (node.tagName === 'A') {
      const destination = node.getAttribute('href');
      if (!destination || !['https:', 'http:', 'mailto:'].includes(new URL(destination, window.location.href).protocol)) return text;
      const url = destination.replace(/^\.\.\/\.\.\/assets\//, 'assets/').replace(/[<>\s]/g, encodeURIComponent);
      const title = node.getAttribute('title');
      return '[' + text + '](<' + url + '>' + (title ? ' "' + title.replace(/["\\]/g, '\\$&') + '"' : '') + ')';
    }
    const marker = {B: '**', STRONG: '**', I: '*', EM: '*'}[node.tagName];
    if (!marker || !text.trim()) return text;
    return text.replace(/^(\s*)([\s\S]*?)(\s*)$/, `$1${marker}$2${marker}$3`);
  }

  function sourceText(item) {
    const {node, html, text} = item;
    if (node.innerHTML === html) return text;
    const value = markdown(node).trim();
    if (node.tagName === 'P') {
      const paragraph = value.replace(/^(\s*)(#{1,6}|[-+]|\d+[.)])(?=\s)/gm,
        (_, indent, mark) => indent + mark.slice(0, -1) + '\\' + mark.slice(-1));
      return paragraph + (text.endsWith('\n') ? '\n' : '');
    }
    if (!value) throw new Error('请给小标题保留文字。');
    const heading = text.match(/^(#{2,6}[ \t]+)(.*?)([ \t]+\{[^{}\n]+\})?(\r?\n)?$/);
    const prefix = heading ? heading[1] : '#'.repeat(Number(node.tagName[1])) + ' ';
    return prefix + value + (heading?.[3] ?? '') + (heading?.[4] ?? '');
  }

  function draft() {
    const parts = [...source.parts];
    const written = [];
    for (const group of groups) {
      const values = group.entries.map(sourceText);
      for (let index = 0; index < values.length; index++) written.push([group.entries[index], values[index]]);
      parts[group.index] = values.length === 1 ? values[0] : values.filter(text => text.trim()).map(text => text.trimEnd()).join('\n\n') + (parts[group.index].endsWith('\n') ? '\n' : '');
    }
    return {text: parts.join(''), written};
  }

  function base64(text) {
    const bytes = new TextEncoder().encode(text);
    let raw = '';
    for (let at = 0; at < bytes.length; at += 8192) raw += String.fromCharCode(...bytes.subarray(at, at + 8192));
    return btoa(raw);
  }

  async function github(token, path, options = {}) {
    const response = await fetch('https://api.github.com' + path, {
      ...options, redirect: 'error', credentials: 'omit', cache: 'no-store',
      signal: AbortSignal.timeout(15000),
      headers: {Accept: 'application/vnd.github+json', Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
    });
    if (response.ok) return response.json();
    const details = {
      401: 'GitHub 拒绝了这枚令牌。请确认令牌有效。',
      403: '请确认令牌选中了本站仓库，并有 Contents 读写权限。',
      404: '请确认令牌选中了本站仓库，并有 Contents 读写权限。',
      409: '源稿发生了变化。你的草稿留在本页，可以先复制再合并。',
      422: 'GitHub 未接受提交。请核对源稿版本。',
    };
    throw Object.assign(new Error(details[response.status] ?? '暂时无法访问 GitHub。请稍后重试。'), {status: response.status});
  }

  async function checkVersion(token) {
    const latest = await github(token, articlePath + '?ref=main');
    if (latest.sha !== source.sha) {
      throw new Error(editing ? '源稿已有更新。你的草稿留在本页，可以先复制再合并。' : '当前页面的源稿较旧，请刷新后再编辑。');
    }
    return latest.sha;
  }

  async function saveToGitHub(token, text) {
    const latestSha = await checkVersion(token);
    const saved = await github(token, articlePath, {
      method: 'PUT',
      body: JSON.stringify({message: 'Update ARDY technical note', content: base64(text), branch: 'main', sha: latestSha}),
    });
    return saved.content.sha;
  }

  function setDialogMode(mode) {
    dialogMode = mode;
    const unlock = mode === 'unlock';
    byId('note-publish-title').textContent = unlock ? '解锁编辑' : '发布到网站';
    byId('note-token-entry').hidden = !unlock;
    tokenField.required = unlock;
    tokenField.disabled = !unlock;
    submit.textContent = unlock ? '进入编辑' : '发布';
    tokenField.value = '';
  }

  function openDialog(mode) {
    setDialogMode(mode);
    show(message, '');
    dialog.showModal();
    (mode === 'unlock' ? tokenField : submit).focus();
  }

  publish.addEventListener('click', () => openDialog(accessToken ? 'publish' : 'unlock'));
  returnToEdit.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { tokenField.value = ''; });
  dialog.addEventListener('cancel', event => { if (submitting) event.preventDefault(); });
  byId('note-publish-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting) return;
    const unlock = dialogMode === 'unlock';
    const token = unlock ? tokenField.value.trim() : accessToken;
    tokenField.value = '';
    if (!token.startsWith('github_pat_')) {
      show(message, '请填写 GitHub 细粒度访问令牌。');
      tokenField.focus();
      return;
    }
    submitting = true;
    submit.disabled = returnToEdit.disabled = tokenField.disabled = true;
    show(message, unlock ? '正在核对 GitHub 账号…' : '正在提交到 GitHub…');
    try {
      if (unlock) {
        const user = await github(token, '/user');
        if (user.login?.toLowerCase() !== 'approchin') throw new Error('请使用 approchin 账号签发的令牌。');
        await checkVersion(token);
        accessToken = token;
        dialog.close();
        show(notice, '');
        setEditing(true);
        return;
      }
      const article = draft();
      source.sha = await saveToGitHub(token, article.text);
      for (const [item, text] of article.written) Object.assign(item, {text, html: item.node.innerHTML, saved: true});
      dialog.close();
      show(notice, '已提交到 GitHub。站点构建完成后，访客会看到新版。');
      notice.scrollIntoView({block: 'nearest'});
    } catch (error) {
      if (!unlock && [401, 403, 404].includes(error.status)) {
        accessToken = '';
        setDialogMode('unlock');
        show(message, error.message + ' 草稿留在本页。');
      } else {
        const networkError = error instanceof TypeError || error.name === 'TimeoutError';
        show(message, networkError ? '连接 GitHub 失败。草稿留在本页。' : error.message);
      }
    } finally {
      submitting = false;
      returnToEdit.disabled = false;
      submit.disabled = false;
      tokenField.disabled = dialogMode !== 'unlock';
      if (!tokenField.disabled && dialog.open) tokenField.focus();
      updateButton();
    }
  });

  byId('note-source-link').hidden = true;
  toggle.hidden = false;
  window.addEventListener('beforeunload', event => {
    if (editing && changed()) event.preventDefault();
  });
  window.addEventListener('pagehide', () => { accessToken = ''; });
})();
