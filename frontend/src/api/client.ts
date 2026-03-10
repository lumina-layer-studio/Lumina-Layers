import axios from "axios";

/**
 * Axios 实例，统一管理 API 请求基础配置。
 *
 * 注意：不设置默认 Content-Type header。
 * - 发送 JSON 时 axios 自动设置 application/json
 * - 发送 FormData 时 axios 自动设置 multipart/form-data 并附加 boundary
 * - 手动设置默认 Content-Type 会阻止 FormData 的 boundary 自动生成，导致后端 422
 */
const apiClient = axios.create({
  baseURL: "http://localhost:8000/api",
  timeout: 30_000,
});

export default apiClient;
