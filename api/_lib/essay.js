// C57 (Sprint 9, 2026-06-03): archive/YYYY-MM-DD.html から論考本文を抽出する.
//
// v3 swap 適用日（Phase 3 案 C）: <article class="essay-section"> の
// .essay-body に <p>...</p> が並ぶ。
// v2 通常日（編集後記なし or Page I 通常）: <article class="front-top"> の
// .lead-story / .body-3col。
//
// 戻り値は LLM に渡すための plain text。HTML タグを除去し、改行で段落分け。
// 出力は 3000 字に truncate（context 圧縮）。

const TAG_RE = /<[^>]+>/g;
const WHITESPACE_RE = /\s+/g;
const PARAGRAPH_TAG_RE = /<\/p>\s*<p[^>]*>/gi;
const ENTITY_MAP = {
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#x27;': "'",
  '&#x2f;': '/',
  '&nbsp;': ' ',
};

const MAX_ESSAY_CHARS = 3000;

function _decodeEntities(text) {
  return text.replace(/&(amp|lt|gt|quot|#x27|#x2f|nbsp);/gi, (m) => {
    return ENTITY_MAP[m.toLowerCase()] || m;
  });
}

function _stripHtml(html) {
  // <p>...</p><p>...</p> 境界を改行に変換してから tag を全削除。
  return html
    .replace(PARAGRAPH_TAG_RE, '\n\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(TAG_RE, '')
    .replace(WHITESPACE_RE, ' ')
    .replace(/[ \t]*\n[ \t]*/g, '\n')
    .trim();
}

function _truncate(text, max) {
  if (text.length <= max) return text;
  // 段落区切りで切る
  const cut = text.slice(0, max);
  const lastBreak = cut.lastIndexOf('\n\n');
  if (lastBreak > max * 0.6) return cut.slice(0, lastBreak) + '\n\n[…以下省略]';
  // 句点で切る
  const lastPeriod = Math.max(cut.lastIndexOf('。'), cut.lastIndexOf('.'));
  if (lastPeriod > max * 0.7) return cut.slice(0, lastPeriod + 1) + ' […以下省略]';
  return cut + '…';
}

function _findBlock(html, openMarker, openTag = '<article') {
  // openMarker を含む <article ...> から始まる本文を返す。タグの開始位置は
  // <article まで遡って取得。終端は </article>。
  const idx = html.indexOf(openMarker);
  if (idx < 0) return null;
  let start = html.lastIndexOf(openTag, idx);
  if (start < 0) start = idx;
  const closeTag = openTag === '<article' ? '</article>' : '</section>';
  const end = html.indexOf(closeTag, idx);
  if (end < 0) return null;
  return html.slice(start, end + closeTag.length);
}

/**
 * Extract page-one essay text from archive HTML.
 * Tries v3 (essay-section) first, falls back to v2 (front-top) lead story.
 * Returns { source: 'v3' | 'v2' | 'none', text: string, title: string }
 */
function extractEssay(html) {
  if (!html || typeof html !== 'string') {
    return { source: 'none', text: '', title: '' };
  }

  // v3 essay-section
  const v3Block = _findBlock(html, 'class="essay-section"');
  if (v3Block) {
    const bodyMatch = v3Block.match(/<div\s+class="essay-body[^"]*">([\s\S]*?)<\/div>/i);
    const titleMatch = v3Block.match(/<h2\s+class="essay-tier3[^"]*"[^>]*>([\s\S]*?)<\/h2>/i);
    const questionMatch = v3Block.match(/<h1\s+class="essay-tier2[^"]*"[^>]*>([\s\S]*?)<\/h1>/i);
    if (bodyMatch) {
      const title = titleMatch ? _decodeEntities(_stripHtml(titleMatch[1])) : '';
      const question = questionMatch ? _decodeEntities(_stripHtml(questionMatch[1])) : '';
      let text = _decodeEntities(_stripHtml(bodyMatch[1]));
      if (question) text = `【今日の問い】${question}\n\n${text}`;
      return {
        source: 'v3',
        text: _truncate(text, MAX_ESSAY_CHARS),
        title,
      };
    }
  }

  // v2 front-top lead-story
  const v2Block = _findBlock(html, 'class="front-top"');
  if (v2Block) {
    const bodyMatch = v2Block.match(/<div\s+class="body-3col[^"]*">([\s\S]*?)<\/div>/i)
      || v2Block.match(/<div\s+class="lead-story[^"]*">([\s\S]*?)<\/div>/i);
    const titleMatch = v2Block.match(/<h2\s+class="headline-xl[^"]*"[^>]*>([\s\S]*?)<\/h2>/i);
    if (bodyMatch) {
      const title = titleMatch ? _decodeEntities(_stripHtml(titleMatch[1])) : '';
      const text = _decodeEntities(_stripHtml(bodyMatch[1]));
      return {
        source: 'v2',
        text: _truncate(text, MAX_ESSAY_CHARS),
        title,
      };
    }
  }

  return { source: 'none', text: '', title: '' };
}

/**
 * Extract editorial postscript (編集後記) body for additional context.
 * Returns string or empty.
 */
function extractEditorial(html) {
  if (!html || typeof html !== 'string') return '';
  const idx = html.indexOf('class="editorial-footer"');
  if (idx < 0) return '';
  const bodyStart = html.indexOf('<div class="body">', idx);
  if (bodyStart < 0) return '';
  const bodyEnd = html.indexOf('</div>', bodyStart);
  if (bodyEnd < 0) return '';
  const block = html.slice(bodyStart, bodyEnd);
  return _decodeEntities(_stripHtml(block)).slice(0, 1000);
}

module.exports = {
  extractEssay,
  extractEditorial,
  MAX_ESSAY_CHARS,
};
