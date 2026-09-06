// The origin is operator-controlled. Never proxy to a hostname supplied by a browser.
async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const origin = process.env.PLATFORM_API_URL;
  if (!origin)
    return Response.json(
      {
        code: 'BACKEND_NOT_CONFIGURED',
        message: 'La conexión con el servidor aún no está configurada.',
      },
      { status: 503 },
    );
  const { path } = await context.params;
  if (!path.length || path.some((p) => !/^[a-zA-Z0-9_-]+$/.test(p)))
    return new Response('Invalid path', { status: 400 });
  const upstream = new URL(
    '/api/' + path.map(encodeURIComponent).join('/'),
    origin,
  );
  upstream.search = new URL(request.url).search;
  const headers = new Headers();
  for (const key of ['authorization', 'content-type']) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  try {
    let body: ArrayBuffer | undefined;
    if (!['GET', 'HEAD'].includes(request.method)) {
      const maxBytes = 6 * 1024 * 1024;
      if (Number(request.headers.get('content-length')) > maxBytes)
        return Response.json(
          { message: 'Archivo demasiado grande.' },
          { status: 413 },
        );
      const reader = request.body?.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      if (reader) {
        while (true) {
          const part = await reader.read();
          if (part.done) break;
          size += part.value.byteLength;
          if (size > maxBytes) {
            await reader.cancel();
            return Response.json(
              { message: 'Archivo demasiado grande.' },
              { status: 413 },
            );
          }
          chunks.push(part.value);
        }
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      body = bytes.buffer;
    }
    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body,
      redirect: 'manual',
      signal: AbortSignal.timeout(25000),
    });
    const outgoing = new Headers({
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    });
    for (const key of [
      'content-type',
      'content-disposition',
      'x-next-cursor',
      'x-request-id',
      'retry-after',
    ]) {
      const value = response.headers.get(key);
      if (value) outgoing.set(key, value);
    }
    return new Response(response.body, {
      status: response.status,
      headers: outgoing,
    });
  } catch {
    return Response.json(
      {
        code: 'BACKEND_UNAVAILABLE',
        message: 'No pudimos conectar con el servidor. Inténtalo de nuevo.',
      },
      { status: 502 },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
