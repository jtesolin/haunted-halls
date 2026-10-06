import { createServer } from "node:http";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createMockResponse, E2E_OPENAI_KEY, UnsupportedRequestError } from "./responses.ts";

const MAX_BODY_BYTES = 1_048_576;

export function createMockServer() {
  return createServer(async (request, response) => {
    response.setHeader("Content-Type", "application/json");
    if (request.method === "GET" && request.url === "/health") {
      response.end(JSON.stringify({ status: "ok" }));
      return;
    }
    if (request.method !== "POST" || request.url !== "/v1/responses") {
      response.writeHead(404).end(JSON.stringify({ error: { message: "Unsupported endpoint" } }));
      return;
    }
    if (request.headers.authorization !== `Bearer ${E2E_OPENAI_KEY}`) {
      console.error("OpenAI E2E mock rejected a non-test credential");
      response.writeHead(401).end(JSON.stringify({ error: { message: "Only the fake E2E key is accepted" } }));
      return;
    }
    try {
      const chunks: Buffer[] = [];
      let size = 0;
      for await (const chunk of request) {
        const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
        size += buffer.length;
        if (size > MAX_BODY_BYTES) {
          throw new UnsupportedRequestError("Request body exceeds E2E limit");
        }
        chunks.push(buffer);
      }
      const payload: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const result = createMockResponse(payload);
      console.info("OpenAI E2E mock served a Responses request");
      response.end(JSON.stringify(result));
    } catch (error) {
      const expected = error instanceof UnsupportedRequestError || error instanceof SyntaxError;
      const message = expected ? error.message : "Unexpected mock provider failure";
      console.error(`OpenAI E2E mock rejected request: ${message}`);
      response.writeHead(expected ? 400 : 500).end(JSON.stringify({
        error: { message, type: "invalid_request_error", code: "unsupported_e2e_request" },
      }));
    }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  createMockServer().listen(8080, "0.0.0.0", () => {
    console.info("OpenAI E2E mock listening on port 8080; no external provider forwarding");
  });
}
