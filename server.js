import { createServer } from "node:http";
import { createReadStream } from "node:fs";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, "public");
const TMP_DIR = path.join(__dirname, "tmp");
const JOBS_DIR = path.join(TMP_DIR, "jobs");
const PORT = Number(process.env.PORT || 3025);
const MAX_UPLOAD_BYTES = 80 * 1024 * 1024;
const MAX_OUTPUT_TOKENS = Number(process.env.AI_MAX_OUTPUT_TOKENS || 32768);
const DEFAULT_MODEL = "gemini-3.1-flash-lite";

await loadLocalEnv();
await mkdir(JOBS_DIR, { recursive: true });

createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

    if ((req.method === "GET" || req.method === "HEAD") && url.pathname === "/") {
      await sendFile(res, path.join(PUBLIC_DIR, "index.html"), "text/html; charset=utf-8", req.method === "HEAD");
      return;
    }

    if ((req.method === "GET" || req.method === "HEAD") && url.pathname === "/health") {
      if (req.method === "HEAD") {
        res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
        return res.end();
      }
      return sendJson(res, 200, { ok: true });
    }

    if (req.method === "POST" && url.pathname === "/api/convert") {
      await handleConvert(req, res);
      return;
    }

    const downloadMatch = url.pathname.match(/^\/download\/([a-f0-9-]+)$/i);
    if (req.method === "GET" && downloadMatch) {
      await handleDownload(res, downloadMatch[1]);
      return;
    }

    sendJson(res, 404, { error: "페이지를 찾을 수 없습니다." });
  } catch (error) {
    if (!res.headersSent) sendJson(res, error.statusCode || 500, { error: publicError(error) });
    else res.destroy();
  }
}).listen(PORT, () => {
  console.log(`pdf2hwpx-clean listening on http://localhost:${PORT}`);
});

async function handleConvert(req, res) {
  const contentType = req.headers["content-type"] || "";
  if (!contentType.includes("multipart/form-data")) {
    return sendJson(res, 400, { error: "PDF 파일을 업로드해 주세요." });
  }
  const contentLength = Number(req.headers["content-length"] || 0);
  if (contentLength > MAX_UPLOAD_BYTES) {
    return sendJson(res, 413, { error: uploadLimitMessage() });
  }

  const body = await readRequestBody(req, MAX_UPLOAD_BYTES);
  const { fields, files } = parseMultipart(body, contentType);
  const pdf = files.file;
  if (!pdf || pdf.data.length === 0) {
    return sendJson(res, 400, { error: "PDF 파일을 선택해 주세요." });
  }
  if (!pdf.contentType.includes("pdf") && !pdf.filename.toLowerCase().endsWith(".pdf")) {
    return sendJson(res, 400, { error: "PDF 파일만 업로드할 수 있습니다." });
  }

  const apiKey = getSecret("AI_API_KEY");
  if (!apiKey) {
    return sendJson(res, 500, { error: "AI API 키를 찾지 못했습니다. 배포 환경변수를 확인해 주세요." });
  }

  const model = getSecret("AI_MODEL") || DEFAULT_MODEL;
  const options = {
    school: cleanField(fields.school, "학교 시험지"),
    grade: cleanField(fields.grade, "1"),
    range: cleanField(fields.range, "중1 수학"),
  };

  const jobId = crypto.randomUUID();
  const jobDir = path.join(JOBS_DIR, jobId);
  await mkdir(jobDir, { recursive: true });

  const payload = await analyzePdf({ apiKey, model, pdfBuffer: pdf.data, filename: pdf.filename, options });
  const normalized = normalizePayload(payload, options);
  const dataPath = path.join(jobDir, "exam.json");
  const outPath = path.join(jobDir, "result.hwpx");
  await writeFile(dataPath, JSON.stringify(normalized, null, 2), "utf8");
  await buildHwpx(dataPath, outPath);

  sendJson(res, 200, {
    jobId,
    downloadUrl: `/download/${jobId}`,
    problemCount: normalized.problems.length,
    problems: normalized.problems.map((problem) => ({
      number: problem.number,
      topic: problem.topic,
      answer: problem.answer,
    })),
  });
}

