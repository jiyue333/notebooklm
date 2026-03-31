export const LOGO_OPTION_META = [
    { id: 'page', label: '智慧之页' },
    { id: 'spark', label: '灵感之星' },
    { id: 'orbit', label: '知识星环' },
];

export function getLogoOptions() {
    return LOGO_OPTION_META.map((item) => ({ ...item }));
}
