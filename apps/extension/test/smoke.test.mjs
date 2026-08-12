/**
 * 冒烟测试：在 jsdom 中模拟浏览器环境，验证 extract.js 核心链路：
 *   Readability 提取正文 → Turndown 转 Markdown → chrome.runtime.sendMessage 回传
 * 运行：node test/smoke.test.mjs
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { JSDOM } from 'jsdom';
import { strict as assert } from 'node:assert';

const read = (p) => readFileSync(new URL('../' + p, import.meta.url), 'utf8');

/** 模拟一次"popup 点击 → 注入依赖库与提取脚本"的完整过程 */
function runExtract(html, url) {
  const dom = new JSDOM(html, { url, contentType: 'text/html', runScripts: 'outside-only' });
  const context = dom.getInternalVMContext();
  const messages = [];
  dom.window.chrome = { runtime: { sendMessage: (m) => messages.push(m) } };
  // 按 manifest 中 executeScript 的 files 顺序注入（重构后为构建产物）
  vm.runInContext(read('lib/Readability.js'), context);
  vm.runInContext(read('lib/turndown.js'), context);
  vm.runInContext(read('dist/content.js'), context);
  const msg = messages.find((m) => m.type === 'MD_RESULT');
  return msg ? msg.result : null;
}

// ── 用例 1：典型文章页 → 提取正文、去噪音、链接绝对化 ──
const articleHtml = `<!DOCTYPE html><html><head>
<title>深夜写代码的人</title>
<meta name="author" content="张三">
</head><body>
<nav><a href="/nav1">导航一</a><a href="/nav2">导航二</a></nav>
<article>
<h1>深夜写代码的人</h1>
<p>第一段：白天属于别人，夜晚属于自己。</p>
<p>第二段：点击<a href="/about">这里</a>了解更多，配图：<img src="/img/x.png" alt="深夜的屏幕"></p>
<pre><code>const night = true;</code></pre>
<p>第三段：凌晨三点的城市，只有路灯还醒着。</p>
</article>
<footer>广告：点击购买课程 联系客服</footer>
</body></html>`;

const r1 = runExtract(articleHtml, 'https://blog.example.com/post/deep-night');
assert.ok(r1 && r1.ok === true, '用例1：转换应成功');
assert.equal(r1.title, '深夜写代码的人', '用例1：标题应为文章标题');
assert.equal(r1.fallback, false, '用例1：应为正文提取而非降级');
assert.ok(!r1.md.includes('导航'), '用例1：导航噪音应被过滤');
assert.ok(!r1.md.includes('点击购买课程'), '用例1：广告噪音应被过滤');
assert.ok(r1.md.includes('https://blog.example.com/about'), '用例1：相对链接应绝对化');
assert.ok(r1.md.includes('https://blog.example.com/img/x.png'), '用例1：相对图片应绝对化');
assert.ok(/#+\s*深夜写代码的人/.test(r1.md), '用例1：标题应转成 Markdown 标题');
assert.ok(r1.md.includes('```'), '用例1：代码块应转成 fenced');
assert.ok(r1.charCount > 0 && r1.paragraphs >= 1, '用例1：应有字数与段落统计');
console.log('用例 1 通过：正常文章页 提取+转换+绝对化+去噪音');

// ── 用例 2：无正文页 → 自动链路不再整页降级（V2：整页改手动）──
const noArticleHtml = `<!DOCTYPE html><html><head><title>纯空白页</title></head>
<body></body></html>`;
const r2 = runExtract(noArticleHtml, 'https://paywall.example.com/login');
assert.ok(r2, '用例2：应有结果');
assert.equal(r2.ok, false, '用例2：无正文页自动链路应失败（不再自动整页降级）');
assert.ok(r2.error && /正文内容/.test(r2.error), '用例2：应给出可读失败原因');
console.log('用例 2 通过：无正文页自动链路失败并提示（整页转换需手动触发）');

// ── 用例 2b：完全空文档 → 可读失败原因 ──
const r2b = runExtract('<!DOCTYPE html><html><head></head><body></body></html>', 'https://x.example/empty');
assert.ok(r2b, '用例2b：应有结果');
assert.equal(r2b.ok, false, '用例2b：完全空文档转换应失败');
assert.ok(r2b.error && /正文内容/.test(r2b.error), '用例2b：应给出可读的失败原因');
console.log('用例 2b 通过：完全空文档给出可读失败原因');

// ── 用例 3：依赖缺失 → 明确报错而非崩溃 ──
const dom3 = new JSDOM('<html><body><p>hi</p></body></html>', {
  url: 'https://x.example/',
  runScripts: 'outside-only',
});
const context3 = dom3.getInternalVMContext();
const messages3 = [];
dom3.window.chrome = { runtime: { sendMessage: (m) => messages3.push(m) } };
vm.runInContext(read('dist/content.js'), context3); // 故意不注入依赖库
const msg3 = messages3.find((m) => m.type === 'MD_RESULT');
assert.ok(msg3 && msg3.result.ok === false, '用例3：缺依赖时应返回失败结果');
assert.ok(/依赖库/.test(msg3.result.error), '用例3：失败原因应可读');
console.log('用例 3 通过：依赖缺失时明确报错（dist/content.js 无全局库注入）');

console.log('\n全部冒烟测试通过 ✓');