async function analyzePdf({ apiKey, model, pdfBuffer, filename, options }) {
  const pageCount = estimatePdfPageCount(pdfBuffer);
  if (pageCount >= 3) {
    const rangedPayload = await analyzePdfByPageRanges({ apiKey, model, pdfBuffer, filename, options, pageCount });
    const rangedCount = Array.isArray(rangedPayload?.problems) ? rangedPayload.problems.length : 0;
    if (rangedCount > 5) return rangedPayload;
  }

  const prompt = buildAnalysisPrompt({ filename, options });
  const text = await requestAiJson({
    apiKey,
    model,
    parts: [
      {
        inline_data: {
          mime_type: "application/pdf",
          data: pdfBuffer.toString("base64"),
        },
      },
      { text: prompt },
    ],
  });

  let payload = await parseOrRepairAiJson({ apiKey, model, text });
  const problemCount = Array.isArray(payload?.problems) ? payload.problems.length : 0;
  if (problemCount > 0 && problemCount <= 5) {
    const retryText = await requestAiJson({
      apiKey,
      model,
      parts: [
        {
          inline_data: {
            mime_type: "application/pdf",
            data: pdfBuffer.toString("base64"),
          },
        },
        {
          text: [
            "앞선 응답이 5문항 이하라서 누락 가능성이 큽니다.",
            "PDF의 모든 페이지를 다시 확인하고, 번호가 붙은 수학 문항을 처음부터 끝까지 전부 추출하세요.",
            "문항 일부만 반환하지 말고 전체 시험지를 대상으로 JSON 객체 하나만 반환하세요.",
            "마크다운, 코드블록, 설명문은 쓰지 마세요.",
            "",
            `파일명: ${filename}`,
            `학년: 중${options.grade}`,
            `범위: ${options.range}`,
            "",
            "반환 형식은 이전 스키마와 동일합니다.",
          ].join("\n"),
        },
      ],
    });
    const retryPayload = await parseOrRepairAiJson({ apiKey, model, text: retryText });
    const retryCount = Array.isArray(retryPayload?.problems) ? retryPayload.problems.length : 0;
    if (retryCount > problemCount) payload = retryPayload;
  }

  return payload;
}

async function analyzePdfByPageRanges({ apiKey, model, pdfBuffer, filename, options, pageCount }) {
  const chunks = [];
  for (let start = 1; start <= pageCount; start += 2) {
    chunks.push({ start, end: Math.min(start + 1, pageCount) });
  }

  const payloads = [];
  for (const range of chunks) {
    const prompt = buildAnalysisPrompt({ filename, options, pageCount, pageRange: range });
    const text = await requestAiJson({
      apiKey,
      model,
      parts: [
        {
          inline_data: {
            mime_type: "application/pdf",
            data: pdfBuffer.toString("base64"),
          },
        },
        { text: prompt },
      ],
    });
    const payload = await parseOrRepairAiJson({ apiKey, model, text });
    payloads.push(payload);
  }

  return mergeProblemPayloads(payloads, options);
}

function buildAnalysisPrompt({ filename, options, pageCount = 0, pageRange = null }) {
  const scope = pageRange
    ? [
        `이번 요청은 전체 ${pageCount}쪽 PDF 중 ${pageRange.start}쪽부터 ${pageRange.end}쪽까지의 문항만 추출합니다.`,
        "다른 페이지의 문항은 넣지 마세요.",
        "문항 번호는 PDF에 보이는 원래 번호를 유지하세요.",
        "한 문항이 페이지 경계에 걸쳐 있으면 이 구간에서 보이는 내용을 최대한 포함하세요.",
      ]
    : [
        "PDF의 첫 페이지부터 마지막 페이지까지 모든 페이지를 확인하세요.",
        "수학 문항을 일부만 요약하지 말고 번호 순서대로 전부 추출하세요.",
        "학교 시험지는 보통 20문항 이상일 수 있습니다. 5문항만 반환하고 멈추지 마세요.",
      ];

  return [
    "중학교 수학 시험지 PDF를 읽고 HWPX 변환용 JSON만 반환하세요.",
    ...scope,
    "수학 문항마다 정답과 짧은 해설을 작성하세요.",
    "마크다운, 코드블록, 설명문 없이 JSON 객체만 반환하세요.",
    "",
    `파일명: ${filename}`,
    `학년: 중${options.grade}`,
    `범위: ${options.range}`,
    "",
    "스키마:",
    JSON.stringify({
      title: "string",
      problems: [
        {
          number: 1,
          topic: "유형 또는 단원",
          difficulty: "하|중|상",
          parts: [{ t: "문제 텍스트" }, { eq: "x^2+3x+2" }],
          choices: [[{ t: "보기" }], [{ eq: "2^3" }]],
          answer: "③",
          explanation_parts: [{ t: "짧은 해설" }, { br: true }, { eq: "x=2" }],
        },
      ],
    }),
    "",
    "규칙:",
    "- 수식은 가능한 한 {\"eq\":\"...\"} 조각으로 분리하세요.",
    "- eq에는 $ 기호를 넣지 마세요.",
    "- 객관식 보기는 choices에 넣고, 보기가 없으면 choices는 빈 배열로 두세요.",
    "- 해설은 짧게 작성하세요.",
    "- 모든 배열 요소와 객체 속성 사이에 쉼표를 넣은 엄격한 JSON 문법을 지키세요.",
  ].join("\n");
}

