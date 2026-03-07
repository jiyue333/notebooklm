const normalizeDataSource = (value) => {
    if (value === 'api' || value === 'backend') return 'api';
    return 'mock';
};

export const runtimeConfig = {
    dataSource: normalizeDataSource(import.meta.env.VITE_DATA_SOURCE),
    apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '/api',
    requestTimeoutMs: Number(import.meta.env.VITE_API_TIMEOUT_MS || 15000),
};

