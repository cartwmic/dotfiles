// shartifacts port: the REST routes the server already serves. Anything but a 2xx answer is a request_failed.
import { ShxError } from '../core/domain.mjs';

const TIMEOUT_MS = 30000;

async function request(method, url, body) {
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body === undefined ? {} : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (e) {
    throw new ShxError('request_failed', `${method} ${url} failed: ${e.cause ? e.cause.message || e.cause : e.message}`);
  }
  if (!res.ok) throw new ShxError('request_failed', `${method} ${url} answered ${res.status}`);
  try {
    return await res.json();
  } catch {
    throw new ShxError('request_failed', `${method} ${url} did not answer with JSON`);
  }
}

const artifactUrl = (base, artifact) => `${base}/api/artifacts/${encodeURIComponent(artifact)}`;

export const api = {
  comments: (base, artifact) => request('GET', `${artifactUrl(base, artifact)}/comments`),
  artifact: (base, artifact) => request('GET', artifactUrl(base, artifact)),
  postMatches: (base, artifact, body) => request('POST', `${artifactUrl(base, artifact)}/comments/matches`, body),
};
