/**
 * SCAI 助理後端（Cloudflare Worker + Workers AI）
 *
 * 模型：@cf/openai/gpt-oss-20b —— OpenAI 官方開放權重模型（OpenAI 系列），
 *       符合競賽「OpenAI／Anthropic／Google 三大系列」限制；
 *       Workers AI 每日 10,000 Neurons 免費額度內即可運作，零成本產生真實 token 數據。
 *       ※ Llama／Qwen／Mistral 等非三大系列模型不得使用（同否決 Perplexity Sonar 之理由）。
 *
 * 設計約束（對應網站「治理」頁）：
 * - 模型與 system prompt 固定在本檔，前端不可指定。
 * - 問題長度上限 300 字、輸出上限 512 tokens。
 * - CORS 白名單鎖定 SCAI 網站來源。
 * - 不記錄問答內容（無任何儲存呼叫）；回應附 token 用量供網站顯示。
 * - 每 IP 每分鐘 8 次（單一 isolate 內盡力而為；免費額度用罄時 Workers AI 直接回錯，
 *   前端自動降級為展示模式）。
 *
 * 日後切換 Claude（經費到位後）：把 MODEL 換成 AI Gateway Unified Billing 的
 * Anthropic 端點呼叫即可，前端零改動——見 README-部署.md 第 6 節。
 */

const MODEL = "@cf/openai/gpt-oss-20b";

const ALLOWED_ORIGINS = [
  "https://sakaban-code.github.io",   // GitHub Pages 正式站
  "http://localhost:8765",            // 本機驗證用
];

const MAX_Q = 300;          // 問題字數上限
const MAX_OUT = 512;        // 輸出 token 上限
const RATE = { limit: 8, windowMs: 60_000 };   // 每 IP 每分鐘

const SYSTEM = [
  "你是 SCAI-Agent 網站的助理。SCAI-Agent 是每週產出的半導體戰略情報系統：",
  "以 X 軸（地緣與供應鏈聚合，-1 碎裂到 +1 聚合）與 Y 軸（資源與政策充沛，-1 匱乏到 +1 充沛）",
  "判定四情境（Spring/Crossroads/Adaptation/Inferno），校準 25 項關鍵決策因素（KDF，中性 50），",
  "並依企業畫像觸發劇本。",
  "回答規則：一律繁體中文；依提供的當週脈絡回答，不捏造脈絡外的數字；",
  "超出脈絡的問題明說「本週資料未涵蓋」；不提供投資建議；回答精簡（150 字內為佳）。",
].join("");

// 單一 isolate 內的簡易限流（重啟即歸零；正式強化可換 KV/Durable Objects）
const hits = new Map();
function rateLimited(ip) {
  const now = Date.now();
  const rec = hits.get(ip) || { n: 0, t: now };
  if (now - rec.t > RATE.windowMs) { rec.n = 0; rec.t = now; }
  rec.n += 1;
  hits.set(ip, rec);
  if (hits.size > 2000) hits.clear();   // 防脹
  return rec.n > RATE.limit;
}

function cors(origin) {
  const ok = ALLOWED_ORIGINS.includes(origin);
  return {
    "access-control-allow-origin": ok ? origin : ALLOWED_ORIGINS[0],
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "content-type",
    "access-control-max-age": "86400",
  };
}

const json = (obj, status, extra) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...extra },
  });

export default {
  async fetch(request, env) {
    const origin = request.headers.get("origin") || "";
    const ch = cors(origin);

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: ch });
    if (request.method !== "POST") return json({ error: "POST only" }, 405, ch);
    if (!ALLOWED_ORIGINS.includes(origin)) return json({ error: "origin not allowed" }, 403, ch);

    const ip = request.headers.get("cf-connecting-ip") || "?";
    if (rateLimited(ip)) return json({ error: "rate limited，請稍候再試" }, 429, ch);

    let body;
    try { body = await request.json(); } catch { return json({ error: "bad json" }, 400, ch); }

    const q = String(body.question || "").slice(0, MAX_Q).trim();
    if (!q) return json({ error: "empty question" }, 400, ch);

    // 前端傳入的當週脈絡（皆為網站上公開的資料，非機密）
    const ctx = [
      `本週 W${body.week}（${body.range}）`,
      `情境 ${body.scenario}，X=${body.x}、Y=${body.y}`,
      `目前檢視企業：${body.company}`,
      `該企業本週觸發劇本：${(Array.isArray(body.fired) && body.fired.length) ? body.fired.join("；") : "無"}`,
    ].join("\n");

    const prompt = `${SYSTEM}\n\n[當週脈絡]\n${ctx}\n\n[使用者問題]\n${q}`;

    let r;
    try {
      // gpt-oss 於 Workers AI 採 Responses 風格輸入；若平台 schema 變動，退回 messages 格式
      try {
        r = await env.AI.run(MODEL, { input: prompt, max_output_tokens: MAX_OUT });
      } catch {
        r = await env.AI.run(MODEL, {
          messages: [
            { role: "system", content: SYSTEM },
            { role: "user", content: `[當週脈絡]\n${ctx}\n\n${q}` },
          ],
          max_tokens: MAX_OUT,
        });
      }
    } catch (e) {
      // 免費額度用罄（每日 10,000 Neurons，00:00 UTC 重置）或模型錯誤
      return json({ error: "ai unavailable: " + String(e).slice(0, 100) }, 503, ch);
    }

    // 各格式防禦性取值
    let answer =
      r?.output_text ??
      r?.response ??
      (Array.isArray(r?.output)
        ? r.output.flatMap(o => o?.content || []).map(c => c?.text || "").join("")
        : "") ??
      "";
    if (!answer) answer = "（模型未回傳內容）";

    const u = r?.usage || {};
    return json({
      answer,
      model: MODEL,
      usage: {
        input_tokens: u.prompt_tokens ?? u.input_tokens ?? null,
        output_tokens: u.completion_tokens ?? u.output_tokens ?? null,
      },
    }, 200, ch);
  },
};
