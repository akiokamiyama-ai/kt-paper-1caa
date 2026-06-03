// C57 (Sprint 9, 2026-06-03): Anthropic Messages API の薄い fetch ラッパー.
//
// C37 と同じ「依存ゼロ・fetch 直叩き」設計。SDK を入れないことで Vercel
// の cold start を最小化しつつ、Edge 移植余地も残す。
//
// 使い方:
//   const { text, input_tokens, output_tokens, cost_usd } =
//     await callAnthropic({ system, messages, model, max_tokens, temperature });

const DEFAULT_MODEL = 'claude-sonnet-4-6';
const DEFAULT_MAX_TOKENS = 2000;
const DEFAULT_TEMPERATURE = 0.7;
const API_URL = 'https://api.anthropic.com/v1/messages';
const API_VERSION = '2023-06-01';

// Pricing per 1M tokens (Sonnet 4.6 standard tier). Cache pricing not used here.
const PRICE_INPUT_PER_MILLION = 3.0;
const PRICE_OUTPUT_PER_MILLION = 15.0;

function _getKey() {
  const k = process.env.TRIBUNE_ANTHROPIC_API_KEY;
  if (!k || typeof k !== 'string' || !k.startsWith('sk-')) {
    throw new Error('TRIBUNE_ANTHROPIC_API_KEY env var missing or invalid');
  }
  return k;
}

function estimateCost(input_tokens, output_tokens) {
  const inUsd = (input_tokens / 1e6) * PRICE_INPUT_PER_MILLION;
  const outUsd = (output_tokens / 1e6) * PRICE_OUTPUT_PER_MILLION;
  return Math.round((inUsd + outUsd) * 1e6) / 1e6; // 6 桁
}

async function callAnthropic({
  system,
  messages,
  model = DEFAULT_MODEL,
  max_tokens = DEFAULT_MAX_TOKENS,
  temperature = DEFAULT_TEMPERATURE,
  tag = 'comment.ai_draft',
} = {}) {
  if (!Array.isArray(messages) || messages.length === 0) {
    throw new Error('messages must be a non-empty array');
  }
  const body = {
    model,
    max_tokens,
    temperature,
    messages,
  };
  if (system) body.system = system;

  const res = await fetch(API_URL, {
    method: 'POST',
    headers: {
      'x-api-key': _getKey(),
      'anthropic-version': API_VERSION,
      'content-type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const txt = await res.text();
    const e = new Error(`Anthropic API ${res.status}: ${txt.slice(0, 300)}`);
    e.status = res.status;
    throw e;
  }

  const data = await res.json();
  const text = Array.isArray(data.content)
    ? data.content.map((c) => (c.type === 'text' ? c.text : '')).join('').trim()
    : '';
  const in_tok = (data.usage && data.usage.input_tokens) || 0;
  const out_tok = (data.usage && data.usage.output_tokens) || 0;
  const cost_usd = estimateCost(in_tok, out_tok);

  // Vercel console に構造化 cost ログ（Phase A llm_usage 形式に寄せる）。
  console.log(JSON.stringify({
    event: 'llm_call',
    tag,
    model,
    input_tokens: in_tok,
    output_tokens: out_tok,
    cost_usd,
    stop_reason: data.stop_reason || null,
  }));

  return {
    text,
    input_tokens: in_tok,
    output_tokens: out_tok,
    cost_usd,
    stop_reason: data.stop_reason || null,
  };
}

module.exports = {
  callAnthropic,
  estimateCost,
  DEFAULT_MODEL,
  DEFAULT_MAX_TOKENS,
  DEFAULT_TEMPERATURE,
};