function parseAiJson(text) {
  const cleaned = text
    .trim()
    .replace(/^```(?:json)?/i, "")
    .replace(/```$/i, "")
    .trim();
  const first = cleaned.indexOf("{");
  const last = cleaned.lastIndexOf("}");
  const jsonText = first >= 0 && last >= first ? cleaned.slice(first, last + 1) : cleaned;
  const direct = tryParseJson(jsonText);
  if (direct.ok) return direct;

  for (const candidate of repairJsonCandidates(jsonText)) {
    const repaired = tryParseJson(candidate);
    if (repaired.ok) return repaired;
  }

  return { ok: false, error: direct.error };
}

async function requestAiJson({ apiKey, model, parts }) {
  const response = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": apiKey,
      },
      body: JSON.stringify({
        contents: [
          {
            role: "user",
            parts,
          },
        ],
        generationConfig: {
          temperature: 0,
          responseMimeType: "application/json",
          maxOutputTokens: MAX_OUTPUT_TOKENS,
        },
      }),
    }
  );

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message = body?.error?.message || `AI API 요청 실패 (${response.status})`;
    throw new Error(message);
  }

  const text = body?.candidates?.[0]?.content?.parts
    ?.map((part) => part.text)
    .filter(Boolean)
    .join("\n")
    .trim();
  if (!text) throw new Error("AI 응답을 읽지 못했습니다.");
  return text;
}

async function parseOrRepairAiJson({ apiKey, model, text }) {
  const parsed = parseAiJson(text);
  if (parsed.ok) return parsed.value;

  const repairedText = await requestAiJson({
    apiKey,
    model,
    parts: [
      {
        text: [
          "아래 텍스트는 JSON 파싱에 실패했습니다.",
          "내용을 추가하거나 삭제하지 말고, 문법만 고쳐서 유효한 JSON 객체 하나만 반환하세요.",
          "마크다운, 코드블록, 설명문은 쓰지 마세요.",
          "",
          `파싱 오류: ${parsed.error}`,
          "",
          "고칠 JSON:",
          text.slice(0, 80000),
        ].join("\n"),
      },
    ],
  });
  const repaired = parseAiJson(repairedText);
  if (repaired.ok) return repaired.value;

  throw new Error("AI 응답 형식을 정리하지 못했습니다. 같은 PDF로 한 번 더 시도하거나 PDF를 더 작은 범위로 나눠 주세요.");
}

function tryParseJson(text) {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "JSON 파싱 실패" };
  }
}

function repairJsonCandidates(text) {
  const normalized = text
    .replace(/\r\n/g, "\n")
    .replace(/,\s*([}\]])/g, "$1");

  return [
    normalized,
    normalized.replace(/}\s*\n\s*{/g, "},\n{"),
    normalized.replace(/]\s*\n\s*{/g, "],\n{").replace(/}\s*\n\s*"/g, '},\n"'),
  ];
}

function estimatePdfPageCount(pdfBuffer) {
  const text = pdfBuffer.toString("latin1");
  const count = (text.match(/\/Type\s*\/Page\b/g) || []).length;
  return count > 0 && count < 500 ? count : 0;
}

