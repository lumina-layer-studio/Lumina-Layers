interface GltfParser<T> {
  parse(
    data: ArrayBuffer | string,
    path: string,
    onLoad: (model: T) => void,
    onError?: (error: ErrorEvent) => void,
  ): void;
}

const configuredLoaders = new WeakSet<object>();

/** Decode gzip left in the response body by a proxy before GLTFLoader parses it. */
export function configureGltfTransport<T>(loader: GltfParser<T>): void {
  if (configuredLoaders.has(loader)) return;
  const parse = loader.parse.bind(loader);
  loader.parse = (data, path, onLoad, onError) => {
    const header = typeof data === "string" ? null : new Uint8Array(data, 0, Math.min(2, data.byteLength));
    if (header?.[0] !== 0x1f || header[1] !== 0x8b) {
      parse(data, path, onLoad, onError);
      return;
    }

    // Normal HTTP gzip is already decoded by the browser. Only a gzip body
    // reaches this branch; keep the shared loader, decoders and cache intact.
    const body = new Response(data).body!;
    void new Response(body.pipeThrough(new DecompressionStream("gzip")))
      .arrayBuffer()
      .then((decoded) => parse(decoded, path, onLoad, onError))
      .catch((error) => onError?.(error));
  };
  configuredLoaders.add(loader);
}
