/*! Parse PyScript loader query strings.

Shared by micropython.html, pyodide.html, mp.html, py.html, and
harness.html. Canonical package-install key is ``deps=`` on every shell.

Query keys:
  modules, manifests  — example stems / packages/<name>.json manifests
  deps                — MIP (MicroPython) or micropip (Pyodide) packages
  packages            — harness-only extra MIP index installs (legacy path)
  debug, autotest, duration, timeout — harness / tooling flags

Exposes ``window.LoaderQuery``.
*/
(function (global) {
    'use strict';

    var SAFE_MODULE = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
    var SAFE_PACKAGE = /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/;
    var VCS_PREFIX = /^(github|gitlab|codeberg):/i;

    function parseCommaList(raw) {
        return String(raw || '')
            .split(',')
            .map(function (s) {
                s = s.trim();
                if (s.toLowerCase().endsWith('.py')) {
                    s = s.slice(0, -3);
                }
                return s;
            })
            .filter(Boolean);
    }

    function truthyFlag(val) {
        return val === '' || /^(1|true|yes)$/i.test(val);
    }

    /**
     * @param {string} search location.search or raw query (with or without '?')
     * @returns {{
     *   modules: string[],
     *   manifests: string[],
     *   deps: string[],
     *   packages: string[],
     *   entryKind: string|null,
     *   entryName: string|null,
     *   debug: boolean,
     *   autotest: boolean,
     *   autotestDuration: number,
     *   autotestTimeout: number|null
     * }}
     */
    function parse(search) {
        var modules = [];
        var manifests = [];
        var deps = [];
        var packages = [];
        var entryKind = null;
        var entryName = null;
        var debug = false;
        var autotest = false;
        var autotestDuration = 5;
        var autotestTimeout = null;
        var raw = String(search || '');
        if (raw.charAt(0) === '?') {
            raw = raw.slice(1);
        }
        raw.split('&').forEach(function (part) {
            if (!part) {
                return;
            }
            var eq = part.indexOf('=');
            var key = eq === -1 ? part : decodeURIComponent(part.slice(0, eq));
            var val =
                eq === -1
                    ? ''
                    : decodeURIComponent(part.slice(eq + 1).replace(/\+/g, ' '));
            if (key === 'modules') {
                var mlist = parseCommaList(val);
                if (!entryKind && mlist.length) {
                    entryKind = 'module';
                    entryName = mlist[0];
                }
                modules.push.apply(modules, mlist);
            } else if (key === 'manifests') {
                var flist = parseCommaList(val);
                if (!entryKind && flist.length) {
                    entryKind = 'manifest';
                    entryName = flist[0];
                }
                manifests.push.apply(manifests, flist);
            } else if (key === 'deps') {
                deps.push.apply(deps, parseCommaList(val));
            } else if (key === 'packages') {
                packages.push.apply(packages, parseCommaList(val));
            } else if (key === 'debug') {
                debug = truthyFlag(val);
            } else if (key === 'autotest') {
                autotest = truthyFlag(val);
            } else if (key === 'duration') {
                var n = parseInt(val, 10);
                if (!isNaN(n) && n > 0) {
                    autotestDuration = n;
                }
            } else if (key === 'timeout') {
                var t = parseInt(val, 10);
                if (!isNaN(t) && t > 0) {
                    autotestTimeout = t;
                }
            }
        });
        return {
            modules: modules,
            manifests: manifests,
            deps: deps,
            packages: packages,
            entryKind: entryKind,
            entryName: entryName,
            debug: debug,
            autotest: autotest,
            autotestDuration: autotestDuration,
            autotestTimeout: autotestTimeout,
        };
    }

    function isSafeDep(name) {
        if (/^https?:\/\//i.test(name)) {
            return /\.whl(\?|#|$)/i.test(name);
        }
        if (VCS_PREFIX.test(name)) {
            return true;
        }
        return SAFE_PACKAGE.test(name);
    }

    /** @returns {string[]} unsafe names (empty if plan is valid) */
    function invalidNames(plan) {
        var bad = [];
        (plan.modules || []).forEach(function (name) {
            if (!SAFE_MODULE.test(name)) {
                bad.push(name);
            }
        });
        (plan.manifests || []).forEach(function (name) {
            if (!SAFE_MODULE.test(name)) {
                bad.push(name);
            }
        });
        (plan.deps || []).forEach(function (name) {
            if (!isSafeDep(name)) {
                bad.push(name);
            }
        });
        (plan.packages || []).forEach(function (name) {
            if (!SAFE_PACKAGE.test(name)) {
                bad.push(name);
            }
        });
        return bad;
    }

    /**
     * Publish plan onto ``window.__loader*`` for Python loaders.
     * @param {object} plan from parse()
     * @param {{ ready?: boolean }} [options]
     */
    function publish(plan, options) {
        options = options || {};
        var w = global;
        w.__loaderModules = (plan.modules || []).join(',');
        w.__loaderManifests = (plan.manifests || []).join(',');
        w.__loaderDeps = (plan.deps || []).join(',');
        w.__loaderPackages = (plan.packages || []).join(',');
        w.__loaderEntryKind = plan.entryKind || '';
        w.__loaderEntry = plan.entryName || '';
        w.__loaderDebug = plan.debug ? '1' : '';
        w.__loaderAutotest = plan.autotest ? '1' : '';
        w.__loaderAutotestDuration = String(
            plan.autotestDuration != null ? plan.autotestDuration : 5
        );
        w.__loaderAutotestTimeout =
            plan.autotestTimeout != null ? String(plan.autotestTimeout) : '';
        if (options.ready) {
            w.__loaderReady = true;
        }
    }

    function titleCaseStem(stem) {
        return String(stem || '')
            .replace(/_/g, ' ')
            .replace(/\b\w/g, function (c) {
                return c.toUpperCase();
            });
    }

    global.LoaderQuery = {
        SAFE_MODULE: SAFE_MODULE,
        SAFE_PACKAGE: SAFE_PACKAGE,
        parseCommaList: parseCommaList,
        parse: parse,
        invalidNames: invalidNames,
        isSafeDep: isSafeDep,
        publish: publish,
        titleCaseStem: titleCaseStem,
    };
})(typeof window !== 'undefined' ? window : globalThis);
