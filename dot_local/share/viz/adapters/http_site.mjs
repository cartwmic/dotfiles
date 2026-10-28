// Site port over HTTP: PUT each file to $VIZ_PUBLISH_URL/<path> with basic auth
// (user viz, password $VIZ_PUBLISH_PASSWORD). The server is a plain static site
// that accepts authenticated PUTs (nginx with dav_methods PUT, for example).
import { VizError } from '../core/domain.mjs';

const USER = 'viz';

export function createSite(env) {
  const config = () => {
    const base = (env.VIZ_PUBLISH_URL || '').replace(/\/+$/, '');
    if (!base) throw new VizError('missing_dependency', 'VIZ_PUBLISH_URL is not set (the site viz publish uploads to)');
    if (!/^https?:\/\/[^/]/.test(base)) throw new VizError('bad_input', `VIZ_PUBLISH_URL must be an http(s) URL, got ${JSON.stringify(base)}`);
    if (!env.VIZ_PUBLISH_PASSWORD) throw new VizError('missing_dependency', 'VIZ_PUBLISH_PASSWORD is not set (the upload password for the site)');
    return { base, auth: `Basic ${Buffer.from(`${USER}:${env.VIZ_PUBLISH_PASSWORD}`).toString('base64')}` };
  };
  return {
    locate() { return config().base; },

    async put(path, bytes, contentType) {
      const { base, auth } = config();
      const url = `${base}/${path}`;
      let res;
      try {
        res = await fetch(url, { method: 'PUT', headers: { authorization: auth, 'content-type': contentType }, body: bytes });
      } catch (e) {
        const cause = e && e.cause ? e.cause.code || e.cause.message : null;
        throw new VizError('publish_failed', `PUT ${url} failed: ${cause || (e && e.message) || e}`);
      }
      await res.arrayBuffer().catch(() => {});
      if (!res.ok) {
        const hint = res.status === 401 ? ' (wrong VIZ_PUBLISH_PASSWORD?)' : '';
        throw new VizError('publish_failed', `PUT ${url} returned ${res.status} ${res.statusText}${hint}`);
      }
      return res.status;
    },
  };
}
