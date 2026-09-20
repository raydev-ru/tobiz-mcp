// Рантайм рендера блоков: воспроизводит то, что делает редактор TOBIZ перед отправкой
// SaveBlocks. Проверено побайтовым совпадением с настоящим `cache` (docs/spikes/S-5-render.md).
//
// Из чего состоит совпадение (любой пропущенный пункт даёт расхождение):
//   1. underscore 1.8.3 — файл вендора /js/underscore-min.js, а не свежая версия;
//   2. шаблоны блоков из /js/blocks2.js (tobiz.blocks[].template);
//   3. хелперы вендора — объект из _.mixin({...}) в editor.min.js, целиком;
//   4. глобалы замыкания редактора: A (= window.tobiz) и I (= window.tobiz.isValidValue);
//   5. методы приложения вида A.ParseVKVideoLink (в бандле объявлены через локальные алиасы);
//   6. DOM-раундтрип через jsdom: prepend(<span class="block_anchor">) + data-id/id + outerHTML;
//   7. цепочка строковых замен, ровно в том порядке, что в обработчике «Сохранить».
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { JSDOM } = require('jsdom');

const BUNDLES = [
  'editor.min.js',
  'editor.bundle.min.js',
  'flex_tools.min.js',
  'script.min.js',
];

// --- 1. объект _.mixin({...}) из editor.min.js ---
function findMixinObject(src) {
  const start = src.indexOf('_.mixin({');
  if (start < 0) throw new Error('_.mixin не найден в editor.min.js (изменилась сборка вендора)');
  const open = start + '_.mixin('.length;
  let i = open;
  let depth = 0;
  let prevToken = '';
  while (i < src.length) {
    const c = src[i];
    if (c === '"' || c === "'" || c === '`') {
      const quote = c;
      i++;
      while (i < src.length && src[i] !== quote) {
        if (src[i] === '\\') i++;
        i++;
      }
      prevToken = 'str';
      i++;
      continue;
    }
    if (c === '/' && src[i + 1] === '/') { while (i < src.length && src[i] !== '\n') i++; continue; }
    if (c === '/' && src[i + 1] === '*') { i = src.indexOf('*/', i) + 2; continue; }
    if (c === '/' && /[=(,:[!&|?{};+\-*%<>~^]|return|typeof|case/.test(prevToken || '=')) {
      i++;
      let inClass = false;
      while (i < src.length) {
        const d = src[i];
        if (d === '\\') { i += 2; continue; }
        if (d === '[') inClass = true;
        else if (d === ']') inClass = false;
        else if (d === '/' && !inClass) break;
        else if (d === '\n') break;
        i++;
      }
      i++;
      prevToken = 'regex';
      continue;
    }
    if (c === '{' || c === '(' || c === '[') depth++;
    if (c === '}' || c === ')' || c === ']') {
      depth--;
      if (depth === 0) return src.slice(open, i + 1);
    }
    if (!/\s/.test(c)) prevToken = c;
    i++;
  }
  throw new Error('не найден конец объекта _.mixin');
}

// --- 2. методы приложения: App.X / window.tobiz.X / <алиас>.X для нужных имён ---
function extractAppMethods(sources, neededNames) {
  const combined = sources.join('\n');
  const out = new Map();
  if (!neededNames || !neededNames.length) return out;
  const pattern = new RegExp(
    `(?:[A-Za-z_$][A-Za-z0-9_$]*\\.)(${neededNames.join('|')})\\s*=\\s*function\\s*\\(`, 'g');
  let match;
  while ((match = pattern.exec(combined))) {
    const name = match[1];
    if (out.has(name)) continue;
    const fnIndex = combined.lastIndexOf('function', match.index + match[0].length);
    if (fnIndex < 0) continue;
    const parenIndex = combined.indexOf('(', fnIndex + 8);
    let i = parenIndex;
    let depth = 0;
    for (; i < combined.length; i++) {
      const c = combined[i];
      if (c === '(') depth++;
      else if (c === ')') { depth--; if (depth === 0) break; }
      else if (c === '"' || c === "'" || c === '`') {
        const quote = c; i++;
        while (i < combined.length && combined[i] !== quote) { if (combined[i] === '\\') i++; i++; }
      }
    }
    const braceIndex = combined.indexOf('{', i);
    if (braceIndex < 0) continue;
    let j = braceIndex;
    let braces = 0;
    for (; j < combined.length; j++) {
      const c = combined[j];
      if (c === '{') braces++;
      else if (c === '}') { braces--; if (braces === 0) break; }
      else if (c === '"' || c === "'" || c === '`') {
        const quote = c; j++;
        while (j < combined.length && combined[j] !== quote) { if (combined[j] === '\\') j++; j++; }
      }
    }
    out.set(name, `function${combined.slice(combined.lastIndexOf('function', parenIndex) + 8, j + 1)}`);
  }
  return out;
}

// --- 3. цепочка замен обработчика «Сохранить» ---
const REPLACEMENTS = [
  [/\u00A0/g, ' '], ['&nbsp;', ' '], [';;', ';'], ['; "', '"'], ['background-color:;', ''],
  ['style=""', ''], ['alt=""', ''], ['data=""', ''], ['="undefined"', ''], [' class=""', ''],
  ['> <', '><'], ['data-bind_grid="1"', ''], ['data-bind_grid="0"', ''],
  ['data-bind_wrapper="1"', ''], ['data-bind_wrapper="0"', ''],
  ['data-bind_obj="1"', ''], ['data-bind_obj="0"', ''],
];

// --- 4. заглушки DOM/jQuery: нужны только чтобы код вендора инициализировался ---
const stubNode = new Proxy({}, { get: () => () => stubNode });
const $stub = () => stubNode;
$stub.ajax = () => $stub;
$stub.each = (collection, callback) => {
  if (Array.isArray(collection)) collection.forEach((value, index) => callback(value, index));
  return $stub;
};
$stub.parseHTML = (html) => [new JSDOM(`<body>${html}</body>`).window.document.body.firstElementChild];

function createRuntime(vendorDir, options = {}) {
  const quiet = options.quiet !== false;
  const read = (name) => fs.readFileSync(path.join(vendorDir, name), 'utf8');
  const sandbox = {
    console: quiet ? { log() {}, error() {}, warn() {}, info() {} } : console,
    window: { location: { hash: '', search: '', href: 'https://example.invalid/' }, tobiz: {} },
    document: {
      createElement: () => stubNode,
      getElementById: () => null,
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: () => {},
      cookie: '',
    },
    navigator: { userAgent: 'node' },
    localStorage: { getItem: () => null, setItem: () => {} },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
  };
  sandbox.window.document = sandbox.document;
  sandbox.tobiz = sandbox.window.tobiz;
  sandbox.$ = $stub;
  sandbox.jQuery = $stub;
  sandbox.A = sandbox.window.tobiz;                       // A = window.tobiz в редакторе
  sandbox.I = (v) => v !== null && v !== undefined && v !== '' && v !== 0; // App.isValidValue
  vm.createContext(sandbox);

  vm.runInContext(read('underscore-min.js'), sandbox, { filename: 'underscore-min.js' });
  const underscore = sandbox._;
  if (!underscore) throw new Error('underscore не загрузился');

  const editorSrc = read('editor.min.js');
  const blocksSrc = read('blocks2.js');
  const mixin = findMixinObject(editorSrc);
  vm.runInContext(`_;_.mixin(${mixin});`, sandbox, { filename: 'vendor-mixin.js' });

  const bundleSources = BUNDLES
    .map((name) => path.join(vendorDir, name))
    .filter((file) => fs.existsSync(file))
    .map((file) => fs.readFileSync(file, 'utf8'));
  const needed = new Set();
  for (const source of [blocksSrc, mixin, ...bundleSources]) {
    for (const match of source.matchAll(/\bA\.([A-Za-z_$][A-Za-z0-9_$]*)\s*\(/g)) needed.add(match[1]);
  }
  const appMethods = extractAppMethods(bundleSources, [...needed]);
  for (const [name, body] of appMethods) {
    try {
      vm.runInContext(`window.tobiz[${JSON.stringify(name)}] = ${body};`, sandbox);
    } catch (e) {
      if (!quiet) process.stderr.write(`[vendor] App.${name}: ${e.message}\n`);
    }
  }
  sandbox.A = sandbox.window.tobiz;

  vm.runInContext(blocksSrc, sandbox, { filename: 'blocks2.js' });
  const blocks = sandbox.tobiz.blocks || [];
  const byType = new Map(blocks.map((b) => [Number(b.type_id), b]));

  function render(typeId, values, blockId) {
    const block = byType.get(Number(typeId));
    if (!block) {
      const error = new Error(`тип блока ${typeId} отсутствует в сборке проекта`);
      error.code = 'TEMPLATE_UNAVAILABLE';
      throw error;
    }
    const merged = Object.assign({}, block.values, values || {});
    const body = underscore.template(block.template)(merged);
    const dom = new JSDOM(`<body>${body}</body>`);
    const doc = dom.window.document;
    const root = doc.body.firstElementChild;
    if (!root) throw new Error(`шаблон ${typeId} вернул пустой HTML`);
    const anchorId = merged.anchor || `a_${blockId}`;
    const span = doc.createElement('span');
    span.setAttribute('id', anchorId);
    span.setAttribute('class', 'block_anchor');
    root.prepend(span);
    root.setAttribute('data-id', String(blockId));
    root.setAttribute('id', `b_${blockId}`);
    let html = root.outerHTML;
    for (const [from, to] of REPLACEMENTS) html = html.replaceAll(from, to);
    return html;
  }

  return { underscore, blocks, byType, render, appMethods: [...appMethods.keys()] };
}

module.exports = { createRuntime, findMixinObject, extractAppMethods, REPLACEMENTS };