function mergeProblemPayloads(payloads, options) {
  const merged = [];
  const seen = new Map();
  let title = "";

  for (const payload of payloads) {
    if (!title && typeof payload?.title === "string") title = payload.title;
    const problems = Array.isArray(payload?.problems) ? payload.problems : [];
    for (const problem of problems) {
      const normalized = {
        ...problem,
        parts: normalizeParts(problem?.parts || problem?.question || ""),
        choices: normalizeChoices(problem?.choices),
        explanation_parts: normalizeParts(problem?.explanation_parts || problem?.explanation || ""),
      };
      const key = problemMergeKey(normalized);
      const prevIndex = seen.get(key);
      if (prevIndex === undefined) {
        seen.set(key, merged.length);
        merged.push(normalized);
      } else if (problemTextLength(normalized) > problemTextLength(merged[prevIndex])) {
        merged[prevIndex] = normalized;
      }
    }
  }

  merged.sort((a, b) => {
    const an = Number(a.number);
    const bn = Number(b.number);
    if (Number.isFinite(an) && Number.isFinite(bn) && an !== bn) return an - bn;
    return problemTextValue(a).localeCompare(problemTextValue(b), "ko");
  });

  return {
    title: title || `${options.school} ${options.range}`,
    problems: merged,
  };
}

function problemMergeKey(problem) {
  const number = Number(problem?.number);
  const textKey = problemTextValue(problem).replace(/\s+/g, "").slice(0, 80);
  if (Number.isFinite(number) && number > 0) return `n:${number}:${textKey}`;
  return `t:${textKey}`;
}

function problemTextLength(problem) {
  return problemTextValue(problem).length;
}

function problemTextValue(problem) {
  return [
    problem?.topic || "",
    partsToPlainText(problem?.parts || []),
    (problem?.choices || []).map((choice) => partsToPlainText(choice)).join(" "),
  ].join(" ");
}

function partsToPlainText(parts) {
  return normalizeParts(parts)
    .map((part) => part.eq || part.t || "")
    .join(" ");
}

function normalizePayload(payload, options) {
  const problems = Array.isArray(payload?.problems) ? payload.problems : [];
  if (problems.length === 0) throw new Error("문항을 찾지 못했습니다.");

  return {
    title: payload.title || `${options.school} ${options.range}`,
    info: options,
    problems: problems.map((problem, index) => ({
      number: Number(problem.number) || index + 1,
      topic: textValue(problem.topic || problem.subtopic || "미분류"),
      difficulty: textValue(problem.difficulty || "중"),
      parts: normalizeParts(problem.parts || problem.question || ""),
      choices: normalizeChoices(problem.choices),
      answer: textValue(problem.answer || ""),
      explanation_parts: normalizeParts(problem.explanation_parts || problem.explanation || "해설을 확인하세요."),
    })),
  };
}

function normalizeChoices(value) {
  if (!Array.isArray(value)) return [];
  return value.map((choice) => normalizeParts(choice).filter((part) => !part.br));
}

function normalizeParts(value) {
  if (typeof value === "string") return splitTextAndMath(value);
  if (!Array.isArray(value)) return [{ t: textValue(value) }];

  const parts = [];
  for (const part of value) {
    if (!part || typeof part !== "object") continue;
    if (part.br === true) parts.push({ br: true });
    else if (typeof part.eq === "string") parts.push({ eq: part.eq });
    else if (typeof part.math === "string") parts.push({ eq: part.math });
    else if (typeof part.t === "string") parts.push(...splitTextAndMath(part.t));
    else if (typeof part.text === "string") parts.push(...splitTextAndMath(part.text));
  }
  return parts.length > 0 ? parts : [{ t: "" }];
}

function splitTextAndMath(text) {
  const source = textValue(text);
  const parts = [];
  const pattern = /\$([^$]+)\$/g;
  let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    if (match.index > cursor) parts.push({ t: source.slice(cursor, match.index) });
    parts.push({ eq: match[1] });
    cursor = match.index + match[0].length;
  }
  if (cursor < source.length) parts.push({ t: source.slice(cursor) });
  return parts.length > 0 ? parts : [{ t: source }];
}

