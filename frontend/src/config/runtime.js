const normalizeDataSource = (value) => {
    if (value === 'api' || value === 'backend') return 'api';
    return 'mock';
};

export const runtimeConfig = {
    dataSource: normalizeDataSource(import.meta.env.VITE_DATA_SOURCE),
    apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '/api',
    apiFallbackUrl: import.meta.env.VITE_API_FALLBACK_URL || 'http://127.0.0.1:8080/api',
    requestTimeoutMs: Number(import.meta.env.VITE_API_TIMEOUT_MS || 15000),
};
