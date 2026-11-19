# Vendored front-end library

Whisper serves its one third-party browser library itself instead of loading it
from a CDN, so the CSP can be `script-src 'self'` and visitors' browsers
contact no third party.

[argon2-browser](https://www.npmjs.com/package/argon2-browser) 1.18.0 (MIT), in
`argon2-browser-1.18.0/`, copied unmodified from the npm package tarball
(`package/lib/` and `package/dist/`) after checking the tarball against the
registry's published `dist.integrity`:

| File | SHA-384 |
|---|---|
| `lib/argon2.js` | `sha384-M0v+643vWImGSGCZxDlAOQ/Ca2ShlvWHrOSQizBcd/mtr40Ho/ErB/mrWLxlQ366` |
| `dist/argon2.js` | `sha384-am7P6S/HiklM8ZO8Ihrv1tCPTFPGfEnKfUn8cqws88YeMDJAx8PJ3gCTdcS1XBuz` |
| `dist/argon2.wasm` | `sha384-jYRCJenBD5xXa9g4Cyw0KAgt/wotuIsyW5PhLq33KzsZIycIP4/ybXDi0gfuIrnj` |
| `dist/argon2-simd.wasm` | `sha384-8sZXx8hYXC56DOUVAM5b1HKxriiIdxUllDQ+e96jtDQ7P4jEcUaxZkE33bdrVwtJ` |

`lib/argon2.js` is the loader the pages include. `whisper.js` points it at
`dist/argon2-simd.wasm` when the browser supports WebAssembly SIMD (all
current browsers, about 1.3-2x faster) and at `dist/argon2.wasm` otherwise.
Both builds produce identical hashes, and identical hashes to the
`argon2-bundled.min.js` build used through 0.3.2.

Copy buttons and tooltips use the browser's Clipboard API and plain CSS (see
`whisper.js` and `style.css`), so Bootstrap and clipboard.js are no longer
used.

## Updating

1. Get the new version's `dist.tarball` URL and `dist.integrity` from
   `https://registry.npmjs.org/argon2-browser/<version>`, download the
   tarball and check its SHA-512 against `dist.integrity`.
2. Copy the four files above and `package/LICENSE` into a new
   `argon2-browser-<version>/` folder (same layout) and delete the old one.
3. Update the script path in `templates/index.html` and the table above.
4. Check that secrets created before the update still open.