async function buildHwpx(dataPath, outPath) {
  const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  await new Promise((resolve, reject) => {
    const child = spawn(python, ["scripts/generate_hwpx.py", dataPath, outPath], {
      cwd: __dirname,
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(stderr.trim() || "HWPX 생성에 실패했습니다."));
    });
  });
}

async function handleDownload(res, jobId) {
  const safeId = jobId.replace(/[^a-f0-9-]/gi, "");
  const filePath = path.join(JOBS_DIR, safeId, "result.hwpx");
  try {
    const info = await stat(filePath);
    res.writeHead(200, {
      "Content-Type": "application/octet-stream",
      "Content-Length": info.size,
      "Content-Disposition": "attachment; filename*=UTF-8''%EC%8B%9C%ED%97%98%EC%A7%80_%ED%92%80%EC%9D%B4%ED%95%B4%EC%84%A4.hwpx",
    });
    createReadStream(filePath).pipe(res);
  } catch {
    sendJson(res, 404, { error: "파일을 찾을 수 없습니다." });
  }
}

async function sendFile(res, filePath, contentType, headOnly = false) {
  const info = await stat(filePath);
  res.writeHead(200, { "Content-Type": contentType, "Content-Length": info.size });
  if (headOnly) return res.end();
  createReadStream(filePath).pipe(res);
}

function sendJson(res, statusCode, body) {
  const bytes = Buffer.from(JSON.stringify(body), "utf8");
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": bytes.length,
  });
  res.end(bytes);
}

async function readRequestBody(req, limit) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > limit) {
      const error = new Error(uploadLimitMessage());
      error.statusCode = 413;
      throw error;
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function uploadLimitMessage() {
  return `${Math.floor(MAX_UPLOAD_BYTES / 1024 / 1024)}MB 이하 PDF만 업로드할 수 있습니다.`;
}

function parseMultipart(buffer, contentType) {
  const boundary = contentType.match(/boundary=(?:"([^"]+)"|([^;]+))/)?.[1] || contentType.match(/boundary=(?:"([^"]+)"|([^;]+))/)?.[2];
  if (!boundary) throw new Error("업로드 형식을 읽지 못했습니다.");

  const fields = {};
  const files = {};
  const rawParts = buffer.toString("latin1").split(`--${boundary}`).slice(1, -1);
  for (let rawPart of rawParts) {
    if (rawPart.startsWith("\r\n")) rawPart = rawPart.slice(2);
    if (rawPart.endsWith("\r\n")) rawPart = rawPart.slice(0, -2);
    const splitAt = rawPart.indexOf("\r\n\r\n");
    if (splitAt < 0) continue;
    const headerText = rawPart.slice(0, splitAt);
    const content = Buffer.from(rawPart.slice(splitAt + 4), "latin1");
    const disposition = headerText.match(/content-disposition:\s*([^\r\n]+)/i)?.[1] || "";
    const name = disposition.match(/name="([^"]+)"/)?.[1];
    if (!name) continue;
    const filename = disposition.match(/filename="([^"]*)"/)?.[1];
    const contentType = headerText.match(/content-type:\s*([^\r\n]+)/i)?.[1] || "";
    if (filename !== undefined) {
      files[name] = { filename: path.basename(filename) || "upload.pdf", contentType, data: content };
    } else {
      fields[name] = content.toString("utf8").trim();
    }
  }
  return { fields, files };
}

async function loadLocalEnv() {
  for (const name of [".env.local", ".env"]) {
    try {
      const text = await readFile(path.join(__dirname, name), "utf8");
      for (const line of text.split(/\r?\n/)) {
        const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
        if (!match) continue;
        const key = match[1];
        const value = match[2].replace(/^['"]|['"]$/g, "").trim();
        if (value && !process.env[key]) process.env[key] = value;
      }
    } catch {
      // Local env files are optional and are not committed.
    }
  }
}

function getSecret(name) {
  const value = process.env[name];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function cleanField(value, fallback) {
  const text = textValue(value).trim();
  return text.length > 0 ? text.slice(0, 80) : fallback;
}

function textValue(value) {
  return value === undefined || value === null ? "" : String(value);
}

function publicError(error) {
  const message = error instanceof Error ? error.message : "변환에 실패했습니다.";
  return message
    .replace(/Gemini/gi, "AI")
    .replace(/gemini-[A-Za-z0-9_.-]+/gi, "AI 모델");
}
