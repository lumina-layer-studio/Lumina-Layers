/**
 * Generate a minimal valid GLB file (a colored cube) by constructing
 * the binary format directly. No browser APIs needed.
 * Run: node scripts/generate-test-glb.mjs
 */
import { writeFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

function buildGlb() {
  // A unit cube: 8 vertices, 12 triangles (2 per face)
  const positions = new Float32Array([
    // Front face
    -0.5, -0.5,  0.5,
     0.5, -0.5,  0.5,
     0.5,  0.5,  0.5,
    -0.5,  0.5,  0.5,
    // Back face
    -0.5, -0.5, -0.5,
     0.5, -0.5, -0.5,
     0.5,  0.5, -0.5,
    -0.5,  0.5, -0.5,
  ]);

  const indices = new Uint16Array([
    0,1,2, 0,2,3, // front
    5,4,7, 5,7,6, // back
    4,0,3, 4,3,7, // left
    1,5,6, 1,6,2, // right
    3,2,6, 3,6,7, // top
    4,5,1, 4,1,0, // bottom
  ]);

  // Build the binary buffer: indices first, then positions
  const indexBytes = Buffer.from(indices.buffer);
  const posBytes = Buffer.from(positions.buffer);

  // Pad index buffer to 4-byte alignment
  const indexPadding = (4 - (indexBytes.length % 4)) % 4;
  const binBuffer = Buffer.concat([
    indexBytes,
    Buffer.alloc(indexPadding),
    posBytes,
  ]);

  const posOffset = indexBytes.length + indexPadding;

  const gltfJson = {
    asset: { version: "2.0", generator: "lumina-test-glb" },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0, name: "TestCube" }],
    meshes: [{
      primitives: [{
        attributes: { POSITION: 1 },
        indices: 0,
        mode: 4, // TRIANGLES
      }],
    }],
    accessors: [
      {
        bufferView: 0,
        componentType: 5123, // UNSIGNED_SHORT
        count: indices.length,
        type: "SCALAR",
        max: [7],
        min: [0],
      },
      {
        bufferView: 1,
        componentType: 5126, // FLOAT
        count: positions.length / 3,
        type: "VEC3",
        max: [0.5, 0.5, 0.5],
        min: [-0.5, -0.5, -0.5],
      },
    ],
    bufferViews: [
      {
        buffer: 0,
        byteOffset: 0,
        byteLength: indexBytes.length,
        target: 34963, // ELEMENT_ARRAY_BUFFER
      },
      {
        buffer: 0,
        byteOffset: posOffset,
        byteLength: posBytes.length,
        target: 34962, // ARRAY_BUFFER
      },
    ],
    buffers: [{ byteLength: binBuffer.length }],
  };

  const jsonStr = JSON.stringify(gltfJson);
  const jsonBuf = Buffer.from(jsonStr, "utf8");
  // Pad JSON chunk to 4-byte alignment with spaces (0x20)
  const jsonPadding = (4 - (jsonBuf.length % 4)) % 4;
  const jsonChunkData = Buffer.concat([jsonBuf, Buffer.alloc(jsonPadding, 0x20)]);

  // GLB structure: 12-byte header + JSON chunk + BIN chunk
  const jsonChunkHeader = Buffer.alloc(8);
  jsonChunkHeader.writeUInt32LE(jsonChunkData.length, 0);
  jsonChunkHeader.writeUInt32LE(0x4E4F534A, 4); // "JSON"

  const binChunkPadding = (4 - (binBuffer.length % 4)) % 4;
  const binChunkData = Buffer.concat([binBuffer, Buffer.alloc(binChunkPadding)]);
  const binChunkHeader = Buffer.alloc(8);
  binChunkHeader.writeUInt32LE(binChunkData.length, 0);
  binChunkHeader.writeUInt32LE(0x004E4942, 4); // "BIN\0"

  const totalLength = 12 + 8 + jsonChunkData.length + 8 + binChunkData.length;

  const glbHeader = Buffer.alloc(12);
  glbHeader.writeUInt32LE(0x46546C67, 0); // "glTF"
  glbHeader.writeUInt32LE(2, 4);           // version 2
  glbHeader.writeUInt32LE(totalLength, 8);

  return Buffer.concat([
    glbHeader,
    jsonChunkHeader, jsonChunkData,
    binChunkHeader, binChunkData,
  ]);
}

const glb = buildGlb();
const outPath = join(__dirname, "..", "public", "test.glb");
writeFileSync(outPath, glb);
console.log(`Written ${outPath} (${glb.length} bytes)`);
