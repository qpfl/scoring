(function configureApi(global) {
    const productionOrigin = 'https://qpfl-scoring.vercel.app';
    const supportedEndpoints = new Set([
        'lineup',
        'nfl-draft',
        'rule-changes',
        'team-avatar',
        'team-name',
        'transaction',
    ]);

    function originForLocation(location) {
        const hostname = String(location?.hostname || '').toLowerCase();
        if (
            hostname === 'localhost'
            || hostname === '127.0.0.1'
            || hostname === 'qpfl.github.io'
        ) {
            return productionOrigin;
        }
        return String(location?.origin || productionOrigin).replace(/\/$/, '');
    }

    const origin = originForLocation(global.location);
    global.QPFL_API = Object.freeze({
        origin,
        url(endpoint) {
            if (!supportedEndpoints.has(endpoint)) {
                throw new Error(`Unsupported API endpoint: ${endpoint}`);
            }
            return `${origin}/api/${endpoint}`;
        },
        originForLocation,
    });
}(window));
