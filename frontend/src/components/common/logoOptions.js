export const LOGO_OPTION_META = [
    { id: 'stack', label: '堆叠卡片' },
    { id: 'spark-notes', label: '灵感闪光' },
    { id: 'orbit', label: '知识轨道' },
];

export function getLogoOptions() {
    return LOGO_OPTION_META.map((item) => ({ ...item }));
}
