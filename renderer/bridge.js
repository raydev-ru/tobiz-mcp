// Мост Python -> Node: читает один JSON-запрос из stdin, пишет один JSON-ответ в stdout.
//
// Запросы:
//   {"op":"meta","vendor_dir":"..."}                       -> {"ok":true,"types":[...]}
//   {"op":"render","vendor_dir":"...","items":[{...}]}     -> {"ok":true,"html":{block_id:html}}
//   {"op":"check","vendor_dir":"..."}                       -> {"ok":true,"checked":N,"failed":[...]}
//
// Диагностика — только в stderr, чтобы stdout оставался валидным JSON.
const fs = require('fs');
const path = require('path');
const { createRuntime } = require('./vendor-runtime');

function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.on('data', (c) => chunks.push(c));
    process.stdin.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    process.stdin.on('error', reject);
  });
}

function reply(payload) {
  process.stdout.write(JSON.stringify(payload));
}

(async () => {
  let request;
  try {
    request = JSON.parse(await readStdin());
  } catch (e) {
    reply({ ok: false, error: `не разобран запрос: ${e.message}` });
    process.exitCode = 1;
    return;
  }
  const vendorDir = request.vendor_dir;
  if (!vendorDir || !fs.existsSync(vendorDir)) {
    reply({ ok: false, error: `каталог сборки не найден: ${vendorDir}` });
    process.exitCode = 1;
    return;
  }
  let runtime;
  try {
    runtime = createRuntime(vendorDir, { quiet: true });
  } catch (e) {
    reply({ ok: false, error: `не удалось поднять рантайм вендора: ${e.message}` });
    process.exitCode = 1;
    return;
  }

  try {
    if (request.op === 'meta') {
      const types = runtime.blocks.map((b) => ({
        type_id: String(b.type_id),
        values: b.values || {},
        settings: b.settings || [],
        vars: b.vars || [],
        has_template: typeof b.template === 'string' && b.template.length > 0,
        template_bytes: (b.template || '').length,
      }));
      reply({ ok: true, types, count: types.length });
      return;
    }

    if (request.op === 'render' || request.op === 'check') {
      const html = {};
      const failed = [];
      for (const item of request.items || []) {
        try {
          html[String(item.block_id)] = runtime.render(item.type_id, item.values, item.block_id);
        } catch (e) {
          failed.push({
            block_id: String(item.block_id),
            type_id: String(item.type_id),
            error: String(e.message || e),
            code: e.code || 'RENDER_FAILED',
          });
        }
      }
      if (request.op === 'check') {
        reply({ ok: failed.length === 0, checked: (request.items || []).length, failed });
        return;
      }
      reply({
        ok: failed.length === 0,
        html,
        failed,
        rendered: Object.keys(html).length,
      });
      if (failed.length) process.exitCode = 0; // ошибки блоков передаются в JSON, а не кодом
      return;
    }

    reply({ ok: false, error: `неизвестная операция: ${request.op}` });
    process.exitCode = 1;
  } catch (e) {
    reply({ ok: false, error: String(e.message || e) });
    process.exitCode = 1;
  }
})();
