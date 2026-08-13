(function (root, factory) {
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.ScholarlyUtils = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
    function getStorage() {
        try {
            const storage = root.localStorage;
            if (!storage || typeof storage.getItem !== 'function') return null;
            return storage;
        } catch (_) {
            return null;
        }
    }

    const storage = {
        get(key) {
            const target = getStorage();
            if (!target || typeof key !== 'string') return null;
            try {
                const value = target.getItem(key);
                return typeof value === 'string' ? value : null;
            } catch (_) {
                return null;
            }
        },

        set(key, value) {
            const target = getStorage();
            if (!target || typeof key !== 'string' || typeof value !== 'string') return false;
            try {
                target.setItem(key, value);
                return true;
            } catch (_) {
                return false;
            }
        },

        remove(key) {
            const target = getStorage();
            if (!target || typeof key !== 'string') return false;
            try {
                target.removeItem(key);
                return true;
            } catch (_) {
                return false;
            }
        },

        readJson(key, fallback) {
            const value = this.get(key);
            if (value === null) return fallback;
            try {
                return JSON.parse(value);
            } catch (_) {
                return fallback;
            }
        },

        keys() {
            const target = getStorage();
            if (!target) return [];
            try {
                const keys = [];
                for (let index = 0; index < target.length; index += 1) {
                    const key = target.key(index);
                    if (typeof key === 'string') keys.push(key);
                }
                return keys;
            } catch (_) {
                return [];
            }
        },
    };

    function safeHttpUrl(value) {
        if (typeof value !== 'string') return '';
        try {
            const url = new URL(value);
            if ((url.protocol !== 'http:' && url.protocol !== 'https:') || !url.hostname) return '';
            if (url.username || url.password) return '';
            return url.href;
        } catch (_) {
            return '';
        }
    }

    function isStringArray(value, maxItems) {
        const limit = Number.isSafeInteger(maxItems) && maxItems >= 0 ? maxItems : Number.MAX_SAFE_INTEGER;
        return Array.isArray(value) && value.length <= limit && value.every((item) => typeof item === 'string');
    }

    function isPlainObject(value) {
        if (!value || Object.prototype.toString.call(value) !== '[object Object]') return false;
        const prototype = Object.getPrototypeOf(value);
        return prototype === null || prototype === Object.prototype;
    }

    return { storage, safeHttpUrl, isStringArray, isPlainObject };
});
